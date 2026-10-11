"""Check what docs/reference/compatibility/index.md says about deprecation.

``001.py`` is the Tier 1 pattern: ``old_method()`` warns with a removal
version and delegates to ``new_method()``. ``002.py`` deprecates the
``OrderPlaced`` event with ``superseded_by=OrderPlacedV2``. The page says
raising it emits a ``ProteanDeprecationWarning`` once per event type that names
the successor, and that the ``DEPRECATED_ELEMENT`` diagnostic appends
``superseded by`` and the successor.
"""

import warnings

import pytest

from protean._deprecation import ProteanDeprecationWarning
from tests.docs.support import load_example, module_name_for

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def old_method_example():
    return load_example("reference/compatibility/001.py")


@pytest.fixture
def superseded_example():
    module = load_example("reference/compatibility/002.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


def test_old_method_warns_with_the_removal_version(old_method_example):
    class Client:
        old_method = old_method_example.old_method

        def new_method(self):
            return "new result"

    with pytest.warns(DeprecationWarning) as record:
        result = Client().old_method()

    assert result == "new result"
    assert str(record[0].message) == (
        "old_method() is deprecated. Use new_method() instead. "
        "Will be removed in v0.17.0."
    )
    # stacklevel=2 points the warning at the caller, not at old_method itself.
    assert record[0].filename == __file__


def test_raising_the_deprecated_event_warns_once_naming_the_successor(
    superseded_example,
):
    order = superseded_example.Order(customer_id="c-1")

    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        order.raise_(superseded_example.OrderPlaced())
        order.raise_(superseded_example.OrderPlaced())

    deprecations = [
        w for w in record if issubclass(w.category, ProteanDeprecationWarning)
    ]
    assert [str(w.message) for w in deprecations] == [
        (
            "Event `OrderPlaced` is deprecated. Use `OrderPlacedV2` instead. "
            "Will be removed in v0.19."
        )
    ]


def test_deprecated_element_diagnostic_names_the_successor(superseded_example):
    module = module_name_for("reference/compatibility/002.py")
    diagnostics = [
        d
        for d in superseded_example.domain.to_ir()["diagnostics"]
        if d["code"] == "DEPRECATED_ELEMENT"
    ]

    assert [d["message"] for d in diagnostics] == [
        (
            "`OrderPlaced` is deprecated since v0.16, scheduled for removal in v0.19; "
            f"superseded by `{module}.OrderPlacedV2`"
        )
    ]
