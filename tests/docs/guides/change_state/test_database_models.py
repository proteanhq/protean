"""Check what docs/guides/change-state/database-models.md says about models.

The page's runnable example registers an empty custom model for `Product`
that only changes the schema name to `products`, and a second model used only
on PostgreSQL.
"""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example():
    module = load_example("guides/change-state/database-models/001.py")
    module.domain.init(traverse=False)
    return module


def product_models(example):
    return {
        record.cls.__name__: record.cls
        for record in example.domain.registry.database_models.values()
        if record.cls.meta_.part_of is example.Product
    }


def test_registered_model_overrides_the_schema_name(example):
    model = product_models(example)["ProductModel"]

    assert model.meta_.schema_name == "products"
    assert model.derive_schema_name() == "products"
    assert model.meta_.database is None


def test_reporting_model_is_registered_for_postgresql_only(example):
    assert sorted(product_models(example)) == ["ProductModel", "ProductReportingModel"]
    model = product_models(example)["ProductReportingModel"]

    assert model.meta_.schema_name == "product_reports"
    assert model.meta_.database == "postgresql"


def test_memory_database_uses_the_model_without_a_database_type(example):
    with example.domain.domain_context():
        repo = example.domain.repository_for(example.Product)

        assert issubclass(repo._dao.database_model_cls, example.ProductModel)


def test_custom_model_round_trips_a_product(example):
    with example.domain.domain_context():
        repo = example.domain.repository_for(example.Product)
        model_cls = repo._dao.database_model_cls
        product = example.Product(name="Pen", description="A blue pen", price=1.5)

        row = model_cls.from_entity(product)
        restored = model_cls.to_entity(row)

        assert issubclass(model_cls, example.ProductModel)
        assert restored == product
        assert (restored.name, restored.description, restored.price) == (
            "Pen",
            "A blue pen",
            1.5,
        )
