"""The example on the Choosing Adapters guide behaves as the page says."""

import pytest

from protean.utils.reflection import id_field
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_projection_is_routed_to_the_named_search_database():
    example = load_example("guides/compose-a-domain/choosing-adapters/001.py")
    example.domain.init(traverse=False)

    assert example.ProductSearchIndex.meta_.provider == "search"
    assert id_field(example.ProductSearchIndex).field_name == "product_id"
    assert example.domain.registry.elements == {
        "projections": [example.ProductSearchIndex]
    }
