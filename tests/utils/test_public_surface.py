"""`protean.utils` public surface.

`__all__` is trimmed to the config enums, ``DomainObjects``, ``get_version`` and
the injectable clock seam (``Clock`` / ``SystemClock``).
Six plumbing helpers that were historically importable stay reachable through a
module ``__getattr__`` for one deprecation window, each emitting
``RemovedInProtean10Warning`` on access and delegating to its underscore-prefixed
implementation. Framework code imports the underscore names directly and never
self-warns.
"""

import warnings

import pytest

from protean import utils
from protean._deprecation import RemovedInProtean10Warning

KEPT = {
    "Cache",
    "Clock",
    "Database",
    "DomainObjects",
    "IdentityStrategy",
    "IdentityType",
    "Processing",
    "SystemClock",
    "get_version",
}

# Old public name -> its live underscore-prefixed implementation.
DEPRECATED = {
    "derive_element_class": utils._derive_element_class,
    "generate_identity": utils._generate_identity,
    "fully_qualified_name": utils._fully_qualified_name,
    "convert_str_values_to_list": utils._convert_str_values_to_list,
    "TypeMatcher": utils._TypeMatcher,
    "utcnow_func": utils._utcnow_func,
}


def _star_import():
    namespace: dict[str, object] = {}
    exec("from protean.utils import *", namespace)
    return {name for name in namespace if not name.startswith("__")}


def test_all_is_the_trimmed_surface():
    assert set(utils.__all__) == KEPT


def test_star_import_matches_all():
    # Star-import respects `__all__`, so the deprecated names are not pulled in
    # and no deprecation warning is emitted during the import itself.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        exported = _star_import()
    assert exported == set(utils.__all__)


@pytest.mark.parametrize("name, impl", sorted(DEPRECATED.items()))
def test_deprecated_plumbing_warns_and_delegates(name, impl):
    with pytest.warns(RemovedInProtean10Warning) as record:
        obj = getattr(utils, name)

    # Returns the live implementation, identity-equal to the underscore spelling.
    assert obj is impl
    # The warning message is fully pinned: the qualified name, the "no public
    # replacement" clause, and the 1.0 removal version. Asserting only
    # `name in message` would be trivially satisfied since the message is built
    # from `name`.
    assert str(record[0].message) == (
        f"`protean.utils.{name}` is deprecated. "
        f"It is internal plumbing with no public replacement. "
        f"Will be removed in v1.0.0."
    )
    # The warning is attributed to the caller's frame (this test file), not to
    # `utils/__init__.py` or `_deprecation.py`. A wrong stacklevel on a
    # module-level PEP-562 `__getattr__` would otherwise ship undetected.
    assert record[0].filename == __file__


@pytest.mark.parametrize("name, impl", sorted(DEPRECATED.items()))
def test_from_import_of_deprecated_name_warns(name, impl):
    # `from protean.utils import <name>` routes through __getattr__ too.
    with pytest.warns(RemovedInProtean10Warning):
        namespace: dict[str, object] = {}
        exec(f"from protean.utils import {name}", namespace)
    assert namespace[name] is impl


@pytest.mark.parametrize("name", sorted(KEPT))
def test_kept_names_do_not_warn(name):
    # Kept names are live globals; accessing them never reaches __getattr__.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert getattr(utils, name) is not None


def test_unknown_attribute_raises_attribute_error():
    with pytest.raises(AttributeError):
        _ = utils.this_name_does_not_exist


def test_underscore_implementations_do_not_warn():
    # Framework code imports the underscore spelling directly, which resolves as
    # a normal global and must never emit a deprecation warning.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for impl in DEPRECATED.values():
            assert impl is not None
