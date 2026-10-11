"""Check the examples on docs/community/contributing/testing.md.

``001.py`` is a test that uses the ``test_domain`` fixture from
``tests/conftest.py``. The page says that fixture gives each test a fresh
domain named ``Test`` with test configuration, so the example test is called
here with the real fixture. ``002.py`` holds the ``place_order`` section the
page uses to show how a page includes code from ``docs_src``.
"""

import pytest

from protean import Domain
from protean.exceptions import ValidationError
from protean.utils.reflection import declared_fields
from tests.docs.support import load_example


@pytest.fixture
def fixture_example():
    return load_example("community/contributing/testing/001.py")


def test_example_test_passes_with_the_test_domain_fixture(fixture_example, test_domain):
    fixture_example.test_domain_initialization(test_domain)


@pytest.mark.no_test_domain
def test_example_test_fails_with_another_domain(fixture_example):
    with pytest.raises(AssertionError):
        fixture_example.test_domain_initialization(Domain(name="Other"))


@pytest.fixture
def place_order_example():
    module = load_example("community/contributing/testing/002.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


@pytest.mark.no_test_domain
def test_place_order_targets_the_order_aggregate(place_order_example):
    assert place_order_example.PlaceOrder.meta_.part_of is place_order_example.Order


@pytest.mark.no_test_domain
def test_place_order_requires_an_order_id(place_order_example):
    with pytest.raises(ValidationError, match="order_id.*is required"):
        place_order_example.PlaceOrder()

    assert place_order_example.PlaceOrder(order_id="o-1").order_id == "o-1"


@pytest.mark.no_test_domain
def test_order_declares_a_status_field(place_order_example):
    assert set(declared_fields(place_order_example.Order)) == {"id", "status"}
