"""`protean.testing.__all__` freezes the public testing DSL surface, keeping
incidental imports and the deprecated invariant helpers out of `import *`
(#1110)."""


def _star_import():
    namespace: dict[str, object] = {}
    exec("from protean.testing import *", namespace)
    return {name for name in namespace if not name.startswith("__")}


EXPECTED = {
    "given",
    "EventLog",
    "AggregateResult",
    "ProcessResult",
    "drain",
    "process_and_wait",
    "EventSequence",
    "ProcessManagerResult",
    "ProjectionResult",
    "assert_chain",
    "assert_snapshot",
    "get_generic_test_dir",
}


def test_star_import_matches_all():
    from protean import testing

    assert _star_import() == set(testing.__all__)


def test_all_lists_the_public_dsl():
    from protean import testing

    assert set(testing.__all__) == EXPECTED


def test_deprecated_helpers_are_not_exported():
    # `assert_valid`/`assert_invalid` remain importable by name but must not be
    # dragged in by `import *`.
    exported = _star_import()
    assert "assert_valid" not in exported
    assert "assert_invalid" not in exported


def test_underscore_helpers_and_incidental_imports_are_not_exported():
    exported = _star_import()
    assert "_flatten_messages" not in exported
    assert "_event_store_of" not in exported
    # Module-level imports pulled in for implementation, not public API.
    assert "Message" not in exported
    assert "fqn" not in exported
    assert "warnings" not in exported
