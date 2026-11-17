"""A renamed element option raises ``ConfigurationError`` naming its replacement.

Aggregates, entities, projections and subscribers took ``provider`` and now
take ``database``. Repositories and database models took ``database`` and now
take ``database_type``.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.core.entity import BaseEntity
from protean.core.projection import BaseProjection
from protean.core.repository import BaseRepository
from protean.core.subscriber import BaseSubscriber
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, String


class Order(BaseAggregate):
    name = String()


class LineItem(BaseEntity):
    sku = String()


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)


class PaymentSubscriber(BaseSubscriber):
    def __call__(self, payload: dict) -> None:
        pass


class OrderRepository(BaseRepository):
    pass


class OrderModel(BaseDatabaseModel):
    pass


@pytest.mark.parametrize(
    "element_cls, opts",
    [
        (Order, {}),
        (LineItem, {"part_of": Order}),
        (OrderSummary, {}),
        (PaymentSubscriber, {"stream": "payments"}),
    ],
    ids=["aggregate", "entity", "projection", "subscriber"],
)
def test_provider_option_names_database(test_domain, element_cls, opts):
    with pytest.raises(ConfigurationError) as exc:
        test_domain.register(element_cls, provider="default", **opts)

    assert exc.value.args[0] == "Renamed option(s): `provider` is now `database`"


@pytest.mark.parametrize(
    "element_cls",
    [OrderRepository, OrderModel],
    ids=["repository", "database_model"],
)
def test_database_option_names_database_type(test_domain, element_cls):
    test_domain.register(Order)

    with pytest.raises(ConfigurationError) as exc:
        test_domain.register(element_cls, part_of=Order, database="postgresql")

    assert exc.value.args[0] == "Renamed option(s): `database` is now `database_type`"


def test_decorator_rejects_the_provider_option(test_domain):
    with pytest.raises(ConfigurationError) as exc:

        @test_domain.aggregate(provider="default")
        class Invoice:
            number = String()

    assert exc.value.args[0] == "Renamed option(s): `provider` is now `database`"


def test_database_option_registers_on_an_aggregate(test_domain):
    @test_domain.aggregate(database="reporting")
    class Invoice:
        number = String()

    assert Invoice.meta_.database == "reporting"


def test_database_type_option_registers_on_a_repository(test_domain):
    @test_domain.aggregate
    class Invoice:
        number = String()

    @test_domain.repository(part_of=Invoice, database_type="memory")
    class InvoiceRepository:
        pass

    assert InvoiceRepository.meta_.database_type == "memory"


def test_an_unrelated_unknown_option_keeps_the_generic_error(test_domain):
    with pytest.raises(ConfigurationError) as exc:
        test_domain.register(Order, colour="red")

    assert exc.value.args[0] == "Unknown option(s) {'colour'}"
