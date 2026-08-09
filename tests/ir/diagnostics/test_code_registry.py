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
from pathlib import Path

import protean
from protean.ir.diagnostics import (
    REGISTRY,
    CodeMeta,
    Diagnostic,
    DiagnosticCode,
    build_diagnostic,
    resolve,
)

# Categories a code may carry. Adding one is a deliberate change: extend this set
# in the same commit so a typo'd category ("bounded_contex") fails here.
ALLOWED_CATEGORIES = frozenset(
    {
        "aggregate_design",
        "bounded_context",
        "deprecation",
        "handler_completeness",
        "naming_conventions",
        "persistence",
        "versioning",
    }
)

# The schema's diagnostic ``level`` enum (schema.json).
ALLOWED_LEVELS = frozenset({"error", "warning", "info"})

# The producers that reference diagnostic codes, relative to the source root.
PRODUCER_FILES = (
    "ir/builder.py",
    "domain/validation.py",
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
            "HANDLER_TOO_BROAD",
            "INFRA_IMPORT_IN_DOMAIN",
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
            "UNUSED_COMMAND",
            "UPCASTER_GAP",
            "VALUE_OBJECT_MUTABLE_FIELD",
        }
    )

    def test_code_set_is_frozen(self):
        actual = {code.value for code in DiagnosticCode}
        assert actual == self.EXPECTED_CODES, {
            "added (breaking if a rename)": sorted(actual - self.EXPECTED_CODES),
            "removed (breaking)": sorted(self.EXPECTED_CODES - actual),
        }


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
