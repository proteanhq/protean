"""An event handler's ``stream_category`` names a category inside its own domain."""

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils.mixins import handle


class Order(BaseAggregate):
    name = String()


class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    client_id = Identifier()


class Return(BaseAggregate):
    reason = String()


class ReturnRequested(BaseEvent):
    return_id = Identifier(required=True)


received: list[str] = []


class ReportHandler(BaseEventHandler):
    @handle("$any")
    def record(self, event):
        received.append(event.return_id)


class OrderHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        pass


class ExternalSubscriber(BaseSubscriber):
    def __call__(self, payload: dict) -> None:
        pass


def test_a_bare_category_gets_the_domain_prefix(test_domain):
    test_domain.register(ReportHandler, stream_category="all_orders")

    assert ReportHandler.meta_.stream_category == "test::all_orders"


def test_all_stays_as_written(test_domain):
    test_domain.register(ReportHandler, stream_category="$all")

    assert ReportHandler.meta_.stream_category == "$all"


def test_a_qualified_category_stays_as_written(test_domain):
    test_domain.register(ReportHandler, stream_category="billing::invoice")

    assert ReportHandler.meta_.stream_category == "billing::invoice"


def test_a_category_derived_from_part_of_is_not_prefixed_twice(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderHandler, part_of=Order)

    assert OrderHandler.meta_.stream_category == "test::order"
    assert OrderHandler.meta_.stream_category == Order.meta_.stream_category


def test_a_handler_registered_before_its_aggregate_gets_the_same_category(
    test_domain,
):
    test_domain.register(OrderHandler, part_of=Order)
    test_domain.register(Order)

    assert OrderHandler.meta_.stream_category == "test::order"
    assert Order.meta_.stream_category == "test::order"


def test_a_string_part_of_resolves_to_the_prefixed_aggregate_category(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(OrderHandler, part_of="Order")
    test_domain.init(traverse=False)

    assert OrderHandler.meta_.part_of is Order
    assert OrderHandler.meta_.stream_category == "test::order"


def test_a_subscriber_stream_is_not_prefixed(test_domain):
    test_domain.register(ExternalSubscriber, stream="payments")

    assert ExternalSubscriber.meta_.stream == "payments"


def test_a_bare_category_reads_the_aggregate_with_that_category(test_domain):
    received.clear()
    test_domain.config["event_processing"] = "async"
    test_domain.register(Return, stream_category="all_orders")
    test_domain.register(ReturnRequested, part_of=Return)
    test_domain.register(ReportHandler, stream_category="all_orders")
    test_domain.init(traverse=False)

    returned = Return(reason="damaged")
    returned.raise_(ReturnRequested(return_id=returned.id))
    test_domain.repository_for(Return).add(returned)

    Engine(domain=test_domain, test_mode=True).run()

    assert received == [returned.id]


def test_an_explicit_category_matches_the_partition_key_of_its_events(test_domain):
    """The subscription factory looks up the handler's category in the partition
    key map, which is keyed by the category the events are written to."""
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(
        OrderHandler, stream_category="order", sequential_by="client_id"
    )
    test_domain.init(traverse=False)

    assert test_domain._partition_keys == {"test::order": "client_id"}
    assert OrderHandler.meta_.stream_category in test_domain._partition_keys
