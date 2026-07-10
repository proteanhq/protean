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


def test_star_import_binds_exactly_the_public_dsl():
    # RHS is the hardcoded EXPECTED surface, not `set(__all__)`: a name silently
    # dropped from `__all__` (and thus from `import *`) is caught here too.
    assert _star_import() == EXPECTED


def test_all_lists_the_public_dsl():
    from protean import testing

    assert set(testing.__all__) == EXPECTED


def test_deprecated_helpers_are_not_exported():
    # `assert_valid`/`assert_invalid` remain importable by name but must not be
    # dragged in by `import *`.
    exported = _star_import()
    assert "assert_valid" not in exported
    assert "assert_invalid" not in exported


def test_incidental_imports_are_not_exported():
    # Non-underscore module-level names that `import *` would drag in without an
    # explicit `__all__` (the `fqn` helper alias, the `Message` import, the
    # `warnings` module). Underscore helpers are excluded by `import *`
    # regardless of `__all__`, so they are not asserted here.
    exported = _star_import()
    assert "Message" not in exported
    assert "fqn" not in exported
    assert "warnings" not in exported
