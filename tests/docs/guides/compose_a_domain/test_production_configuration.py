"""The example on the production configuration guide behaves as the page says."""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_aggregate_is_stored_through_the_named_database():
    example = load_example("guides/compose-a-domain/production-configuration/001.py")
    example.domain.init(traverse=False)

    assert example.ProductSearch.meta_.provider == "analytics"

    with example.domain.domain_context():
        repo = example.domain.repository_for(example.ProductSearch)
        assert repo._provider is example.domain.providers["analytics"]

        product = example.ProductSearch()
        repo.add(product)
        assert repo.get(product.id).id == product.id
