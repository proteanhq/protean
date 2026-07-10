"""`protean.utils.globals.__all__` narrows the module's star-export to the
three request-scoped proxies, keeping the lookup helpers and context stacks
internal (#1110)."""


def _star_import():
    namespace: dict[str, object] = {}
    exec("from protean.utils.globals import *", namespace)
    return {name for name in namespace if not name.startswith("__")}


def test_all_lists_only_the_public_proxies():
    from protean.utils import globals as globals_mod

    assert globals_mod.__all__ == ["current_domain", "current_uow", "g"]


def test_star_import_matches_all():
    from protean.utils import globals as globals_mod

    assert _star_import() == set(globals_mod.__all__)


def test_internal_helpers_are_not_exported():
    exported = _star_import()
    assert "_find_domain" not in exported
    assert "_find_uow" not in exported
    assert "_lookup_domain_object" not in exported
    assert "_domain_context_stack" not in exported
    assert "_uow_context_stack" not in exported
