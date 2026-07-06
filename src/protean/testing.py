"""Testing DSL for Protean.

Provides fluent, Pythonic DSLs for testing event-sourced aggregates,
process managers, projections, and domain invariants.

Event-sourcing tests
--------------------

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

Process manager tests
---------------------

When the first argument is a process manager class, ``given()`` returns
a ``ProcessManagerResult`` that feeds events through the PM's handlers::

    result = given(
        OrderFulfillmentPM,
        OrderPlaced(order_id="o1", customer_id="c1", total=100.0),
        PaymentConfirmed(payment_id="p1", order_id="o1", amount=100.0),
    )
    assert result.status == "awaiting_shipment"
    assert not result.is_complete
    assert result.transition_count == 2

Or events first with ``.results_in()``::

    result = given(
        OrderPlaced(order_id="o1", ...),
        PaymentConfirmed(order_id="o1", ...),
    ).results_in(OrderFulfillmentPM, id="o1")

Projection tests
----------------

When called with event instances only (no class), ``given()`` returns
an ``EventSequence`` for testing projections::

    result = given(
        Registered(user_id="u1", name="Alice"),
        Transacted(user_id="u1", amount=100),
    ).then(Balances, id="u1")

    result.has(name="Alice", balance=100)
    assert result.projection.balance == 100

To test invariants, use ``pytest.raises(ValidationError)`` directly.
"""

from __future__ import annotations

import difflib
import inspect
import json
import warnings
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from collections.abc import Callable, Iterator, Sequence
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from protean.core.process_manager import (
    BaseProcessManager,
    _resolve_correlation_value,
)
from protean.exceptions import (
    ObjectNotFoundError,
    ProteanExceptionWithMessage,
    ValidationError,
)

if TYPE_CHECKING:
    from protean.core.aggregate import BaseAggregate
    from protean.core.event import BaseEvent
    from protean.domain import Domain
    from protean.port.event_store import BaseEventStore, CausationNode
from protean.utils import Processing, fqn
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageEnvelope,
    MessageHeaders,
    Metadata,
    new_correlation_id,
)
from protean.utils.globals import current_domain
from protean.utils.reflection import _ID_FIELD_NAME
from protean.utils.sync_dispatch import dispatch_events_sync


def _event_store_of(domain: "Domain") -> "BaseEventStore":
    """Return the domain's initialised event store, narrowing away ``None``.

    The testing DSL always runs against a live, fully-initialised domain, so
    ``domain.event_store.store`` is never ``None`` here. This helper makes that
    invariant explicit for the type checker (and fails loudly if it is ever
    violated).
    """
    store = domain.event_store.store
    if store is None:  # pragma: no cover - defensive; store is always set here
        raise RuntimeError("Event store is not initialised on the domain")
    return store


def _flatten_messages(
    messages: dict[str, list[str]] | list[str] | str,
) -> list[str]:
    """Flatten a :class:`ProteanExceptionWithMessage.messages` value.

    ``messages`` can be a ``{field: [msg, ...]}`` dict, a flat list of
    messages, or a single string. Normalise all three into a flat
    ``list[str]``.
    """
    if isinstance(messages, dict):
        return [msg for msgs in messages.values() for msg in msgs]
    if isinstance(messages, str):
        return [messages]
    return list(messages)


def given(
    cls_or_event: "type | BaseEvent", *events: "BaseEvent"
) -> AggregateResult | ProcessManagerResult | EventSequence:
    """Start a test sentence.

    Polymorphic entry point:

    - ``given(AggregateClass, *events)`` — returns an ``AggregateResult`` for
      event-sourcing tests.
    - ``given(ProcessManagerClass, *events)`` — returns a
      ``ProcessManagerResult`` for process manager tests.
    - ``given(event, *events)`` — returns an ``EventSequence`` for projection
      or process manager tests (via ``.results_in()``).

    Examples::

        # Event-sourcing test
        given(Order)                                    # no history
        given(Order, order_created)                     # one event
        given(Order, order_created, order_confirmed)    # multiple events

        # Process manager test
        given(OrderFulfillmentPM, order_placed, payment_confirmed)

        # Projection test
        given(Registered(user_id="u1", name="Alice"))
        given(registered_event, transacted_event)
    """
    if isinstance(cls_or_event, type):
        if issubclass(cls_or_event, BaseProcessManager):
            return ProcessManagerResult(cls_or_event, list(events))
        return AggregateResult(cast("type[BaseAggregate]", cls_or_event), list(events))
    # All arguments are event instances → projection / PM testing path
    return EventSequence([cls_or_event, *events])


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

    def __iter__(self) -> Iterator[Any]:
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

    Created by ``given()``, not directly.
    """

    def __init__(
        self,
        aggregate_cls: "type[BaseAggregate]",
        given_events: list[Any] | None = None,
    ) -> None:
        self._aggregate_cls = aggregate_cls
        self._given_events = list(given_events or [])
        self._aggregate: BaseAggregate | None = None
        self._new_events: EventLog = EventLog([])
        self._all_events: list[Any] = []
        self._rejection: Exception | None = None
        self._processed: bool = False
        self._aggregate_id: Any = None
        self._event_count: int = 0
        self._seeded: bool = False

    def after(self, *events: Any) -> AggregateResult:
        """Accumulate more history events (for BDD "And given" steps).

        Returns self for chaining::

            order = given(Order, order_created)
            order = order.after(order_confirmed)
            order = order.after(payment_pending)
        """
        self._given_events.extend(events)
        return self

    def process(
        self, command: Any, *, correlation_id: str | None = None
    ) -> AggregateResult:
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
        domain = current_domain
        store = _event_store_of(domain)
        self._processed = True
        self._rejection = None  # Reset for this command

        # Seed event store with given events (first call only)
        if self._given_events and not self._seeded:
            self._aggregate_id = self._seed_events(domain)
            self._event_count = len(self._given_events)
            self._seeded = True

        # Process command through the domain
        try:
            result = domain.process(
                command, asynchronous=False, correlation_id=correlation_id
            )
        except Exception as exc:
            self._rejection = exc
            # On rejection, load aggregate from event store to reflect
            # the state before the failed command
            if self._aggregate_id is not None:
                self._aggregate = store.load_aggregate(
                    self._aggregate_cls, str(self._aggregate_id)
                )
            self._new_events = EventLog([])
            return self

        # Determine aggregate_id if not known (e.g. create commands)
        if self._aggregate_id is None:
            self._aggregate_id = result

        aggregate_id_str = str(self._aggregate_id)

        # Load aggregate from event store
        self._aggregate = store.load_aggregate(self._aggregate_cls, aggregate_id_str)

        # Read new events (those beyond previously seen events)
        stream = f"{self._aggregate_cls.meta_.stream_category}-{aggregate_id_str}"
        all_messages = store.read(stream)
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
            return _flatten_messages(self._rejection.messages)
        return [str(self._rejection)]

    @property
    def aggregate(self) -> Any:
        """The raw aggregate instance, if needed directly."""
        return self._aggregate

    def __getattr__(self, name: str) -> Any:
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

    def _seed_events(self, domain: "Domain") -> Any:
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
        event_store = _event_store_of(domain)

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
        # just like UoW commit does for synchronous processing — breadth-first
        # via the shared drain so a seeded event that starts a multi-step
        # process manager cascades correctly (ADR-0016).
        if domain.config["event_processing"] == Processing.SYNC.value:
            dispatch_events_sync(enriched_events, domain.handlers_for)

        return aggregate_id


# ---------------------------------------------------------------------------
# Integration-test helpers: process_and_wait / drain
# ---------------------------------------------------------------------------


class ProcessResult:
    """The outcome of :func:`process_and_wait`.

    Surfaces the three things an integration test cares about without
    reaching into framework internals (outbox rows, event store streams):

    - ``result`` — the command handler's return value (synchronous
      processing) or the store position of the enqueued command
      (asynchronous processing).
    - ``events`` — an :class:`EventLog` of every event raised in the
      command's correlation chain, ordered chronologically.
    - ``error`` — the exception raised by :meth:`Domain.process`, or
      ``None``. This covers a synchronous handler error and any
      submission-time rejection (unregistered command, expired deadline,
      duplicate key, enrichment ``ValidationError``) in either mode.
      Asynchronous *handler* failures happen after the command is enqueued,
      are absorbed by the engine (retries / DLQ), and are not surfaced here.

    Created by :func:`process_and_wait`, not directly.

    Example::

        outcome = process_and_wait(PlaceOrder(order_id="o1", ...), domain)

        assert outcome.succeeded
        assert OrderPlaced in outcome.events
        assert outcome.events[OrderPlaced].order_id == "o1"
    """

    def __init__(
        self,
        *,
        result: Any,
        events: list[Any],
        error: Exception | None,
    ) -> None:
        self._result = result
        self._events = EventLog(events)
        self._error = error

    @property
    def result(self) -> Any:
        """The command handler's return value, or the enqueue position."""
        return self._result

    @property
    def events(self) -> EventLog:
        """Events raised in the command's correlation chain (``EventLog``)."""
        return self._events

    @property
    def error(self) -> Exception | None:
        """The exception raised by :meth:`Domain.process`, or ``None``.

        A synchronous handler error, or a submission-time rejection in either
        mode. Asynchronous handler failures (after enqueue) are not captured.
        """
        return self._error

    @property
    def succeeded(self) -> bool:
        """``True`` if :meth:`Domain.process` raised no exception.

        In asynchronous mode this reflects *submission* success, not the
        eventual async handler outcome — engine failures are absorbed and
        never flip this to ``False``.
        """
        return self._error is None

    @property
    def failed(self) -> bool:
        """``True`` if :meth:`Domain.process` raised an exception.

        Mirrors :attr:`succeeded` (submission-level in async mode).
        """
        return not self.succeeded

    def __repr__(self) -> str:
        status = "failed" if self.failed else "succeeded"
        return f"<ProcessResult {status} events={len(self._events)}>"


def _events_for_correlation(domain: "Domain", correlation_id: str) -> list[Any]:
    """Load every event in a correlation chain as domain objects.

    Reads the correlation group from the event store and returns the
    ``EVENT`` messages (commands excluded) as reconstituted domain
    objects, ordered by ``global_position``.
    """
    store = _event_store_of(domain)
    group = store._load_correlation_group(correlation_id)
    group.sort(key=lambda raw: raw.get("global_position", 0))

    events: list[Any] = []
    for raw in group:
        message = Message.deserialize(raw)
        if (
            message.metadata
            and message.metadata.domain
            and message.metadata.domain.kind == "EVENT"
        ):
            events.append(message.to_domain_object())
    return events


def drain(
    domain: "Domain | None" = None,
    *,
    until: Callable[[], bool] | None = None,
    max_cycles: int = 5,
) -> int:
    """Run the engine in test mode until *until* is satisfied or the budget runs out.

    Replaces the hand-rolled ``for _ in range(N): Engine(...).run()`` loop
    that integration tests copy-paste. Each cycle runs one full test-mode
    engine pass (draining outbox → broker → subscriptions → handlers).

    Args:
        domain: The domain to drain. Defaults to ``current_domain``.
        until: Optional predicate. Draining stops early once it returns
            truthy. When omitted, a single engine pass is run.
        max_cycles: Upper bound on engine passes so a never-satisfied
            *until* cannot hang the test. Must be at least 1. Each test-mode
            engine pass takes at least ~1 second, so the bound is also a
            worst-case latency budget — raise it only for flows that
            genuinely need more passes.

    Returns:
        The number of engine passes actually run. If *until* was supplied but
        never became truthy, this equals ``max_cycles`` and a ``UserWarning``
        is emitted so the exhausted bound is not silently swallowed.

    Example::

        drain(domain, until=lambda: repo.get("o1").status == "shipped")
    """
    if max_cycles < 1:
        raise ValueError("max_cycles must be at least 1")

    domain = domain if domain is not None else current_domain

    # Local import: the server engine is a heavy subsystem, kept out of the
    # module top so importing `protean.testing` stays cheap (CLAUDE.md #3).
    from protean.server.engine import Engine  # noqa: PLC0415

    for cycle in range(max_cycles):
        Engine(domain=domain, test_mode=True).run()
        if until is None or until():
            return cycle + 1

    # Reaching here means `until` was supplied (a `None` predicate returns on
    # the first cycle above) but stayed falsey for every pass. Surface the
    # exhausted bound rather than swallowing it (CLAUDE.md: no silent caps).
    warnings.warn(
        f"drain() exhausted max_cycles={max_cycles} before `until` became "
        "truthy; the awaited effect may not have settled. Raise max_cycles "
        "if the flow needs more engine passes.",
        UserWarning,
        stacklevel=2,
    )
    return max_cycles


def process_and_wait(
    command: Any,
    domain: "Domain | None" = None,
    *,
    until: Callable[[], bool] | None = None,
    max_cycles: int = 5,
) -> ProcessResult:
    """Process a command and wait for its effects to settle.

    Makes the *same test body work in both processing modes*:

    - **Synchronous** (``event_processing``/``command_processing`` set to
      ``"sync"``): the whole chain runs inline during the call; the result
      is returned immediately.
    - **Asynchronous** (the default): the command is enqueued and a
      bounded test-mode engine drains the outbox, broker, and handlers
      before returning.

    Args:
        command: The command instance to process.
        domain: The domain to process against. Defaults to
            ``current_domain``.
        until: Optional predicate forwarded to :func:`drain`; draining
            stops early once it returns truthy (async mode only).
        max_cycles: Upper bound on engine passes when draining (see
            :func:`drain` — each pass takes at least ~1 second).

    Returns:
        A :class:`ProcessResult` exposing the command result, the events
        that fired, and any synchronous/submission-time error (see
        :class:`ProcessResult` for what is and isn't captured).

    Example::

        outcome = process_and_wait(PlaceOrder(order_id="o1", ...), domain)
        assert outcome.succeeded
        assert OrderPlaced in outcome.events
    """
    domain = domain if domain is not None else current_domain
    correlation_id = new_correlation_id()

    result: Any = None
    error: Exception | None = None
    try:
        result = domain.process(command, correlation_id=correlation_id)
    except Exception as exc:  # noqa: BLE001 — captured for the caller to assert on
        error = exc

    # Drain only when something is left to process asynchronously. A
    # synchronous failure already ran (and rolled back) inline, so there is
    # nothing for the engine to do.
    needs_drain = error is None and Processing.ASYNC.value in (
        domain.config["command_processing"],
        domain.config["event_processing"],
    )
    if needs_drain:
        drain(domain, until=until, max_cycles=max_cycles)

    events = _events_for_correlation(domain, correlation_id)
    return ProcessResult(result=result, events=events, error=error)


# ---------------------------------------------------------------------------
# Projection testing DSL
# ---------------------------------------------------------------------------


class EventSequence:
    """A sequence of domain events for testing projections.

    Created by ``given()`` when all arguments are event instances.
    Use ``.then()`` to query the resulting projection state after
    processing the events through their projector handlers.

    Example::

        result = given(
            Registered(user_id="u1", name="Alice"),
            Transacted(user_id="u1", amount=100),
        ).then(Balances, id="u1")

        result.has(name="Alice", balance=100)
    """

    def __init__(self, events: list[Any]) -> None:
        self._events = list(events)

    def then(self, projection_cls: type, **identity: Any) -> ProjectionResult:
        """Process events through projector handlers and query the projection.

        Dispatches each event to its registered handlers (projectors, event
        handlers) and then retrieves the projection record identified by
        the given keyword arguments.

        Args:
            projection_cls: The projection class to query.
            **identity: Keyword arguments identifying the projection record.
                Must provide exactly one keyword matching the projection's
                identifier field.

        Returns:
            ProjectionResult: Result object with ``.has()``, ``.found``,
            and ``.projection`` for assertions.
        """
        if not identity:
            raise ValueError(
                "then() requires at least one keyword argument to identify "
                "the projection record (e.g., id='u1')"
            )

        domain = current_domain

        # Process each event through its handlers — breadth-first (ADR-0016).
        dispatch_events_sync(self._events, domain.handlers_for)

        # Retrieve the projection

        repo = domain.repository_for(projection_cls)
        identifier_value = next(iter(identity.values()))

        try:
            projection = repo.get(identifier_value)
        except ObjectNotFoundError:
            projection = None

        return ProjectionResult(projection_cls, projection)

    def results_in(self, pm_cls: type, **identity: Any) -> ProcessManagerResult:
        """Feed events through a process manager and return the result.

        An alternative to ``given(PMClass, *events)`` when you want to
        start with events and specify the PM class afterward::

            result = given(
                OrderPlaced(order_id="o1", ...),
                PaymentConfirmed(order_id="o1", ...),
            ).results_in(OrderFulfillmentPM, id="o1")

        Args:
            pm_cls: The process manager class.
            **identity: Optional keyword arguments to identify the PM
                instance to retrieve. If provided, uses the first value
                as the correlation value for loading the PM.

        Returns:
            ProcessManagerResult with the PM state after processing.
        """
        identifier_value = next(iter(identity.values()), None) if identity else None
        return ProcessManagerResult(
            cast("type[BaseProcessManager]", pm_cls),
            self._events,
            correlation_value=identifier_value,
        )

    def __repr__(self) -> str:
        type_names = [type(e).__name__ for e in self._events]
        return f"EventSequence({type_names})"


class ProcessManagerResult:
    """The result of feeding events through a process manager.

    Proxies attribute access to the underlying PM instance, so
    ``result.status`` works directly.

    Created by ``given(PMClass, *events)`` or
    ``given(*events).results_in(PMClass)``, not directly.

    Example::

        result = given(
            OrderFulfillmentPM,
            OrderPlaced(order_id="o1", customer_id="c1", total=100.0),
            PaymentConfirmed(payment_id="p1", order_id="o1", amount=100.0),
        )
        assert result.status == "awaiting_shipment"
        assert not result.is_complete
        assert result.transition_count == 2
    """

    def __init__(
        self,
        pm_cls: "type[BaseProcessManager]",
        events: list[Any] | None = None,
        *,
        correlation_value: str | None = None,
    ) -> None:
        self._pm_cls = pm_cls
        self._events = list(events or [])
        self._pm_instance: BaseProcessManager | None = None
        self._transition_count: int = 0
        self._correlation_value = correlation_value
        self._processed: bool = False

        # Auto-process if events were given
        if self._events:
            self._process_events()

    def _process_events(self) -> None:
        """Feed all events through the PM's _handle() method — breadth-first
        via the shared drain so a multi-step PM cascades to completion under
        synchronous processing (ADR-0016)."""
        dispatch_events_sync(self._events, lambda _event: [self._pm_cls])
        self._processed = True
        self._load_pm()

    def _load_pm(self) -> None:
        """Load the PM instance from the event store after processing."""
        # Determine correlation value from the first event's matching handler
        correlation_value = self._correlation_value
        if correlation_value is None:
            correlation_value = self._infer_correlation_value()

        if correlation_value is None:
            self._pm_instance = None
            self._transition_count = 0
            return

        stream_name = f"{self._pm_cls.meta_.stream_category}-{correlation_value}"
        messages = _event_store_of(current_domain).read(stream_name)

        if messages:
            self._pm_instance = self._pm_cls._from_transitions(
                messages, correlation_value
            )
            self._transition_count = len(messages)
        else:
            self._pm_instance = None
            self._transition_count = 0

    def _infer_correlation_value(self) -> str | None:
        """Infer the correlation value from the first event and the PM's handlers.

        Inspects the PM's handler methods to find the correlate spec,
        then extracts the correlation value from the first event.
        """
        if not self._events:
            return None

        # Find the correlation spec from the first event's handler
        first_event = self._events[0]
        handlers = self._pm_cls._handlers.get(
            first_event.__class__.__type__
        ) or self._pm_cls._handlers.get("$any")

        if not handlers:
            return None

        handler_method = next(iter(handlers))
        correlate_spec = getattr(handler_method, "_correlate", None)
        if correlate_spec is None:
            return None

        return _resolve_correlation_value(first_event, correlate_spec)

    # ------------------------------------------------------------------
    # Result properties
    # ------------------------------------------------------------------

    @property
    def is_complete(self) -> bool:
        """``True`` if the process manager has been marked as complete."""
        if self._pm_instance is None:
            return False
        return self._pm_instance._is_complete

    @property
    def not_started(self) -> bool:
        """``True`` if no PM instance was found (no start event matched)."""
        return self._pm_instance is None

    @property
    def transition_count(self) -> int:
        """Number of transitions (handler invocations) recorded."""
        return self._transition_count

    @property
    def process_manager(self) -> Any:
        """The raw process manager instance, or ``None`` if not found."""
        return self._pm_instance

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to the underlying PM instance.

        This makes ``result.status``, ``result.order_id`` work directly.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        if self._pm_instance is not None:
            return getattr(self._pm_instance, name)
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'. "
            f"Process manager not found — did any start event match?"
        )

    def __repr__(self) -> str:
        pm_name = self._pm_cls.__name__
        if self.not_started:
            status = "not_started"
        elif self.is_complete:
            status = "complete"
        else:
            status = f"transitions={self._transition_count}"
        return f"<ProcessManagerResult({pm_name}) {status}>"


class ProjectionResult:
    """The result of querying a projection after processing events.

    Provides ``.has()`` for fluent attribute assertions, ``.found``
    to check existence, and ``.projection`` for direct access.

    Example::

        result = given(registered_event).then(Balances, id="u1")

        assert result.found
        result.has(name="Alice", balance=0)
        assert result.projection.name == "Alice"
    """

    def __init__(self, projection_cls: type, projection: Any) -> None:
        self._projection_cls = projection_cls
        self._projection = projection

    @property
    def found(self) -> bool:
        """``True`` if the projection record was found."""
        return self._projection is not None

    @property
    def not_found(self) -> bool:
        """``True`` if the projection record was not found."""
        return self._projection is None

    @property
    def projection(self) -> Any:
        """The projection instance, or ``None`` if not found."""
        return self._projection

    def has(self, **expected: Any) -> ProjectionResult:
        """Assert that the projection has the expected attribute values.

        Raises ``AssertionError`` with a descriptive message if any
        attribute does not match.

        Returns self for chaining.

        Example::

            result.has(name="Alice", balance=100)
        """
        if self._projection is None:
            raise AssertionError(
                f"{self._projection_cls.__name__} projection not found"
            )
        for attr, expected_value in expected.items():
            try:
                actual = getattr(self._projection, attr)
            except AttributeError:
                raise AssertionError(
                    f"{self._projection_cls.__name__} has no attribute '{attr}'"
                ) from None
            if actual != expected_value:
                raise AssertionError(
                    f"{self._projection_cls.__name__}.{attr}: "
                    f"expected {expected_value!r}, got {actual!r}"
                )
        return self

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to the underlying projection."""
        if name.startswith("_"):
            raise AttributeError(name)
        if self._projection is not None:
            return getattr(self._projection, name)
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'. "
            f"Projection not found."
        )

    def __repr__(self) -> str:
        status = "found" if self.found else "not_found"
        proj_name = self._projection_cls.__name__
        return f"<ProjectionResult({proj_name}) {status}>"


# ---------------------------------------------------------------------------
# Correlation chain assertions
# ---------------------------------------------------------------------------


def assert_chain(
    chain: Sequence[CausationNode],
    expected: Sequence[str | type],
) -> None:
    """Assert that a correlation chain matches an expected message sequence.

    Compares the ``message_type`` of each
    :class:`~protean.port.event_store.CausationNode` against the expected
    names, in order.

    Args:
        chain: Ordered list of ``CausationNode`` objects, typically from
            ``domain.correlation_trace(correlation_id)``.
        expected: Sequence of expected message types.  Each element can be
            a string (matched against ``CausationNode.message_type``) or
            a domain element class whose ``__type__`` attribute is used.

    Raises:
        AssertionError: If the chain length or any message type does not
            match.

    Example::

        from protean.testing import assert_chain

        chain = domain.correlation_trace(correlation_id)
        assert_chain(chain, [
            "Test.PlaceOrder.v1",
            "Test.OrderPlaced.v1",
            "Test.ConfirmOrder.v1",
            "Test.OrderConfirmed.v1",
        ])

        # Or using classes directly:
        assert_chain(chain, [PlaceOrder, OrderPlaced, ConfirmOrder, OrderConfirmed])
    """
    actual_types = [node.message_type for node in chain]
    expected_types = [getattr(e, "__type__", e) for e in expected]

    if actual_types != expected_types:
        raise AssertionError(
            f"Chain mismatch.\n  Expected: {expected_types}\n  Actual:   {actual_types}"
        )


# ---------------------------------------------------------------------------
# Snapshot testing
# ---------------------------------------------------------------------------

# Module-level flag set by the pytest plugin when --update-snapshots is passed.
_update_snapshots: bool = False


def _snapshot_data(obj: Any, exclude: list[str] | None = None) -> dict[str, Any]:
    """Convert *obj* to a JSON-serialisable dict suitable for snapshotting.

    Supports domain objects (via ``.to_dict()``), plain dicts, and Pydantic
    models (via ``.model_dump()``).

    Args:
        obj: The object to snapshot.
        exclude: Field names to remove from the resulting dict.
    """
    if isinstance(obj, dict):
        data = dict(obj)
    elif hasattr(obj, "to_dict"):
        data = obj.to_dict()
    elif hasattr(obj, "model_dump"):
        data = obj.model_dump()
    else:
        raise TypeError(
            f"Cannot snapshot {type(obj).__name__}: "
            "expected a dict, a domain object with .to_dict(), "
            "or a Pydantic model with .model_dump()"
        )

    if exclude:
        for key in exclude:
            data.pop(key, None)
    return data


def _snapshot_json_default(obj: Any) -> Any:
    """JSON serializer for known stable types only.

    Raises ``TypeError`` for anything else so that non-deterministic
    representations (e.g. ``str(obj)`` with memory addresses) never
    silently slip into snapshots.
    """
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(
        f"Object of type {type(obj).__name__} is not JSON serializable. "
        "Convert it before passing to assert_snapshot()."
    )


def _snapshot_dir_for_caller() -> Path:
    """Return the ``__snapshots__/<test_module>`` directory for the calling test.

    Walks up the call stack to find the first frame in a file whose name
    starts with ``test_``, and uses that module's name (without the ``.py``
    extension) as the snapshot subdirectory.
    """
    stack = inspect.stack(context=0)
    for frame_info in stack:
        filename = Path(frame_info.filename)
        if filename.name.startswith("test_"):
            return filename.parent / "__snapshots__" / filename.stem
    # Fallback: use the first frame outside this module
    this_file = Path(__file__).name
    for frame_info in stack:
        filename = Path(frame_info.filename)
        if filename.name != this_file:
            return filename.parent / "__snapshots__" / filename.stem
    # Ultimate fallback: direct caller
    caller = Path(stack[1].filename)
    return caller.parent / "__snapshots__" / caller.stem


def assert_snapshot(
    obj: Any,
    name: str,
    *,
    exclude: list[str] | None = None,
) -> None:
    """Compare *obj* against a stored JSON snapshot.

    On first run (or when ``--update-snapshots`` is passed to pytest) the
    snapshot file is created automatically.  On subsequent runs the current
    state is compared against the stored snapshot and a unified diff is
    shown on mismatch.

    Snapshot files are stored under::

        <test_file_dir>/__snapshots__/<test_module_name>/<name>.json

    Args:
        obj: A domain object (with ``.to_dict()``), a plain dict, or a
            Pydantic model (with ``.model_dump()``).
        name: A short, descriptive name for this snapshot (used as the
            file stem).
        exclude: Field names to strip before comparison (useful for
            volatile fields like ``id`` or ``created_at``).

    Raises:
        AssertionError: If the current state does not match the stored
            snapshot.
        TypeError: If *obj* cannot be converted to a dict.

    Examples::

        from protean.testing import assert_snapshot

        order = Order(customer_id="c1", items=[OrderItem(...)])
        assert_snapshot(order, "order_with_items")

        # Exclude volatile fields
        assert_snapshot(order, "order_stable", exclude=["id", "created_at"])

        # Works with plain dicts
        assert_snapshot(result.to_dict(), "pm_state")

        # Regenerate all snapshots:
        #   pytest --update-snapshots
    """
    data = _snapshot_data(obj, exclude)

    snapshot_dir = _snapshot_dir_for_caller()

    # Validate snapshot name to prevent path traversal
    name_path = Path(name)
    if (
        name_path.is_absolute()
        or len(name_path.parts) != 1
        or any(part in (".", "..") for part in name_path.parts)
    ):
        raise ValueError(
            f"Invalid snapshot name {name!r}: "
            "must be a simple file name without path separators"
        )

    snapshot_file = snapshot_dir / f"{name}.json"

    current_json = (
        json.dumps(data, indent=2, sort_keys=True, default=_snapshot_json_default)
        + "\n"
    )

    if _update_snapshots or not snapshot_file.exists():
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file.write_text(current_json, encoding="utf-8")
        return

    stored_json = snapshot_file.read_text(encoding="utf-8")

    if current_json == stored_json:
        return

    # Build a human-readable unified diff
    diff = difflib.unified_diff(
        stored_json.splitlines(keepends=True),
        current_json.splitlines(keepends=True),
        fromfile=f"stored: {name}.json",
        tofile=f"current: {name}.json",
    )
    diff_text = "".join(diff)
    raise AssertionError(
        f"Snapshot mismatch for '{name}'.\n"
        f"Run pytest --update-snapshots to update.\n\n{diff_text}"
    )


# ---------------------------------------------------------------------------
# Generic database adapter conformance tests
# ---------------------------------------------------------------------------


def get_generic_test_dir() -> Path:
    """Return the path to the generic database adapter conformance tests.

    These tests can be run against any database provider to verify it
    correctly implements the required capabilities.  Use this path with
    ``pytest`` or pass it to ``protean test test-adapter``.

    Returns:
        Path to the ``tests/adapters/repository/generic/`` directory.

    Raises:
        FileNotFoundError: If the generic test directory is not available
            (e.g. when Protean is installed from a wheel rather than a
            source checkout).

    Example::

        from protean.testing import get_generic_test_dir

        # In an external adapter's conftest.py or test runner
        generic_dir = get_generic_test_dir()
        # Pass to pytest: pytest.main([str(generic_dir), "--db=MY_ADAPTER"])
    """
    # Relative to this file: src/protean/testing.py
    # Tests live at: <repo>/tests/adapters/repository/generic/
    candidate = Path(__file__).resolve().parent.parent.parent / (
        "tests/adapters/repository/generic"
    )
    if candidate.is_dir():
        return candidate

    raise FileNotFoundError(
        "Generic database conformance tests not found. "
        "This is expected when Protean is installed from a wheel. "
        "To run conformance tests, install Protean from source: "
        "pip install -e 'protean[dev]' or use a source checkout."
    )


# ---------------------------------------------------------------------------
# Invariant testing helpers (deprecated)
# ---------------------------------------------------------------------------
#
# These were removed in 0.16.0 without a deprecation cycle, breaking downstream
# test suites at import time. They are restored here as deprecated shims so the
# 0.16.0 removal honours the breaking-change policy (ADR-0004: minimum two
# minor versions). Prefer ``pytest.raises(ValidationError, match=...)``. See
# #1011.


def assert_invalid(
    operation: Callable[[], Any],
    *,
    message: str | None = None,
) -> ValidationError:
    """Assert that an operation raises a ``ValidationError``.

    .. deprecated:: 0.16.1
        Use ``pytest.raises(ValidationError, match=...)`` instead. Will be
        removed in v0.18.0.

    Args:
        operation: A callable (typically a lambda) wrapping the code that
            should fail validation.
        message: If provided, asserts that this string appears in at least one
            of the flattened validation error messages.

    Returns:
        The caught ``ValidationError`` for further assertions.
    """
    warnings.warn(
        "assert_invalid() is deprecated. Use "
        "pytest.raises(ValidationError, match=...) instead. "
        "Will be removed in v0.18.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        operation()
    except ValidationError as exc:
        if message is not None:
            flat_messages = _flatten_messages(exc.messages)
            if not any(message in m for m in flat_messages):
                raise AssertionError(
                    f"Expected validation message containing {message!r}, "
                    f"got: {flat_messages}"
                ) from None
        return exc

    raise AssertionError("Expected ValidationError but no exception was raised")


def assert_valid(operation: Callable[[], Any]) -> Any:
    """Assert that an operation completes without raising a ``ValidationError``.

    .. deprecated:: 0.16.1
        Call the operation directly instead. Will be removed in v0.18.0.

    Args:
        operation: A callable (typically a lambda) wrapping the code that
            should pass validation.

    Returns:
        The return value of the operation.
    """
    warnings.warn(
        "assert_valid() is deprecated. Call the operation directly instead. "
        "Will be removed in v0.18.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        return operation()
    except ValidationError as exc:
        flat_messages = _flatten_messages(exc.messages)
        raise AssertionError(
            f"Expected no ValidationError but got: {flat_messages}"
        ) from exc
