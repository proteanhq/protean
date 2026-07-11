"""Tests for event deprecation completion.

Covers the `superseded_by` event option and the raise-time
`DeprecationWarning` emitted through `raise_()` — which must fire **exactly
once per event type** (not per instance), name the successor when one is set,
and stay silent for non-deprecated events.
"""

import warnings

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.exceptions import ConfigurationError, ProteanDeprecationWarning
from protean.fields import Identifier, String


def _capture(order, *events):
    """Raise the given events and return the Protean deprecation warnings.

    Uses ``simplefilter("always")`` so Python's own per-location dedup can NOT
    mask a double emission — any dedup we observe is the framework's own
    once-per-type tracking, which is what these tests assert.
    """
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        for event in events:
            order.raise_(event)
    return [w for w in record if issubclass(w.category, ProteanDeprecationWarning)]


class TestDeprecatedEventRaiseWarning:
    def test_raising_a_deprecated_event_warns(self, test_domain):
        class Order(BaseAggregate):
            name = String()

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.register(
            OrderPlaced,
            part_of=Order,
            deprecated={"since": "0.15", "removal": "0.18.0"},
        )
        test_domain.init(traverse=False)

        order = Order(name="foo")
        warns = _capture(order, OrderPlaced(order_id="1"))

        assert len(warns) == 1
        message = str(warns[0].message)
        assert "OrderPlaced" in message
        assert "0.18.0" in message

    def test_deprecated_event_warns_once_per_type_not_per_instance(self, test_domain):
        """Three raises of the same deprecated event emit a single warning,
        even under ``simplefilter("always")`` — the dedup is the framework's,
        not Python's warning filter."""

        class Order(BaseAggregate):
            name = String()

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order, deprecated={"since": "0.15"})
        test_domain.init(traverse=False)

        order = Order(name="foo")
        warns = _capture(
            order,
            OrderPlaced(order_id="1"),
            OrderPlaced(order_id="2"),
            OrderPlaced(order_id="3"),
        )

        assert len(warns) == 1

    def test_non_deprecated_event_does_not_warn(self, test_domain):
        """Negative path: a non-deprecated event raises no deprecation
        warning, however many times it is raised."""

        class Order(BaseAggregate):
            name = String()

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        order = Order(name="foo")
        warns = _capture(order, OrderPlaced(order_id="1"), OrderPlaced(order_id="2"))

        assert warns == []

    def test_warning_names_successor_when_superseded_by_is_a_class(self, test_domain):
        class Order(BaseAggregate):
            name = String()

        class OrderConfirmed(BaseEvent):
            order_id = Identifier(identifier=True)

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.register(OrderConfirmed, part_of=Order)
        test_domain.register(
            OrderPlaced,
            part_of=Order,
            deprecated={"since": "0.15", "removal": "0.18.0"},
            superseded_by=OrderConfirmed,
        )
        test_domain.init(traverse=False)

        order = Order(name="foo")
        warns = _capture(order, OrderPlaced(order_id="1"))

        assert len(warns) == 1
        assert "Use `OrderConfirmed` instead." in str(warns[0].message)

    def test_warning_names_successor_when_superseded_by_is_a_string(self, test_domain):
        class Order(BaseAggregate):
            name = String()

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.register(
            OrderPlaced,
            part_of=Order,
            deprecated={"since": "0.15"},
            superseded_by="OrderConfirmed",
        )
        test_domain.init(traverse=False)

        order = Order(name="foo")
        warns = _capture(order, OrderPlaced(order_id="1"))

        assert len(warns) == 1
        assert "Use `OrderConfirmed` instead." in str(warns[0].message)

    def test_warning_without_removal_omits_removal_clause(self, test_domain):
        class Order(BaseAggregate):
            name = String()

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order, deprecated={"since": "0.15"})
        test_domain.init(traverse=False)

        order = Order(name="foo")
        warns = _capture(order, OrderPlaced(order_id="1"))

        assert len(warns) == 1
        assert "Will be removed" not in str(warns[0].message)

    def test_event_sourced_replay_does_not_warn(self, test_domain):
        """Negative scope: reconstructing an aggregate from stored events via
        `from_events` (the replay path, which runs `_apply`, not `raise_`) must
        NOT warn — otherwise loading history would emit a deprecation warning
        for every stored deprecated event."""

        class MoneyDeposited(BaseEvent):
            account_id = Identifier(identifier=True)
            amount = String()

        class Account(BaseAggregate):
            account_id = Identifier(identifier=True)
            balance = String()

            @apply
            def on_deposit(self, event: MoneyDeposited):
                self.balance = event.amount

        test_domain.register(Account, is_event_sourced=True)
        test_domain.register(
            MoneyDeposited,
            part_of=Account,
            deprecated={"since": "0.15", "removal": "0.18.0"},
        )
        test_domain.init(traverse=False)

        account = Account(account_id="a1", balance="0")
        with warnings.catch_warnings():  # the setup raise legitimately warns
            warnings.simplefilter("ignore")
            account.raise_(MoneyDeposited(account_id="a1", amount="100"))
        stored = list(account._events)
        assert len(stored) == 1

        with warnings.catch_warnings(record=True) as record:
            warnings.simplefilter("always")
            replayed = Account.from_events(stored)
        deps = [w for w in record if issubclass(w.category, ProteanDeprecationWarning)]

        assert deps == []
        assert replayed.balance == "100"

    def test_string_shorthand_deprecated_is_normalized_not_crashed(self, test_domain):
        """The `deprecated="0.15"` shorthand is normalized to a dict at
        registration, so the raise-time warning reads it safely instead of
        calling `.get()` on a bare string."""

        class Order(BaseAggregate):
            name = String()

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order, deprecated="0.15")
        test_domain.init(traverse=False)

        assert OrderPlaced.meta_.deprecated == {"since": "0.15"}

        order = Order(name="foo")
        warns = _capture(order, OrderPlaced(order_id="1"))

        assert len(warns) == 1
        assert "OrderPlaced" in str(warns[0].message)


class TestSupersededByOption:
    def test_superseded_by_defaults_to_none(self, test_domain):
        class Order(BaseAggregate):
            name = String()

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        assert OrderPlaced.meta_.superseded_by is None

    def test_superseded_by_is_stored_on_meta(self, test_domain):
        class Order(BaseAggregate):
            name = String()

        class OrderConfirmed(BaseEvent):
            order_id = Identifier(identifier=True)

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.register(OrderConfirmed, part_of=Order)
        test_domain.register(OrderPlaced, part_of=Order, superseded_by=OrderConfirmed)
        test_domain.init(traverse=False)

        assert OrderPlaced.meta_.superseded_by is OrderConfirmed

    def test_superseded_by_rejects_non_class_non_string(self, test_domain):
        """A `superseded_by` that is neither an Event class nor a name string
        is rejected at registration, so a non-serializable value cannot reach
        IR serialization or warning text."""

        class Order(BaseAggregate):
            name = String()

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        with pytest.raises(
            ConfigurationError,
            match="`superseded_by` must be an Event class or a name string",
        ):
            test_domain.register(
                OrderPlaced, part_of=Order, superseded_by={"not": "valid"}
            )
