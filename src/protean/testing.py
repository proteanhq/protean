"""Event-sourcing test DSL for Protean.

Provides a fluent, Pythonic DSL for testing event-sourced aggregates
through integration tests that exercise the full command processing
pipeline: command → handler → aggregate → events.

The three words::

    given(Order, order_created, order_confirmed).process(initiate_payment)

"Given an Order after order_created and order_confirmed, process initiate_payment."

After ``.process()``, assert with plain Python::

    assert order.accepted
    assert PaymentPending in order.events
    assert order.events[PaymentPending].payment_id == "pay-001"
    assert order.status == "Payment_Pending"

Multi-command chaining::

    order = (
        given(Order)
        .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
        .process(ConfirmOrder(order_id=oid))
        .process(InitiatePayment(order_id=oid, payment_id="pay-001"))
    )

    assert order.accepted
    assert order.status == "Payment_Pending"

Usage::

    from protean.testing import given

    def test_payment_on_confirmed_order(order_created, order_confirmed, initiate_payment):
        order = given(Order, order_created, order_confirmed).process(initiate_payment)

        assert order.accepted
        assert PaymentPending in order.events
        assert order.events[PaymentPending].payment_id == "pay-001"
        assert order.status == "Payment_Pending"

    def test_cannot_pay_unconfirmed_order(order_created, initiate_payment):
        order = given(Order, order_created).process(initiate_payment)

        assert order.rejected
        assert isinstance(order.rejection, ValidationError)
        assert len(order.events) == 0

    def test_create_order(create_order):
        order = given(Order).process(create_order)

        assert order.accepted
        assert OrderCreated in order.events
        assert order.status == "Created"
"""

from __future__ import annotations

from typing import Any

from protean.exceptions import ProteanExceptionWithMessage
from protean.utils import fqn
from protean.utils.eventing import (
    DomainMeta,
    MessageEnvelope,
    MessageHeaders,
    Metadata,
)
from protean.utils.reflection import _ID_FIELD_NAME


def given(aggregate_cls, *events):
    """Start an event-sourcing test sentence.

    Args:
        aggregate_cls: The aggregate class under test.
        *events: Past domain events constituting the aggregate's history.

    Returns:
        AggregateResult ready for ``.after()`` or ``.process()``.

    Examples::

        given(Order)                                    # no history
        given(Order, order_created)                     # one event
        given(Order, order_created, order_confirmed)    # multiple events
    """
    return AggregateResult(aggregate_cls, list(events))


class EventLog:
    """A collection of domain events with Pythonic access.

    Supports ``in`` (contains by type), ``[]`` (getitem by type or index),
    ``len``, ``bool``, iteration, ``.get()``, ``.of_type()``, ``.types``,
    ``.first``, and ``.last``.

    Examples::

        assert PaymentPending in log
        assert log[PaymentPending].payment_id == "pay-001"
        assert log.get(PaymentFailed) is None
        assert log.types == [PaymentPending]
        assert len(log) == 1
        assert log.first is placed_event
        assert log                          # truthy when non-empty
    """

    def __init__(self, events: list[Any]) -> None:
        self._events = list(events)

    def __contains__(self, event_cls: type) -> bool:
        """Check if an event of this type exists."""
        return any(isinstance(e, event_cls) for e in self._events)

    def __getitem__(self, key: type | int) -> Any:
        """Access by event class (first match) or by index.

        Raises ``KeyError`` if an event class is not found.
        """
        if isinstance(key, type):
            for e in self._events:
                if isinstance(e, key):
                    return e
            raise KeyError(f"No {key.__name__} event found")
        return self._events[key]

    def get(self, event_cls: type, default: Any = None) -> Any:
        """Safe access by event class. Returns *default* if not found."""
        for e in self._events:
            if isinstance(e, event_cls):
                return e
        return default

    def of_type(self, event_cls: type) -> list[Any]:
        """Return all events of the given type."""
        return [e for e in self._events if isinstance(e, event_cls)]

    @property
    def types(self) -> list[type]:
        """Ordered list of event types."""
        return [type(e) for e in self._events]

    @property
    def first(self) -> Any | None:
        """First event, or ``None`` if empty."""
        return self._events[0] if self._events else None

    @property
    def last(self) -> Any | None:
        """Last event, or ``None`` if empty."""
        return self._events[-1] if self._events else None

    def __len__(self) -> int:
        return len(self._events)

    def __bool__(self) -> bool:
        return len(self._events) > 0

    def __iter__(self):
        return iter(self._events)

    def __repr__(self) -> str:
        type_names = [type(e).__name__ for e in self._events]
        return f"EventLog({type_names})"


class AggregateResult:
    """The result of processing a command against an event-sourced aggregate.

    Proxies attribute access to the underlying aggregate, so
    ``order.status`` works directly.

    Supports multi-command chaining — call ``.process()`` repeatedly
    to build up aggregate state through the real pipeline::

        order = (
            given(Order)
            .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
            .process(ConfirmOrder(order_id=oid))
            .process(InitiatePayment(order_id=oid, payment_id="pay-001"))
        )

    Created by :func:`given`, not directly.
    """

    def __init__(
        self, aggregate_cls: type, given_events: list[Any] | None = None
    ) -> None:
        self._aggregate_cls = aggregate_cls
        self._given_events = list(given_events or [])
        self._aggregate = None
        self._new_events: EventLog = EventLog([])
        self._all_events: list[Any] = []
        self._rejection: Exception | None = None
        self._processed: bool = False
        self._aggregate_id: Any = None
        self._event_count: int = 0
        self._seeded: bool = False

    def after(self, *events) -> AggregateResult:
        """Accumulate more history events (for BDD "And given" steps).

        Returns self for chaining::

            order = given(Order, order_created)
            order = order.after(order_confirmed)
            order = order.after(payment_pending)
        """
        self._given_events.extend(events)
        return self

    def process(self, command) -> AggregateResult:
        """Dispatch a command through the domain's full processing pipeline.

        Seeds the event store with given events (on first call only),
        then calls ``domain.process(command)`` which routes through the
        real command handler, repository, and unit of work.

        Can be called multiple times to chain commands::

            result = (
                given(Order)
                .process(CreateOrder(...))
                .process(ConfirmOrder(...))
            )

        After each call:

        - ``.events`` contains events from the **last** command only.
        - ``.all_events`` contains events from **all** commands.
        - ``.accepted`` / ``.rejected`` reflects the **last** command.

        Returns self for chaining.
        """
        from protean.utils.globals import current_domain

        domain = current_domain
        self._processed = True
        self._rejection = None  # Reset for this command

        # Seed event store with given events (first call only)
        if self._given_events and not self._seeded:
            self._aggregate_id = self._seed_events(domain)
            self._event_count = len(self._given_events)
            self._seeded = True

        # Process command through the domain
        try:
            result = domain.process(command, asynchronous=False)
        except Exception as exc:
            self._rejection = exc
            # On rejection, load aggregate from event store to reflect
            # the state before the failed command
            if self._aggregate_id is not None:
                self._aggregate = domain.event_store.store.load_aggregate(
                    self._aggregate_cls, str(self._aggregate_id)
                )
            self._new_events = EventLog([])
            return self

        # Determine aggregate_id if not known (e.g. create commands)
        if self._aggregate_id is None:
            self._aggregate_id = result

        aggregate_id_str = str(self._aggregate_id)

        # Load aggregate from event store
        self._aggregate = domain.event_store.store.load_aggregate(
            self._aggregate_cls, aggregate_id_str
        )

        # Read new events (those beyond previously seen events)
        stream = f"{self._aggregate_cls.meta_.stream_category}-{aggregate_id_str}"
        all_messages = domain.event_store.store.read(stream)
        new_events = [m.to_domain_object() for m in all_messages[self._event_count :]]
        self._new_events = EventLog(new_events)
        self._all_events.extend(new_events)
        self._event_count = len(all_messages)

        return self

    # ------------------------------------------------------------------
    # Result properties
    # ------------------------------------------------------------------

    @property
    def events(self) -> EventLog:
        """New events raised by the last command (``EventLog``)."""
        return self._new_events

    @property
    def all_events(self) -> EventLog:
        """All events raised across all ``.process()`` calls (``EventLog``)."""
        return EventLog(self._all_events)

    @property
    def rejection(self) -> Exception | None:
        """The exception if the command was rejected, or ``None``."""
        return self._rejection

    @property
    def accepted(self) -> bool:
        """``True`` if the last command was processed without exception."""
        return self._processed and self._rejection is None

    @property
    def rejected(self) -> bool:
        """``True`` if the last command raised an exception."""
        return self._processed and self._rejection is not None

    @property
    def rejection_messages(self) -> list[str]:
        """Flat list of error messages from the rejection.

        For ``ValidationError``, flattens the ``messages`` dict values.
        For other exceptions, returns ``[str(exc)]``.
        Returns ``[]`` if no rejection.

        Examples::

            assert "Order must be confirmed" in result.rejection_messages
        """
        if self._rejection is None:
            return []
        if isinstance(self._rejection, ProteanExceptionWithMessage):
            return [
                msg
                for messages in self._rejection.messages.values()
                for msg in messages
            ]
        return [str(self._rejection)]

    @property
    def aggregate(self):
        """The raw aggregate instance, if needed directly."""
        return self._aggregate

    def __getattr__(self, name: str):
        """Proxy attribute access to the underlying aggregate.

        This makes ``order.status``, ``order.items``, ``order.pricing``
        work directly on the result object.
        """
        # Avoid infinite recursion on private/dunder attrs
        if name.startswith("_"):
            raise AttributeError(name)
        if self._aggregate is not None:
            return getattr(self._aggregate, name)
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'. "
            f"Did you call .process() first?"
        )

    def __repr__(self) -> str:
        status = (
            "accepted" if self.accepted else "rejected" if self.rejected else "pending"
        )
        agg_name = self._aggregate_cls.__name__
        return f"<AggregateResult({agg_name}) {status}>"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _seed_events(self, domain) -> Any:
        """Write given events to the event store and process handlers.

        Reconstitutes the aggregate from events to determine its identity,
        then enriches each event with proper metadata and appends to the
        event store so that ``domain.process()`` can load the aggregate
        via its repository.

        Also runs synchronous event handlers (projectors, etc.) for each
        seeded event, mirroring what UoW commit does. This ensures
        projections and other side effects are in place when the command
        under test is processed.

        Returns the aggregate identifier.
        """
        from protean.utils import Processing

        event_store = domain.event_store.store

        # Reconstitute aggregate to discover its identity
        temp_aggregate = self._aggregate_cls.from_events(self._given_events)
        id_field_name = getattr(self._aggregate_cls, _ID_FIELD_NAME)
        aggregate_id = getattr(temp_aggregate, id_field_name)

        stream_category = self._aggregate_cls.meta_.stream_category
        stream = f"{stream_category}-{aggregate_id}"

        enriched_events = []
        for i, event in enumerate(self._given_events):
            version = i + 1
            event_identity = f"{stream}-{version}"

            headers = MessageHeaders(
                id=event_identity,
                type=event.__class__.__type__,
                stream=stream,
                time=event._metadata.headers.time
                if (event._metadata.headers and event._metadata.headers.time)
                else None,
            )

            envelope = MessageEnvelope.build(event.payload)

            domain_meta = DomainMeta(
                kind="EVENT",
                fqn=fqn(event.__class__),
                stream_category=stream_category,
                version=event.__class__.__version__,
                sequence_id=str(version),
                asynchronous=False,
            )

            metadata = Metadata(
                headers=headers,
                envelope=envelope,
                domain=domain_meta,
            )

            enriched = event.__class__(
                event.payload,
                _expected_version=i - 1,
                _metadata=metadata,
            )

            event_store.append(enriched)
            enriched_events.append(enriched)

        # Process event handlers (projectors, etc.) for seeded events,
        # just like UoW commit does for synchronous processing.
        if domain.config["event_processing"] == Processing.SYNC.value:
            for enriched in enriched_events:
                handler_classes = domain.handlers_for(enriched)
                for handler_cls in handler_classes:
                    handler_cls._handle(enriched)

        return aggregate_id
