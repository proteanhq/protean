"""The diagnostic-code registry: completeness, the breaking-change snapshot,
and the resolve/build helpers.

``protean.ir.diagnostics`` is the single source of truth for every diagnostic
code and its metadata. These tests hold three promises:

- every code has full, well-formed metadata, and the registry's code set is
  exactly the set of codes the producers actually reference (no orphan entry, no
  producer code missing from the registry);
- the code set is frozen against accidental rename/removal — a change is a
  reviewed breaking change, not a silent one;
- :func:`build_diagnostic` resolves metadata by code and reproduces the wire
  shape, and the thin ``_warnings`` channel can resolve rationale/fix by lookup.
"""

import ast
import hashlib
import tomllib
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import protean
from protean.ir.diagnostics import (
    REGISTRY,
    CodeMeta,
    Diagnostic,
    DiagnosticCode,
    ResolvingOperation,
    build_diagnostic,
    resolve,
)

# Categories a code may carry. Adding one is a deliberate change: extend this set
# in the same commit so a typo'd category ("bounded_contex") fails here.
ALLOWED_CATEGORIES = frozenset(
    {
        "aggregate_design",
        "bounded_context",
        "configuration",
        "deprecation",
        "handler_completeness",
        "invariants",
        "naming_conventions",
        "persistence",
        "unsupported",
        "usage",
        "versioning",
    }
)

# The schema's diagnostic ``level`` enum (schema.json).
ALLOWED_LEVELS = frozenset({"error", "warning", "info"})

# How a code reaches a user: a static ``protean check`` rule, a code carried on
# an exception raised at init/runtime, or a code the staleness check surfaces.
ALLOWED_KINDS = frozenset({"lint", "raise", "staleness"})

# The producers that reference diagnostic codes, relative to the source root.
# ``domain/__init__.py``, ``domain/config.py``, ``core/entity.py``, and
# ``core/value_object.py`` reference the init/runtime ``kind="raise"`` codes;
# ``ir/staleness.py`` references the ``kind="staleness"`` code; the rest
# reference the ``kind="lint"`` rules.
PRODUCER_FILES = (
    "ir/builder.py",
    "domain/validation.py",
    "domain/__init__.py",
    "domain/config.py",
    "core/entity.py",
    "core/value_object.py",
    "ir/staleness.py",
    "_deprecation.py",
)


def _src_root() -> Path:
    return Path(protean.__file__).parent


def _referenced_codes() -> set[str]:
    """Every ``DiagnosticCode.<NAME>`` referenced across the producer files."""
    referenced: set[str] = set()
    root = _src_root()
    for rel in PRODUCER_FILES:
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "DiagnosticCode"
            ):
                referenced.add(node.attr)
    return referenced


class TestRegistryCompleteness:
    def test_registry_covers_exactly_the_enum(self):
        assert set(REGISTRY) == set(DiagnosticCode)

    def test_every_code_has_wellformed_metadata(self):
        assert len(REGISTRY) > 0
        for code, meta in REGISTRY.items():
            assert isinstance(meta, CodeMeta), code
            assert meta.category in ALLOWED_CATEGORIES, (code, meta.category)
            assert meta.level in ALLOWED_LEVELS, (code, meta.level)
            assert meta.kind in ALLOWED_KINDS, (code, meta.kind)
            assert meta.meaning.strip(), f"{code} has an empty meaning"
            assert meta.rationale.strip(), f"{code} has an empty rationale"
            assert meta.fix.strip(), f"{code} has an empty fix"

    def test_registry_matches_codes_the_producers_reference(self):
        # No orphan registry entry, no producer code missing from the registry.
        referenced = _referenced_codes()
        registry_names = {code.name for code in REGISTRY}
        assert referenced == registry_names, {
            "referenced_but_unregistered": sorted(referenced - registry_names),
            "registered_but_unreferenced": sorted(registry_names - referenced),
        }


class TestGoldenSnapshot:
    # The frozen public code set. A code is a stable public identifier: renaming
    # or removing one breaks callers who match on it (CI gates, SARIF consumers,
    # suppression lists). Updating this snapshot is a DELIBERATE, REVIEWED
    # breaking change — do it in the same PR as the rename/removal, not to make a
    # red test green.
    EXPECTED_CODES = frozenset(
        {
            "ADAPTER_CALL_IN_DOMAIN",
            "AGGREGATE_NOT_NOUN",
            "AGGREGATE_NO_INVARIANTS",
            "AGGREGATE_TOO_LARGE",
            "AGGREGATE_WITHOUT_COMMAND_HANDLER",
            "CIRCULAR_CLUSTER_DEPENDENCY",
            "COMMAND_HANDLER_CROSS_CLUSTER",
            "COMMAND_NOT_IMPERATIVE",
            "CONFIG_AMBIGUOUS_ELEMENT_NAME",
            "CONFIG_ELEMENT_NOT_REGISTERED",
            "CONFIG_EVENT_STORE_NOT_INITIALIZED",
            "CONFIG_UNRESOLVED_ENV_VAR",
            "CROSS_AGGREGATE_REFERENCE",
            "DEPRECATED_CONFIG",
            "DEPRECATED_ELEMENT",
            "DEPRECATED_EMAIL",
            "DEPRECATED_FIELD",
            "DEPRECATED_IMPORT",
            "DEPRECATED_OPTION",
            "ES_AGGREGATE_NO_EVENTS",
            "ES_EVENT_MISSING_APPLY",
            "EVENT_HANDLER_FOREIGN_EVENT",
            "EVENT_NOT_PAST_TENSE",
            "EVENT_WITHOUT_DATA",
            "HANDLER_PERSISTS_AND_CALLS_OUT",
            "HANDLER_TOO_BROAD",
            "INFRA_IMPORT_IN_DOMAIN",
            "INVARIANT_POST_FAILED",
            "INVARIANT_PRE_FAILED",
            "IR_STALE",
            "LOW_POOL_SIZE",
            "PROCESS_MANAGER_UNCLOSED",
            "PROJECTION_WITHOUT_PROJECTOR",
            "PROJECTOR_HANDLES_ORPHANED_EVENT",
            "PUBLISHED_NO_EXTERNAL_BROKER",
            "QUERY_HANDLER_WITHOUT_QUERY",
            "SUBSCRIBER_NO_STREAMS",
            "UNBOUNDED_INDEXED_STRING",
            "UNHANDLED_EVENT",
            "UNINDEXED_FILTER_PATH",
            "UNRAISED_EVENT",
            "UNSUPPORTED_ELEMENT_CLASS",
            "UNUSED_COMMAND",
            "UPCASTER_GAP",
            "USAGE_CACHE_BACKED_NO_REPOSITORY",
            "USAGE_DUPLICATE_DATABASE_MODEL",
            "USAGE_ELEMENT_NOT_REGISTERED",
            "USAGE_ENRICHER_NOT_CALLABLE",
            "USAGE_NOT_A_PROJECTION",
            "USAGE_UNKNOWN_ELEMENT_TYPE",
            "VALUE_OBJECT_INVARIANT_FAILED",
            "VALUE_OBJECT_MUTABLE_FIELD",
        }
    )

    # The codes carried on init/runtime exceptions (``kind="raise"``) rather than
    # emitted by ``protean check`` (``kind="lint"``). The metadata digest below
    # does not cover ``kind``, so this freezes the lint/raise split on its own: a
    # code flipped between the two surfaces fails here, deliberately, because it
    # changes whether the code is documented in the check catalog.
    EXPECTED_RAISE_CODES = frozenset(
        {
            "CONFIG_AMBIGUOUS_ELEMENT_NAME",
            "CONFIG_ELEMENT_NOT_REGISTERED",
            "CONFIG_EVENT_STORE_NOT_INITIALIZED",
            "CONFIG_UNRESOLVED_ENV_VAR",
            "INVARIANT_POST_FAILED",
            "INVARIANT_PRE_FAILED",
            "UNSUPPORTED_ELEMENT_CLASS",
            "USAGE_CACHE_BACKED_NO_REPOSITORY",
            "USAGE_DUPLICATE_DATABASE_MODEL",
            "USAGE_ELEMENT_NOT_REGISTERED",
            "USAGE_ENRICHER_NOT_CALLABLE",
            "USAGE_NOT_A_PROJECTION",
            "USAGE_UNKNOWN_ELEMENT_TYPE",
            "VALUE_OBJECT_INVARIANT_FAILED",
        }
    )

    def test_code_set_is_frozen(self):
        actual = {code.value for code in DiagnosticCode}
        assert actual == self.EXPECTED_CODES, {
            "added (breaking if a rename)": sorted(actual - self.EXPECTED_CODES),
            "removed (breaking)": sorted(self.EXPECTED_CODES - actual),
        }

    def test_raise_kind_split_is_frozen(self):
        actual = {c.value for c, meta in REGISTRY.items() if meta.kind == "raise"}
        assert actual == self.EXPECTED_RAISE_CODES, {
            "newly raise (or wrongly flipped)": sorted(
                actual - self.EXPECTED_RAISE_CODES
            ),
            "no longer raise": sorted(self.EXPECTED_RAISE_CODES - actual),
        }

    # The codes produced by staleness_diagnostic (``kind="staleness"``), neither
    # a ``protean check`` lint rule nor an exception-carried code. Frozen on its
    # own so a code added to (or flipped into) this surface is a reviewed change.
    EXPECTED_STALENESS_CODES = frozenset({"IR_STALE"})

    def test_staleness_kind_split_is_frozen(self):
        actual = {c.value for c, meta in REGISTRY.items() if meta.kind == "staleness"}
        assert actual == self.EXPECTED_STALENESS_CODES, {
            "newly staleness": sorted(actual - self.EXPECTED_STALENESS_CODES),
            "no longer staleness": sorted(self.EXPECTED_STALENESS_CODES - actual),
        }

    # The code to command map: which codes carry a resolving operation and the
    # exact command each dispatches to. Populated only where a real command
    # clears the failure, with no invented commands. Freezing it here means
    # adding a pairing (or changing a command/args) is a reviewed change.
    EXPECTED_RESOLUTIONS = {
        "IR_STALE": ("protean-check-staleness", ("--fix",)),
    }

    def test_resolution_map_is_frozen(self):
        actual = {
            code.value: (meta.resolution.command, meta.resolution.args)
            for code, meta in REGISTRY.items()
            if meta.resolution is not None
        }
        assert actual == self.EXPECTED_RESOLUTIONS, {
            "added or changed": {
                k: v for k, v in actual.items() if self.EXPECTED_RESOLUTIONS.get(k) != v
            },
            "removed": sorted(set(self.EXPECTED_RESOLUTIONS) - set(actual)),
        }


def _meta_digest(meta: CodeMeta) -> str:
    """A stable short hash over a code's full metadata text."""
    canon = "␟".join(
        [meta.category, meta.level, meta.meaning, meta.rationale, meta.fix]
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


class TestMetadataSnapshot:
    # The frozen text of every code's metadata (category, level, meaning,
    # rationale, fix), captured as a per-code digest. The code-set snapshot above
    # freezes the identifiers; this freezes the words behind them. The rationale
    # and fix are the public, human-facing surface a code resolves to (they ride
    # the IR/SARIF/check wire), so a silent wording drift should fail the build,
    # not slip through because the string stayed non-empty.
    #
    # A red test here means a code's metadata text changed. If that change is
    # intentional, regenerate the digest for the affected code(s) in the SAME
    # commit as the edit — that is the reviewed acknowledgement that the public
    # text moved. Do not blanket-refresh to make the test green.
    EXPECTED_DIGESTS = {
        "ADAPTER_CALL_IN_DOMAIN": "b709063b030e4922",
        "AGGREGATE_NOT_NOUN": "9b8de4a5ad83aec8",
        "AGGREGATE_NO_INVARIANTS": "dcd39a6b24d9fb7b",
        "AGGREGATE_TOO_LARGE": "65f3c1889382fd95",
        "AGGREGATE_WITHOUT_COMMAND_HANDLER": "5a62e88120c81a8b",
        "CIRCULAR_CLUSTER_DEPENDENCY": "88531b85d6e29964",
        "COMMAND_HANDLER_CROSS_CLUSTER": "4f576d68764bd53c",
        "COMMAND_NOT_IMPERATIVE": "baf655f1128a527f",
        "CONFIG_AMBIGUOUS_ELEMENT_NAME": "c4d36c1d4683f4f8",
        "CONFIG_ELEMENT_NOT_REGISTERED": "eb3cd52052ab9f28",
        "CONFIG_EVENT_STORE_NOT_INITIALIZED": "c836c803ad0225f1",
        "CONFIG_UNRESOLVED_ENV_VAR": "de62569dadbc3090",
        "CROSS_AGGREGATE_REFERENCE": "dac1046534ebd07a",
        "DEPRECATED_CONFIG": "3adabed0433fa534",
        "DEPRECATED_ELEMENT": "5ae99f3b24d74d4b",
        "DEPRECATED_EMAIL": "d9dbcbba0b140002",
        "DEPRECATED_FIELD": "19ea505765933f5d",
        "DEPRECATED_IMPORT": "76194fd361610560",
        "DEPRECATED_OPTION": "41573660a59e367d",
        "ES_AGGREGATE_NO_EVENTS": "83f1637cf49c5525",
        "ES_EVENT_MISSING_APPLY": "1686b4b443812f31",
        "EVENT_HANDLER_FOREIGN_EVENT": "a691537144dd1fff",
        "EVENT_NOT_PAST_TENSE": "991ca4dd80370014",
        "EVENT_WITHOUT_DATA": "75f2114e226c119f",
        "HANDLER_PERSISTS_AND_CALLS_OUT": "ca9b600f8c1d9004",
        "HANDLER_TOO_BROAD": "13aca3a2584e4377",
        "INFRA_IMPORT_IN_DOMAIN": "e9473616069280ed",
        "INVARIANT_POST_FAILED": "304a59b149aa8f82",
        "INVARIANT_PRE_FAILED": "7fe9b51b9b73b67e",
        "IR_STALE": "773e8d3ab35252da",
        "LOW_POOL_SIZE": "e709be40fa308c30",
        "PROCESS_MANAGER_UNCLOSED": "047584f91a3ef45f",
        "PROJECTION_WITHOUT_PROJECTOR": "a0e32732676a7838",
        "PROJECTOR_HANDLES_ORPHANED_EVENT": "6f980c1bd8d0d845",
        "PUBLISHED_NO_EXTERNAL_BROKER": "728d44e069135f88",
        "QUERY_HANDLER_WITHOUT_QUERY": "7683d009f2abb890",
        "SUBSCRIBER_NO_STREAMS": "30f85527c0e2d4c7",
        "UNBOUNDED_INDEXED_STRING": "088562cdce47c001",
        "UNHANDLED_EVENT": "27be7a540757fc9e",
        "UNINDEXED_FILTER_PATH": "9addf817d45187a5",
        "UNRAISED_EVENT": "f61f2645ce7ebe2a",
        "UNSUPPORTED_ELEMENT_CLASS": "8e29c9598a8468e5",
        "UNUSED_COMMAND": "8783ef193a40845a",
        "UPCASTER_GAP": "000698e8cb76386a",
        "USAGE_CACHE_BACKED_NO_REPOSITORY": "95b3e4a196988166",
        "USAGE_DUPLICATE_DATABASE_MODEL": "88a73bad6dba0529",
        "USAGE_ELEMENT_NOT_REGISTERED": "e84da23137dfaa03",
        "USAGE_ENRICHER_NOT_CALLABLE": "5c96e4c23003e66c",
        "USAGE_NOT_A_PROJECTION": "854b5708a5ec40a5",
        "USAGE_UNKNOWN_ELEMENT_TYPE": "840400ec794f376d",
        "VALUE_OBJECT_INVARIANT_FAILED": "147df7e5751ce7c2",
        "VALUE_OBJECT_MUTABLE_FIELD": "1e01dfac9ba9bf00",
    }

    def test_metadata_text_is_frozen(self):
        actual = {code.value: _meta_digest(meta) for code, meta in REGISTRY.items()}
        drifted = {
            code: (self.EXPECTED_DIGESTS.get(code), digest)
            for code, digest in actual.items()
            if self.EXPECTED_DIGESTS.get(code) != digest
        }
        assert not drifted, {"code: (expected, actual)": drifted}

    def test_snapshot_has_an_entry_per_code(self):
        # Guards against a new code that never got a frozen digest, or a stale
        # digest left behind after a code was removed.
        assert set(self.EXPECTED_DIGESTS) == {code.value for code in DiagnosticCode}

    def test_digest_detects_a_text_change(self):
        # Proves the digest actually reacts to a wording edit — a snapshot that
        # hashed to a constant would pass test_metadata_text_is_frozen vacuously.
        code = DiagnosticCode.AGGREGATE_TOO_LARGE
        meta = REGISTRY[code]
        tweaked = CodeMeta(
            category=meta.category,
            level=meta.level,
            meaning=meta.meaning,
            rationale=meta.rationale,
            fix=meta.fix + " (edited)",
        )
        assert _meta_digest(tweaked) != _meta_digest(meta)


class TestResolve:
    def test_resolve_returns_registry_metadata(self):
        for code in DiagnosticCode:
            assert resolve(code) is REGISTRY[code]

    def test_warnings_channel_code_resolves_rationale_and_fix(self):
        # LOW_POOL_SIZE is emitted only on the thin ``_warnings`` channel, which
        # carries code + context and no rule block. Its rationale/fix must still
        # be resolvable by lookup so the "every diagnostic names its fix"
        # contract holds for it.
        meta = resolve(DiagnosticCode.LOW_POOL_SIZE)
        assert meta.rationale.strip()
        assert meta.fix.strip()


class TestBuildDiagnostic:
    def test_resolves_defaults_from_registry(self):
        code = DiagnosticCode.AGGREGATE_TOO_LARGE
        meta = REGISTRY[code]
        d = build_diagnostic(code, element="app.Order", message="too big")

        assert d["code"] == "AGGREGATE_TOO_LARGE"
        # A plain str, not an enum member, on the wire.
        assert type(d["code"]) is str
        assert d["category"] == meta.category
        assert d["level"] == meta.level
        assert d["element"] == "app.Order"
        assert d["message"] == "too big"
        assert d["rule"] == {"rationale": meta.rationale, "fix": meta.fix}
        assert d["suggestion"] == meta.fix
        assert "field" not in d

    def test_field_included_only_when_given(self):
        code = DiagnosticCode.DEPRECATED_FIELD
        without = build_diagnostic(code, element="app.Order", message="m")
        assert "field" not in without

        withf = build_diagnostic(code, element="app.Order", message="m", field="tags")
        assert withf["field"] == "tags"

    def test_overrides_win_over_registry(self):
        code = DiagnosticCode.DEPRECATED_OPTION
        d = build_diagnostic(
            code,
            element="app.Order",
            message="m",
            level="warning",
            rationale="site rationale",
            fix="site fix",
        )
        assert d["level"] == "warning"
        assert d["rule"] == {"rationale": "site rationale", "fix": "site fix"}
        # suggestion still defaults to the resolved (overridden) fix.
        assert d["suggestion"] == "site fix"

    def test_suggestion_override_is_independent_of_fix(self):
        d = build_diagnostic(
            DiagnosticCode.UNBOUNDED_INDEXED_STRING,
            element="app.Order",
            message="m",
            suggestion="name = String(max_length=255)",
        )
        assert d["suggestion"] == "name = String(max_length=255)"
        # fix stays the registry canonical, distinct from suggestion.
        assert d["rule"]["fix"] == REGISTRY[DiagnosticCode.UNBOUNDED_INDEXED_STRING].fix

    def test_return_shape_matches_typed_diagnostic_keys(self):
        d = build_diagnostic(
            DiagnosticCode.UNHANDLED_EVENT, element="app.Thing", message="m"
        )
        assert set(Diagnostic.__required_keys__) == set(d)
        assert "field" in Diagnostic.__optional_keys__
        assert "location" in Diagnostic.__optional_keys__
        assert "resolving_operation" in Diagnostic.__optional_keys__

    def test_resolving_operation_attached_from_registry(self):
        # A code that maps to a resolving command carries the operation as a
        # structured {command, args, display} block, resolved from the registry.
        d = build_diagnostic(DiagnosticCode.IR_STALE, element="app.domain", message="m")
        assert d["resolving_operation"] == {
            "command": "protean-check-staleness",
            "args": ["--fix"],
            "display": "protean-check-staleness --fix",
        }

    def test_resolving_operation_omitted_when_code_has_no_command(self):
        # Negative: a code with no resolving command carries no field, and no
        # command is invented.
        d = build_diagnostic(
            DiagnosticCode.UNHANDLED_EVENT, element="app.Thing", message="m"
        )
        assert "resolving_operation" not in d

    def test_location_included_only_when_given(self):
        without = build_diagnostic(
            DiagnosticCode.CONFIG_UNRESOLVED_ENV_VAR, element="d", message="m"
        )
        assert "location" not in without

        withloc = build_diagnostic(
            DiagnosticCode.CONFIG_UNRESOLVED_ENV_VAR,
            element="d",
            message="m",
            location="Config2._replace_env_var",
        )
        assert withloc["location"] == "Config2._replace_env_var"


class TestResolvingOperation:
    def test_render_joins_command_and_args(self):
        op = ResolvingOperation("protean-check-staleness", ("--fix",))
        assert op.render() == "protean-check-staleness --fix"

    def test_render_with_no_args_is_the_bare_command(self):
        op = ResolvingOperation("protean-check-staleness")
        assert op.render() == "protean-check-staleness"

    def test_as_wire_carries_structure_and_display(self):
        op = ResolvingOperation("protean-check-staleness", ("--fix", "--dir=.protean"))
        assert op.as_wire() == {
            "command": "protean-check-staleness",
            "args": ["--fix", "--dir=.protean"],
            "display": "protean-check-staleness --fix --dir=.protean",
        }

    def test_is_frozen(self):
        op = ResolvingOperation("protean-check-staleness", ("--fix",))
        with pytest.raises(FrozenInstanceError):
            op.command = "other"  # type: ignore[misc]


class TestResolutionCommandsAreReal:
    """The command a diagnostic names must be a command that actually exists.

    A resolving operation's whole promise is "an agent can run this directly."
    The command is a bare string in the registry; the console script that makes
    it runnable is declared separately in ``pyproject.toml``. Tie the two
    together so a rename or typo on either side fails here, instead of handing an
    agent a "command not found". This is the same guard shape the docs-code
    catalogs use (`tests/test_diagnostic_codes_are_documented.py`).
    """

    def _declared_scripts(self) -> set[str]:
        pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return set(data["project"]["scripts"])

    def test_there_are_resolution_commands_to_check(self):
        # Guards against a vacuous pass if the resolution map ever empties out.
        commands = {
            m.resolution.command for m in REGISTRY.values() if m.resolution is not None
        }
        assert commands

    def test_every_resolution_command_is_a_declared_console_script(self):
        scripts = self._declared_scripts()
        missing = {
            m.resolution.command
            for m in REGISTRY.values()
            if m.resolution is not None and m.resolution.command not in scripts
        }
        assert not missing, (
            f"resolution commands not declared in [project.scripts]: "
            f"{sorted(missing)}. Add the console script to pyproject.toml, or fix "
            "the command string in the diagnostics registry so it names a real "
            "command."
        )
