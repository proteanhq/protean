"""Check what docs/reference/troubleshooting.md says about common problems.

``001.py`` defines the ``Sales`` domain the page uses: an ``Order`` aggregate
that raises ``OrderPlaced``, a ``PlaceOrder`` command and its handler, an event
handler, an ``OrderSummary`` projection with its projector, and a subscriber.
It sets command and event processing to ``"sync"``. ``002.py`` is the pytest
fixture that opens a domain context. ``003.py`` is the FastAPI app. Each test
loads its example fresh, so every test gets its own domain and memory stores.
"""

import pytest
from fastapi.testclient import TestClient

from protean import Domain, current_domain, handle
from protean.domain.context import has_domain_context
from protean.exceptions import ValidationError
from protean.fields import Identifier, String
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def sales():
    module = load_example("reference/troubleshooting/001.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


def place_order(module, customer_id="cust-1", **kwargs):
    module.domain.process(module.PlaceOrder(customer_id=customer_id), **kwargs)
    (order,) = module.domain.repository_for(module.Order).query.all().items
    return order


class TestCommandIsAcceptedButNothingHappens:
    def test_the_check_finds_the_registered_handler(self, sales, capsys):
        assert sales.registered_handler() is sales.OrderCommandHandler
        assert "OrderCommandHandler" in capsys.readouterr().out

    def test_the_check_returns_none_when_no_handler_is_registered(self):
        domain = Domain(name="NoHandler")

        @domain.aggregate
        class Order:
            customer_id: String(required=True)

        @domain.command(part_of=Order)
        class PlaceOrder:
            customer_id: String(required=True)

        domain.init(traverse=False)
        with domain.domain_context():
            assert domain.command_handler_for(PlaceOrder(customer_id="c")) is None

    def test_the_handler_persists_the_order_it_creates(self, sales):
        order = place_order(sales, customer_id="cust-7")

        assert order.customer_id == "cust-7"
        assert order.status == "placed"

    def test_a_handler_that_never_calls_add_persists_nothing(self):
        domain = Domain(name="NoAdd")
        domain.config["command_processing"] = "sync"

        @domain.aggregate
        class Order:
            customer_id: String(required=True)

        @domain.command(part_of=Order)
        class PlaceOrder:
            customer_id: String(required=True)

        @domain.command_handler(part_of=Order)
        class OrderCommandHandler:
            @handle(PlaceOrder)
            def place_order(self, command: PlaceOrder):
                Order(customer_id=command.customer_id)

        domain.init(traverse=False)
        with domain.domain_context():
            domain.process(PlaceOrder(customer_id="cust-1"))
            assert domain.repository_for(Order).query.all().items == []

    def test_processing_is_async_by_default_and_the_example_makes_it_sync(
        self, sales, tmp_path
    ):
        # A root path with no domain.toml, so the repo's test config is not read.
        default = Domain(root_path=str(tmp_path), name="Default")
        assert default.config["command_processing"] == "async"
        assert default.config["event_processing"] == "async"

        assert sales.domain.config["command_processing"] == "sync"
        assert sales.domain.config["event_processing"] == "sync"


class TestEventHandlerDoesNotFire:
    def test_place_raises_order_placed_with_the_order_id(self, sales):
        order = sales.Order(customer_id="cust-1")
        order.place()

        (event,) = order._events
        assert isinstance(event, sales.OrderPlaced)
        assert event.order_id == order.id

    def test_creating_the_event_without_raising_it_records_nothing(self, sales):
        order = sales.Order(customer_id="cust-1")
        sales.OrderPlaced(order_id=order.id)

        assert order._events == []

    def test_the_handler_part_of_order_receives_order_events(self, sales):
        order = sales.Order(customer_id="cust-1")
        order.place()

        handlers = sales.domain.handlers_for(order._events[0])
        assert sales.OrderEventHandler in handlers

    def test_a_handler_part_of_another_aggregate_does_not_receive_them(self):
        domain = Domain(name="WrongPartOf")

        @domain.aggregate
        class Order:
            def place(self):
                self.raise_(OrderPlaced(order_id=self.id))

        @domain.aggregate
        class Customer:
            name: String()

        @domain.event(part_of=Order)
        class OrderPlaced:
            order_id: Identifier(required=True)

        @domain.event_handler(part_of=Customer)
        class OrderEventHandler:
            @handle(OrderPlaced)
            def on_placed(self, event: OrderPlaced): ...

        domain.init(traverse=False)
        with domain.domain_context():
            order = Order()
            order.place()
            assert OrderEventHandler not in domain.handlers_for(order._events[0])

    def test_the_engine_in_test_mode_processes_queued_messages(self):
        module = load_example("reference/troubleshooting/001.py")
        module.domain.config["command_processing"] = "async"
        module.domain.config["event_processing"] = "async"
        module.domain.init(traverse=False)

        with module.domain.domain_context():
            module.domain.process(module.PlaceOrder(customer_id="cust-1"))
            orders = module.domain.repository_for(module.Order)
            assert orders.query.all().items == []

            module.process_pending_messages()

            (order,) = orders.query.all().items
            assert order.status == "placed"
            summary = module.domain.repository_for(module.OrderSummary).get(order.id)
            assert summary.status == "placed"


class TestNoDomainContext:
    def test_current_domain_outside_a_context_warns_then_fails(self):
        module = load_example("reference/troubleshooting/001.py")
        module.domain.init(traverse=False)

        with pytest.warns(UserWarning, match="Working outside of domain context"):
            with pytest.raises(AttributeError, match="repository_for"):
                current_domain.repository_for(module.Order)

    def test_creating_an_aggregate_outside_a_context_fails_on_config(self):
        module = load_example("reference/troubleshooting/001.py")
        module.domain.init(traverse=False)

        with pytest.warns(UserWarning, match="Working outside of domain context"):
            with pytest.raises(AttributeError, match="config"):
                module.Order(customer_id="cust-1")

    def test_the_script_fix_reads_orders_inside_its_own_context(self):
        module = load_example("reference/troubleshooting/001.py")
        module.domain.init(traverse=False)
        with module.domain.domain_context():
            module.domain.process(module.PlaceOrder(customer_id="cust-3"))

        assert not has_domain_context()
        (order,) = module.all_orders().items
        assert order.customer_id == "cust-3"

    def test_the_fixture_opens_a_context_for_the_test_and_closes_it(self):
        fixture = load_example("reference/troubleshooting/002.py")
        domain = Domain(name="Tests")

        steps = fixture.domain_context.__wrapped__(domain)
        next(steps)
        assert current_domain.name == "Tests"

        steps.close()
        assert not has_domain_context()

    @pytest.mark.fastapi
    def test_the_middleware_gives_each_request_a_domain_context(self):
        module = load_example("reference/troubleshooting/003.py")
        module.domain.init(traverse=False)

        response = TestClient(module.app).post(
            "/orders", json={"customer_id": "cust-9"}
        )

        assert response.status_code == 200
        with module.domain.domain_context():
            (order,) = module.domain.repository_for(module.Order).query.all().items
        assert order.customer_id == "cust-9"


class TestProjectionIsEmptyOrStale:
    def test_the_projector_writes_a_summary_for_each_placed_order(self, sales):
        order = place_order(sales)

        summary = sales.domain.repository_for(sales.OrderSummary).get(order.id)
        assert summary.status == "placed"

    def test_setting_up_the_database_leaves_the_domain_usable(self, sales):
        sales.create_tables()

        assert place_order(sales).status == "placed"


class TestSubscriberDoesNotReceiveMessages:
    def test_the_subscriber_listens_on_the_stream_it_names(self, sales):
        broker = sales.domain.brokers["default"]

        assert broker._subscribers["external_orders"] == {sales.OrderSubscriber}
        assert broker._subscribers["external-orders"] == set()


class TestAggregateValidationErrors:
    def test_messages_map_each_field_to_its_errors(self, sales, capsys):
        sales.show_validation_errors()

        assert capsys.readouterr().out.strip() == str(
            {
                "customer_id": ["String should have at least 1 character"],
                "total": ["Input should be greater than or equal to 0"],
            }
        )

    def test_messages_is_a_plain_string_when_raised_with_one(self):
        with pytest.raises(ValidationError) as exc:
            raise ValidationError("Order is already shipped")

        assert exc.value.messages == "Order is already shipped"

    def test_messages_is_a_list_when_raised_with_one(self):
        with pytest.raises(ValidationError) as exc:
            raise ValidationError(["Order is already shipped"])

        assert exc.value.messages == ["Order is already shipped"]


class TestMessageTracing:
    def test_the_causation_tree_starts_at_the_command(self, sales):
        place_order(sales, correlation_id="req-1")

        tree = sales.causation_tree("req-1")

        assert tree.message_type == "Sales.PlaceOrder.v1"
        assert [child.message_type for child in tree.children] == [
            "Sales.OrderPlaced.v1"
        ]

    @pytest.mark.fastapi
    def test_the_endpoint_threads_the_request_id_through_the_chain(self):
        module = load_example("reference/troubleshooting/003.py")
        module.domain.init(traverse=False)

        response = TestClient(module.app).post(
            "/orders",
            json={"customer_id": "cust-1"},
            headers={"X-Request-Id": "req-42"},
        )

        assert response.status_code == 200
        with module.domain.domain_context():
            tree = module.domain.event_store.store.build_causation_tree("req-42")
        assert tree.message_type == "Sales.PlaceOrder.v1"
        assert [child.message_type for child in tree.children] == [
            "Sales.OrderPlaced.v1"
        ]
