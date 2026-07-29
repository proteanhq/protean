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
import warnings

import pytest

from protean import Domain
from protean._deprecation import (
    _REMOVAL_WARNINGS,
    DEPRECATIONS,
    Deprecation,
    RemovedInProtean018Warning,
    RemovedInProtean10Warning,
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


class TestRegistryCompleteness:
    def test_registry_holds_twelve_active_deprecations(self) -> None:
        assert len(DEPRECATIONS) == 12

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

    def test_runtime_entry_without_reason_raises(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            Deprecation(
                slug="x", name="x", since="0.1", removal="1.0.0", detection="runtime"
            )


class TestCheckArm:
    """Every ``detection='check'`` entry fires on the fixture domain, and the
    firing diagnostic reports its removal version."""

    def test_all_eight_check_entries_are_detected_with_removal_version(self) -> None:
        ir = IRBuilder(_build_audit_domain()).build()
        messages = _deprecation_messages(ir)

        check_entries = [e for e in DEPRECATIONS.values() if e.detection == "check"]
        assert len(check_entries) == 8, "expected 8 statically-detectable deprecations"

        for entry in check_entries:
            hits = [
                m
                for m in messages
                if entry.detection_hint in m and f"v{entry.removal}" in m
            ]
            assert hits, (
                f"No firing diagnostic for {entry.slug} "
                f"(hint={entry.detection_hint!r}, removal v{entry.removal}). "
                f"Messages: {messages}"
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


class TestRuntimeArm:
    """Every ``detection='runtime'`` entry fires its per-version warning."""

    def test_all_four_runtime_entries_recorded(self) -> None:
        runtime = [e for e in DEPRECATIONS.values() if e.detection == "runtime"]
        assert len(runtime) == 4

    def test_get_email_provider_warns_removed_in_v1(self) -> None:
        domain = Domain(name="RuntimeArmEmail")
        domain.init(traverse=False)
        with pytest.warns(RemovedInProtean10Warning, match=r"v1\.0\.0"):
            with contextlib.suppress(Exception):
                domain.get_email_provider("default")

    def test_send_email_warns_removed_in_v1(self) -> None:
        domain = Domain(name="RuntimeArmSend")
        domain.init(traverse=False)
        with pytest.warns(RemovedInProtean10Warning, match=r"v1\.0\.0"):
            with contextlib.suppress(Exception):
                domain.send_email(object())

    def test_assert_valid_warns_removed_in_v018(self) -> None:
        with pytest.warns(RemovedInProtean018Warning, match=r"v0\.18\.0"):
            assert_valid(lambda: None)

    def test_assert_invalid_warns_removed_in_v018(self) -> None:
        def _raises() -> None:
            raise ValidationError({"field": ["bad"]})

        with pytest.warns(RemovedInProtean018Warning, match=r"v0\.18\.0"):
            assert_invalid(_raises)


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

    def test_from_import_util_name_is_flagged(self) -> None:
        src = "from protean.utils import generate_identity\n"
        assert self._scan(src) == [("util", "protean.utils.generate_identity")]

    def test_attribute_access_util_name_is_flagged(self) -> None:
        src = "import protean.utils\ny = protean.utils.utcnow_func\n"
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
