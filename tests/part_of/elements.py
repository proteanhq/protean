"""Builders for the ``part_of`` kind tests.

Each builder returns a fresh class, so one test's registration options never
leak into another test through a shared module-level class.
"""

from protean.core.aggregate import BaseAggregate
from protean.core.application_service import BaseApplicationService
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.database_model import BaseDatabaseModel
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.event_sourced_repository import BaseEventSourcedRepository
from protean.core.process_manager import BaseProcessManager
from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.core.repository import BaseRepository
from protean.core.value_object import BaseValueObject
from protean.fields import Identifier, String
from protean.utils.mixins import handle


def order_aggregate():
    class Order(BaseAggregate):
        name: String()

    return Order


def account_es_aggregate():
    class Account(BaseAggregate):
        name: String()

    return Account


def line_item_entity():
    class LineItem(BaseEntity):
        sku: String()

    return LineItem


def money_value_object():
    class Money(BaseValueObject):
        amount: String()

    return Money


def order_summary_projection():
    class OrderSummary(BaseProjection):
        order_id: Identifier(identifier=True)
        name: String()

    return OrderSummary


def order_shipped_event():
    class OrderShipped(BaseEvent):
        order_id: Identifier()

    return OrderShipped


def fulfillment_process_manager(started_by):
    class Fulfillment(BaseProcessManager):
        order_id: Identifier()

        @handle(started_by, start=True, correlate="order_id")
        def on_shipped(self, event):
            pass

    return Fulfillment


def value_object():
    class Price(BaseValueObject):
        amount: String()

    return Price


def application_service():
    class OrderService(BaseApplicationService):
        pass

    return OrderService


def repository():
    class OrderRepository(BaseRepository):
        pass

    return OrderRepository


def event_sourced_repository():
    class AccountRepository(BaseEventSourcedRepository):
        pass

    return AccountRepository


def command_handler():
    class OrderCommandHandler(BaseCommandHandler):
        pass

    return OrderCommandHandler


def event_handler():
    class OrderEventHandler(BaseEventHandler):
        pass

    return OrderEventHandler


def entity():
    class Note(BaseEntity):
        text: String()

    return Note


def event():
    class OrderPlaced(BaseEvent):
        order_id: Identifier()

    return OrderPlaced


def command():
    class PlaceOrder(BaseCommand):
        order_id: Identifier()

    return PlaceOrder


def database_model():
    class OrderModel(BaseDatabaseModel):
        @classmethod
        def from_entity(cls, entity):
            return {}

    return OrderModel


def query():
    class GetOrder(BaseQuery):
        order_id: Identifier()

    return GetOrder


def query_handler():
    class OrderQueryHandler(BaseQueryHandler):
        pass

    return OrderQueryHandler
