"""`protean.utils.globals.__all__` narrows the module's star-export to the
three request-scoped proxies, keeping the lookup helpers and context stacks
internal (#1110)."""

EXPECTED = {"current_domain", "current_uow", "g"}


def _star_import():
    namespace: dict[str, object] = {}
    exec("from protean.utils.globals import *", namespace)
    return {name for name in namespace if not name.startswith("__")}


def test_all_lists_only_the_public_proxies():
    from protean.utils import globals as globals_mod

    assert globals_mod.__all__ == ["current_domain", "current_uow", "g"]


def test_star_import_binds_exactly_the_public_proxies():
    # RHS is the independently-derived surface, not `set(__all__)`: dropping a
    # proxy from `__all__` would then break `import *` and fail here too.
    assert _star_import() == EXPECTED


def test_incidental_imports_are_not_exported():
    # Non-underscore module-level names (imports and the module logger) that
    # `import *` would pull in without an explicit `__all__`. Underscore names
    # (`_find_domain`, the context stacks) are excluded by `import *` regardless,
    # so asserting on them would prove nothing — these do.
    exported = _star_import()
    assert "logging" not in exported
    assert "warnings" not in exported
    assert "partial" not in exported
    assert "LocalProxy" not in exported
    assert "LocalStack" not in exported
    assert "logger" not in exported
