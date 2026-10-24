"""A database model that names its aggregate by string stores through SQLite."""

import pytest
from sqlalchemy import inspect

from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.domain import Domain
from protean.fields import String


@pytest.mark.sqlite
def test_an_aggregate_round_trips_through_a_string_part_of_model():
    domain = Domain(
        name="StringPartOfModel",
        config={
            "databases": {
                "default": {"provider": "sqlite", "database_uri": "sqlite:///:memory:"}
            }
        },
    )

    @domain.database_model(part_of="Order", schema_name="custom_orders")
    class OrderModel(BaseDatabaseModel):
        pass

    @domain.aggregate
    class Order(BaseAggregate):
        name: String(max_length=50)

    domain.init(traverse=False)

    with domain.domain_context():
        repo = domain.repository_for(Order)
        provider = domain.providers["default"]
        dao = repo._dao
        provider._metadata.create_all(provider._engine)

        saved = Order(name="Widget")
        repo.add(saved)
        loaded = repo.get(saved.id)
        tables = inspect(provider._engine).get_table_names()

    assert OrderModel.meta_.part_of is Order
    assert dao.database_model_cls.__tablename__ == "custom_orders"
    assert "custom_orders" in tables
    assert loaded.id == saved.id
    assert loaded.name == "Widget"
