"""Tests for process manager instances: construction, starting state, equality,
hashing and text forms."""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.process_manager import BaseProcessManager
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Dict, Identifier, List, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle

from .elements import (
    Order,
    OrderFulfillmentPM,
    OrderPlaced,
    Payment,
    PaymentConfirmed,
    PaymentFailed,
    ShipmentDelivered,
    Shipping,
)


class Ticket(BaseAggregate):
    title: String()

    @classmethod
    def open(cls, title: str) -> "Ticket":
        ticket = cls(title=title)
        ticket.raise_(TicketOpened(ticket_id=str(ticket.id)))
        return ticket


class TicketOpened(BaseEvent):
    ticket_id: Identifier()


class TicketPM(BaseProcessManager):
    """Has an explicit identifier field and does not set it in its handler."""

    ticket_id: Identifier(identifier=True)
    tags: List(content_type=String, default=list)
    notes: Dict(default=dict)
    status: String(default="new")
    priority: String(default="normal")

    @handle(TicketOpened, start=True, correlate="ticket_id")
    def on_ticket_opened(self, event: TicketOpened) -> None:
        self.status = "open"


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(Payment)
    test_domain.register(PaymentConfirmed, part_of=Payment)
    test_domain.register(PaymentFailed, part_of=Payment)
    test_domain.register(Shipping)
    test_domain.register(ShipmentDelivered, part_of=Shipping)
    test_domain.register(
        OrderFulfillmentPM,
        stream_categories=["test::order", "test::payment", "test::shipping"],
    )
    test_domain.register(Ticket)
    test_domain.register(TicketOpened, part_of=Ticket)
    test_domain.register(TicketPM, stream_categories=["test::ticket"])
    test_domain.init(traverse=False)


def _first_transition_state(test_domain, pm_cls, correlation_value):
    stream_name = f"{pm_cls.meta_.stream_category}-{correlation_value}"
    messages = test_domain.event_store.store.read(stream_name)
    return messages[0].to_domain_object().state


class TestConstruction:
    def test_template_dict_and_keyword_arguments_are_merged(self):
        """A dict passed positionally supplies values; keyword arguments add to it."""
        pm = OrderFulfillmentPM(
            {"order_id": "ORD-1", "status": "test"},
            payment_id="PAY-1",
        )

        assert pm.to_dict() == {
            "order_id": "ORD-1",
            "payment_id": "PAY-1",
            "status": "test",
        }

    def test_non_dict_positional_argument_is_rejected(self):
        """A positional argument that is not a dict raises TypeError."""
        with pytest.raises(TypeError) as exc:
            OrderFulfillmentPM("not-a-dict")

        assert str(exc.value) == (
            "Positional argument not-a-dict passed must be a dict. "
            "This argument serves as a template for loading common values."
        )


class TestStartingState:
    def test_new_instance_starts_with_field_defaults(self, test_domain):
        """A started PM records the defaults of fields its handler did not set."""
        ticket = Ticket.open(title="Printer jam")
        with UnitOfWork():
            current_domain.repository_for(Ticket).add(ticket)

        state = _first_transition_state(test_domain, TicketPM, ticket.id)

        assert state["tags"] == []
        assert state["notes"] == {}
        assert state["priority"] == "normal"

    def test_identifier_field_is_set_to_the_correlation_value(self, test_domain):
        """A started PM's identifier field holds the correlation value."""
        ticket = Ticket.open(title="Printer jam")
        with UnitOfWork():
            current_domain.repository_for(Ticket).add(ticket)

        state = _first_transition_state(test_domain, TicketPM, ticket.id)

        assert state["ticket_id"] == str(ticket.id)


class TestToDict:
    def test_to_dict_returns_every_field_value(self):
        """to_dict() returns each declared field, including unset ones as None."""
        pm = OrderFulfillmentPM(order_id="ORD-1", status="awaiting_payment")

        assert pm.to_dict() == {
            "order_id": "ORD-1",
            "payment_id": None,
            "status": "awaiting_payment",
        }


class TestEquality:
    def test_pms_with_the_same_identifier_are_equal(self):
        """Two PMs of one class with the same identifier value are equal."""
        assert TicketPM(ticket_id="T-1") == TicketPM(ticket_id="T-1", status="open")

    def test_pms_with_different_identifiers_are_not_equal(self):
        """Two PMs of one class with different identifier values are not equal."""
        assert TicketPM(ticket_id="T-1") != TicketPM(ticket_id="T-2")

    def test_pms_without_an_identifier_field_are_never_equal(self):
        """Without an identifier field, two PMs with the same data are not equal."""
        order_id = str(uuid4())

        assert OrderFulfillmentPM(order_id=order_id) != OrderFulfillmentPM(
            order_id=order_id
        )

    def test_pm_is_not_equal_to_an_object_of_another_type(self):
        """A PM is not equal to a value of a different type."""
        assert TicketPM(ticket_id="T-1") != "T-1"


class TestHash:
    def test_a_pm_hashes_as_its_identifier_value(self):
        """A PM with an identifier field has the hash of its identifier value."""
        assert hash(TicketPM(ticket_id="T-1", status="open")) == hash("T-1")

    def test_pms_with_the_same_identifier_collapse_in_a_set(self):
        """PMs hash by identifier, so a set keeps one PM per identifier value."""
        pms = {
            TicketPM(ticket_id="T-1"),
            TicketPM(ticket_id="T-2"),
            TicketPM(ticket_id="T-1"),
        }

        assert pms == {TicketPM(ticket_id="T-1"), TicketPM(ticket_id="T-2")}

    def test_pms_without_an_identifier_field_stay_distinct_in_a_set(self):
        """Without an identifier field, each PM instance is a separate set member."""
        pms = {
            OrderFulfillmentPM(order_id="ORD-1"),
            OrderFulfillmentPM(order_id="ORD-1"),
        }

        assert len(pms) == 2


class TestTextForms:
    def test_str_names_the_class_and_lists_the_field_values(self):
        """str() shows the class name and the to_dict() values."""
        pm = OrderFulfillmentPM(order_id="ORD-1")

        assert str(pm) == (
            "OrderFulfillmentPM object "
            "({'order_id': 'ORD-1', 'payment_id': None, 'status': 'new'})"
        )

    def test_repr_wraps_str_in_angle_brackets(self):
        """repr() is the class name and str() inside angle brackets."""
        pm = OrderFulfillmentPM(order_id="ORD-1")

        assert repr(pm) == (
            "<OrderFulfillmentPM: OrderFulfillmentPM object "
            "({'order_id': 'ORD-1', 'payment_id': None, 'status': 'new'})>"
        )
