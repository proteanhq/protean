"""Deprecation-coverage audit — every active deprecation must be detectable.

The registry in ``protean._deprecation`` is the single source of truth for every
active framework-API deprecation. This audit enforces the two arms of that
contract:

- every ``detection="check"`` entry has a ``protean check`` rule that fires on a
  fixture domain exercising the deprecated path, and the firing diagnostic
  reports the entry's removal version;
- every ``detection="runtime"`` entry records why ``check`` cannot see it and is
  covered by its per-version ``DeprecationWarning``.

If a new deprecation is added without wiring detection (or without a registry
entry at its warn site at all), this audit fails.
"""

import ast
import contextlib
import re
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

from protean import Domain
from protean._deprecation import (
    _REMOVAL_WARNINGS,
    DEPRECATIONS,
    Deprecation,
)
from protean.exceptions import ValidationError
from protean.fields import List, String
from protean.ir.builder import IRBuilder
from protean.testing import assert_invalid, assert_valid
from tests.ir.support import deprecated_usage_domain, infra_import_domain


def _build_audit_domain() -> Domain:
    """One domain that exercises every ``detection='check'`` deprecated path."""
    domain = Domain(name="DeprecationAudit", root_path=".")

    # Non-default ``email_providers`` block (DEPRECATED_CONFIG). Mutated after
    # construction, so it is the check rule — not ``load_config``'s bootstrap
    # warning — that this audit exercises.
    domain.config["email_providers"] = {
        "default": {
            "provider": "protean.adapters.DummyEmailProvider",
            "DEFAULT_FROM_EMAIL": "custom@example.com",
        },
    }

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        @domain.aggregate(is_event_sourced=True)  # DEPRECATED_OPTION
        class AliasOrder:
            name = String(max_length=50)

        @domain.aggregate
        class PickledOrder:
            tags = List(String(max_length=10), pickled=True)  # DEPRECATED_FIELD

        @domain.command(part_of="PickledOrder", published=True)  # DEPRECATED_OPTION
        class DoThing:
            name = String(max_length=50)

        @domain.email  # DEPRECATED_EMAIL
        class WelcomeMail:
            pass

        # Method / Nested / protean.utils — on-disk DEPRECATED_IMPORT scan.
        domain.register(deprecated_usage_domain.DeprecatedUsageOrder)

        domain.init(traverse=False)

    return domain


def _deprecation_messages(ir: dict) -> list[str]:
    return [d["message"] for d in ir["diagnostics"] if d["category"] == "deprecation"]


def _deprecation_diagnostics(ir: dict) -> list[dict]:
    return [d for d in ir["diagnostics"] if d["category"] == "deprecation"]


class TestRegistryCompleteness:
    def test_registry_holds_fourteen_active_deprecations(self) -> None:
        assert len(DEPRECATIONS) == 14

    def test_every_entry_is_well_formed(self) -> None:
        for slug, entry in DEPRECATIONS.items():
            assert entry.slug == slug
            assert entry.name
            assert entry.since
            # A registered removal version must resolve to a warning class.
            assert entry.removal in _REMOVAL_WARNINGS
            assert entry.detection in ("check", "runtime")

    def test_check_entries_have_a_hint_runtime_entries_have_a_reason(self) -> None:
        for entry in DEPRECATIONS.values():
            if entry.detection == "check":
                assert entry.detection_hint, entry.slug
                assert entry.reason is None, entry.slug
            else:
                assert entry.reason, entry.slug
                assert entry.detection_hint is None, entry.slug


class TestDeprecationValidation:
    """The registry's own guardrails: an entry cannot be built malformed."""

    def test_unknown_removal_version_raises(self) -> None:
        with pytest.raises(ValueError, match="removal version"):
            Deprecation(
                slug="x",
                name="x",
                since="0.1",
                removal="9.9.9",
                detection="runtime",
                reason="r",
            )

    def test_unknown_detection_raises(self) -> None:
        with pytest.raises(ValueError, match="expected 'check' or 'runtime'"):
            Deprecation(
                slug="x", name="x", since="0.1", removal="1.0.0", detection="maybe"
            )

    def test_check_entry_without_hint_raises(self) -> None:
        with pytest.raises(ValueError, match="detection_hint"):
            Deprecation(
                slug="x", name="x", since="0.1", removal="1.0.0", detection="check"
            )

    def test_check_entry_without_code_raises(self) -> None:
        with pytest.raises(ValueError, match="check_code"):
            Deprecation(
                slug="x",
                name="x",
                since="0.1",
                removal="1.0.0",
                detection="check",
                detection_hint="hint",
            )

    def test_check_entry_with_reason_raises(self) -> None:
        with pytest.raises(ValueError, match="runtime `reason`"):
            Deprecation(
                slug="x",
                name="x",
                since="0.1",
                removal="1.0.0",
                detection="check",
                detection_hint="hint",
                check_code="DEPRECATED_X",
                reason="should not be here",
            )

    def test_runtime_entry_without_reason_raises(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            Deprecation(
                slug="x", name="x", since="0.1", removal="1.0.0", detection="runtime"
            )

    def test_runtime_entry_with_static_hint_raises(self) -> None:
        with pytest.raises(ValueError, match="detection_hint/check_code"):
            Deprecation(
                slug="x",
                name="x",
                since="0.1",
                removal="1.0.0",
                detection="runtime",
                reason="r",
                detection_hint="hint",
            )


class TestRegistryIsTheOnlyWarnPath:
    """The central guarantee of #1121: a framework-API deprecation cannot warn
    without a registry entry, because every warn site routes through
    ``warn_from_registry`` / ``deprecated_from_registry`` (which read the entry).

    A pure registry can drift from reality — a future
    ``warn_deprecated("--foo", removal="1.0.0")`` would warn fine and be invisible
    to this audit, which only enumerates ``DEPRECATIONS``. This source scan closes
    that gap: it fails if any ``src/protean`` module reaches for the low-level
    ``warn_deprecated`` / ``@deprecated`` primitives directly, outside the
    allowlisted user-declared-event site.
    """

    # ``core/aggregate.py`` warns for a *user*-declared deprecated event (the
    # ``removal`` comes from the user's event meta, not the framework registry),
    # so it legitimately uses the low-level primitive. It is not a framework-API
    # deprecation and is exempt.
    _ALLOWLIST = frozenset({"core/aggregate.py"})

    @staticmethod
    def _uses_bare_primitive(tree: ast.AST) -> bool:
        """True if ``tree`` calls ``warn_deprecated`` or applies ``@deprecated``,
        whether reached by bare name (``warn_deprecated(...)``) or by attribute
        access (``protean._deprecation.warn_deprecated(...)``). Shared between
        the real-source-tree scan below and the synthetic-snippet unit tests in
        ``TestBarePrimitiveMatchForms``.
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id == "warn_deprecated")
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "warn_deprecated"
                )
            ):
                return True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    target = dec.func if isinstance(dec, ast.Call) else dec
                    if (isinstance(target, ast.Name) and target.id == "deprecated") or (
                        isinstance(target, ast.Attribute)
                        and target.attr == "deprecated"
                    ):
                        return True
        return False

    @classmethod
    def _bare_primitive_sites(cls) -> set[str]:
        import protean

        root = Path(protean.__file__).parent
        sites: set[str] = set()
        for path in sorted(root.rglob("*.py")):
            # ``_deprecation.py`` DEFINES the primitives and the registry
            # wrappers that legitimately call them; skip it.
            if path.name == "_deprecation.py":
                continue
            rel = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if cls._uses_bare_primitive(tree):
                sites.add(rel)
        return sites

    def test_no_framework_site_bypasses_the_registry(self) -> None:
        offenders = self._bare_primitive_sites() - self._ALLOWLIST
        assert not offenders, (
            "These modules call the low-level warn_deprecated/@deprecated "
            "primitives directly instead of routing through the registry "
            f"(warn_from_registry / deprecated_from_registry): {sorted(offenders)}. "
            "A framework-API deprecation must have a DEPRECATIONS entry."
        )

    def test_allowlisted_site_still_exists(self) -> None:
        # If the user-event site is refactored away, trim the allowlist so it
        # cannot silently excuse a future framework bypass.
        assert self._bare_primitive_sites() >= self._ALLOWLIST, (
            "Allowlisted bare-primitive site(s) no longer present; trim "
            f"TestRegistryIsTheOnlyWarnPath._ALLOWLIST: {sorted(self._ALLOWLIST)}."
        )


class TestBarePrimitiveMatchForms:
    """Direct tests of the bare-primitive AST match across bare-name and
    attribute-access spellings, so a bypass via ``protean._deprecation.foo``
    is provably caught and not just "no real site happens to use it today"."""

    @staticmethod
    def _matches(src: str) -> bool:
        return TestRegistryIsTheOnlyWarnPath._uses_bare_primitive(ast.parse(src))

    def test_bare_name_call_is_flagged(self) -> None:
        assert self._matches("warn_deprecated('x', removal='1.0.0')\n")

    def test_attribute_access_call_is_flagged(self) -> None:
        assert self._matches(
            "import protean._deprecation\n"
            "protean._deprecation.warn_deprecated('x', removal='1.0.0')\n"
        )

    def test_bare_name_decorator_is_flagged(self) -> None:
        assert self._matches("@deprecated\ndef foo(): ...\n")

    def test_attribute_access_decorator_is_flagged(self) -> None:
        assert self._matches("@protean._deprecation.deprecated\ndef foo(): ...\n")

    def test_unrelated_call_is_not_flagged(self) -> None:
        assert not self._matches("warn('x')\nprotean.other.thing()\n")


class TestCheckArm:
    """Every ``detection='check'`` entry fires on the fixture domain, and the
    firing diagnostic reports its removal version."""

    def test_all_eight_check_entries_are_detected_with_removal_version(self) -> None:
        ir = IRBuilder(_build_audit_domain()).build()
        diagnostics = _deprecation_diagnostics(ir)

        check_entries = [e for e in DEPRECATIONS.values() if e.detection == "check"]
        assert len(check_entries) == 8, "expected 8 statically-detectable deprecations"

        for entry in check_entries:
            # Tie the entry to a diagnostic emitted by ITS OWN rule (matching the
            # entry's ``check_code``), not any deprecation message. Otherwise a
            # broken rule can ride on another rule's message: the email element
            # and the ``email_providers`` config both say "email subsystem", and
            # every message carries "v1.0.0", so a message-substring match alone
            # would report the email element covered from the config diagnostic.
            hits = [
                d
                for d in diagnostics
                if d["code"] == entry.check_code
                and entry.detection_hint in d["message"]
                and f"v{entry.removal}" in d["message"]
            ]
            assert hits, (
                f"No firing diagnostic for {entry.slug} "
                f"(code={entry.check_code}, hint={entry.detection_hint!r}, "
                f"removal v{entry.removal}). "
                f"Diagnostics: {[(d['code'], d['message']) for d in diagnostics]}"
            )

    def test_import_scan_reports_method_nested_and_utils(self) -> None:
        ir = IRBuilder(_build_audit_domain()).build()
        imports = [
            d["message"] for d in ir["diagnostics"] if d["code"] == "DEPRECATED_IMPORT"
        ]
        joined = " ".join(imports)
        assert "Method" in joined
        assert "Nested" in joined
        assert "protean.utils.generate_identity" in joined

    def test_pickled_false_also_fires_deprecated_field(self) -> None:
        # The residue marker is set for ANY passed ``pickled`` value, not just
        # ``True`` (the flag is inert either way). ``pickled=False`` must still
        # trip DEPRECATED_FIELD, or a domain that "turned pickling off" would
        # quietly keep the dead argument with no check nudge.
        domain = Domain(name="PickledFalseAudit", root_path=".")

        @domain.aggregate
        class Order:
            tags = List(String(max_length=10), pickled=False)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        entry = DEPRECATIONS["list_pickled"]
        hits = [
            d
            for d in _deprecation_diagnostics(ir)
            if d["code"] == entry.check_code and entry.detection_hint in d["message"]
        ]
        assert hits, "pickled=False did not fire DEPRECATED_FIELD"


def _trigger_get_email_provider() -> None:
    domain = Domain(name="RuntimeArmEmail")
    domain.init(traverse=False)
    with contextlib.suppress(Exception):
        domain.get_email_provider("default")


def _trigger_send_email() -> None:
    domain = Domain(name="RuntimeArmSend")
    domain.init(traverse=False)
    with contextlib.suppress(Exception):
        domain.send_email(object())


def _trigger_assert_valid() -> None:
    assert_valid(lambda: None)


def _trigger_assert_invalid() -> None:
    def _raises() -> None:
        raise ValidationError({"field": ["bad"]})

    assert_invalid(_raises)


def _runtime_arm_update_domain() -> tuple[Domain, type]:
    """A tiny built domain with one persistable aggregate for the update arms."""
    domain = Domain(name="RuntimeArmUpdate")

    @domain.aggregate
    class Thing:
        name = String(max_length=50)

    domain.init(traverse=False)
    return domain, Thing


def _trigger_dao_update() -> None:
    domain, Thing = _runtime_arm_update_domain()
    with domain.domain_context():
        dao = domain.repository_for(Thing)._dao
        thing = dao.create(name="before")
        dao.update(thing, name="after")


def _trigger_queryset_update() -> None:
    domain, Thing = _runtime_arm_update_domain()
    with domain.domain_context():
        dao = domain.repository_for(Thing)._dao
        dao.create(name="before")
        dao.query.filter(name="before").update(name="after")


# Each runtime deprecation's slug → a callable that exercises its deprecated
# path. Keyed by slug so the completeness test below can prove the map and the
# registry's runtime arm stay in lock-step: adding a runtime entry without a
# trigger here (or vice versa) fails the audit.
_RUNTIME_TRIGGERS: dict[str, Callable[[], None]] = {
    "get_email_provider": _trigger_get_email_provider,
    "send_email": _trigger_send_email,
    "assert_valid": _trigger_assert_valid,
    "assert_invalid": _trigger_assert_invalid,
    "dao_update": _trigger_dao_update,
    "queryset_update": _trigger_queryset_update,
}


class TestRuntimeArm:
    """Every ``detection='runtime'`` entry fires its per-version warning.

    Registry-driven and symmetric with the check arm: the trigger map is
    reconciled against the registry, then every runtime entry is exercised and
    its warning class and removal version are asserted from the entry itself.
    """

    def test_every_runtime_entry_has_a_trigger(self) -> None:
        runtime = {slug for slug, e in DEPRECATIONS.items() if e.detection == "runtime"}
        assert runtime == set(_RUNTIME_TRIGGERS), (
            "Every runtime deprecation needs a trigger proving its warning fires. "
            f"Registry-only (no trigger): {runtime - set(_RUNTIME_TRIGGERS)}; "
            f"trigger-only (no entry): {set(_RUNTIME_TRIGGERS) - runtime}."
        )

    @pytest.mark.parametrize("slug", list(_RUNTIME_TRIGGERS))
    def test_runtime_entry_fires_its_per_version_warning(self, slug: str) -> None:
        entry = DEPRECATIONS[slug]
        expected = _REMOVAL_WARNINGS[entry.removal]
        with pytest.warns(expected, match=rf"v{re.escape(entry.removal)}"):
            _RUNTIME_TRIGGERS[slug]()


class TestNegativeCoverage:
    """Guard the new rules against false positives."""

    def test_clean_domain_emits_no_new_deprecation_codes(self) -> None:
        domain = Domain(name="CleanDomain", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)
            tags = List(String(max_length=10))  # no pickled= → no residue

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = {d["code"] for d in ir["diagnostics"]}
        assert "DEPRECATED_CONFIG" not in codes
        assert "DEPRECATED_IMPORT" not in codes
        assert "DEPRECATED_FIELD" not in codes

    def test_default_email_providers_block_stays_silent(self) -> None:
        # A domain that never touches ``email_providers`` keeps the default
        # block, so the equality guard suppresses DEPRECATED_CONFIG.
        domain = Domain(name="DefaultEmail", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert not [d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_CONFIG"]

    def test_non_deprecated_import_module_is_not_flagged(self) -> None:
        # ``infra_import_domain`` imports only live symbols (String, ValueObject,
        # InlineBroker) — none deprecated — so the import scan stays quiet.
        domain = Domain(name="NoDeprecatedImports", root_path=".")
        domain.register(infra_import_domain.Money)
        domain.register(infra_import_domain.InfraOrder)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert not [d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_IMPORT"]

    def test_list_without_pickled_leaves_no_residue(self) -> None:
        spec = List(String(max_length=10))
        assert getattr(spec, "_pickled_deprecated", False) is False


class TestImportScanForms:
    """Direct tests of the static AST scan across every import form it accepts,
    so each detection branch is exercised without a registered-element module."""

    @staticmethod
    def _scan(src: str) -> list[tuple[str, str]]:
        return IRBuilder._find_deprecated_import_uses(ast.parse(src))

    def test_from_import_field_call_is_flagged(self) -> None:
        src = "from protean.fields import Method\nx = Method('a')\n"
        assert self._scan(src) == [("field", "Method")]

    def test_aliased_from_import_field_call_is_flagged(self) -> None:
        src = "from protean.fields import Nested as N\nx = N('a')\n"
        assert self._scan(src) == [("field", "Nested")]

    def test_attribute_call_field_is_flagged(self) -> None:
        src = "import protean.fields\nx = protean.fields.Method('a')\n"
        assert self._scan(src) == [("field", "Method")]

    def test_whole_module_import_alias_field_call_is_flagged(self) -> None:
        # ``import protean.fields as pf`` still routes through the runtime
        # deprecation warning on ``pf.Method(...)``, so the scan must catch it.
        src = "import protean.fields as pf\nx = pf.Method('a')\n"
        assert self._scan(src) == [("field", "Method")]

    def test_from_import_util_name_is_flagged(self) -> None:
        src = "from protean.utils import generate_identity\n"
        assert self._scan(src) == [("util", "protean.utils.generate_identity")]

    def test_attribute_access_util_name_is_flagged(self) -> None:
        src = "import protean.utils\ny = protean.utils.utcnow_func\n"
        assert self._scan(src) == [("util", "protean.utils.utcnow_func")]

    def test_whole_module_import_alias_util_name_is_flagged(self) -> None:
        src = "import protean.utils as u\ny = u.utcnow_func\n"
        assert self._scan(src) == [("util", "protean.utils.utcnow_func")]

    def test_bare_field_import_without_call_is_not_flagged(self) -> None:
        # The import is the surface, but the call is the usage — a never-used
        # import must not fire (matches the runtime warning, which fires on
        # instantiation).
        src = "from protean.fields import Method\n"
        assert self._scan(src) == []

    def test_non_deprecated_util_name_is_not_flagged(self) -> None:
        # ``fqn`` is a live export, and the underscore implementations are the
        # framework's own — neither is a deprecated public shim.
        src = (
            "import protean.utils\n"
            "a = protean.utils.fqn\n"
            "b = protean.utils._generate_identity\n"
        )
        assert self._scan(src) == []

    def test_impure_attribute_base_is_not_flagged(self) -> None:
        # A plumbing name reached off a non-``protean.utils`` base (here a call
        # result) is not attributable to the module and must be ignored.
        src = "get_utils().generate_identity\n"
        assert self._scan(src) == []
