"""Projections take no ``database_model`` option.

A custom model is registered with ``@domain.database_model(part_of=<Projection>)``.
Passing ``database_model=`` to the projection itself raises ``ConfigurationError``.
"""

import pytest

from protean.core.projection import BaseProjection
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, String


def test_registering_a_projection_with_database_model_raises(test_domain):
    class ProductInventory(BaseProjection):
        product_id = Identifier(identifier=True)
        name = String()

    with pytest.raises(ConfigurationError) as exc:
        test_domain.register(ProductInventory, database_model="InventoryModel")

    assert "Unknown option" in str(exc.value)
    assert "database_model" in str(exc.value)


def test_decorating_a_projection_with_database_model_raises(test_domain):
    with pytest.raises(ConfigurationError) as exc:

        @test_domain.projection(database_model="InventoryModel")
        class ProductInventory:
            product_id = Identifier(identifier=True)
            name = String()

    assert "Unknown option" in str(exc.value)
    assert "database_model" in str(exc.value)


def test_a_projection_without_the_option_registers(test_domain):
    @test_domain.projection
    class ProductInventory:
        product_id = Identifier(identifier=True)
        name = String()

    assert "database_model" not in dict(ProductInventory.meta_)
