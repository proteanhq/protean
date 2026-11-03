"""Tests for OpenTelemetry span instrumentation on command processing,
handler dispatch, and query dispatch.

Verifies that:
- ``CommandProcessor.process()`` emits a ``protean.command.process`` span
  with the correct attributes (command type, id, stream, correlation_id).
- ``CommandProcessor.enrich()`` emits a child ``protean.command.enrich``
  span nested under the process span.
- ``HandlerMixin._handle()`` emits a ``protean.handler.execute`` span
  with handler name, type, and correlation/causation IDs.
- ``UnitOfWork.commit()`` emits a ``protean.uow.commit`` span with
  correlation_id.
- ``QueryProcessor.dispatch()`` emits a ``protean.query.dispatch`` span.
- Errors in handlers record exceptions and set ERROR status on spans.
- Parent-child span relationships are correct.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.exceptions import IncorrectUsageError
from protean.fields import Float, Identifier, String
from protean.utils.eventing import Message
from protean.utils.globals import current_domain, g
from protean.utils.mixins import handle, read

# ---------------------------------------------------------------------------
# Domain elements for testing
# ---------------------------------------------------------------------------


class Account(BaseAggregate):
    account_id = Identifier(identifier=True)
    name = String(required=True)


class OpenAccount(BaseCommand):
    account_id = Identifier(identifier=True)
    name = String(required=True)


class AccountCommandHandler(BaseCommandHandler):
    @handle(OpenAccount)
    def open(self, command: OpenAccount):
        account = Account(account_id=command.account_id, name=command.name)
        current_domain.repository_for(Account).add(account)
        return {"opened": command.account_id}


class FailingCommand(BaseCommand):
    account_id = Identifier(identifier=True)


class FailingCommandHandler(BaseCommandHandler):
    @handle(FailingCommand)
    def fail(self, command: FailingCommand):
        raise RuntimeError("handler exploded")


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    total_amount = Float()


class GetOrdersByCustomer(BaseQuery):
    customer_id = Identifier(required=True)


class OrderSummaryQueryHandler(BaseQueryHandler):
    @read(GetOrdersByCustomer)
    def get_by_customer(self, query: GetOrdersByCustomer):
        return [
            {
                "order_id": "order-1",
                "customer_id": query.customer_id,
                "status": "shipped",
            },
            {
                "order_id": "order-2",
                "customer_id": query.customer_id,
                "status": "pending",
            },
        ]


# Event-sourced aggregate elements for testing
class WalletOpened(BaseEvent):
    wallet_id = Identifier(identifier=True)
    owner = String(required=True)


class Wallet(BaseAggregate):
    wallet_id = Identifier(identifier=True)
    owner = String(required=True)

    @classmethod
    def open(cls, wallet_id: str, owner: str) -> "Wallet":
        wallet = cls(wallet_id=wallet_id, owner=owner)
        wallet.raise_(WalletOpened(wallet_id=wallet_id, owner=owner))
        return wallet

    @apply
    def on_wallet_opened(self, event: WalletOpened) -> None:
        self.owner = event.owner


class OpenWallet(BaseCommand):
    wallet_id = Identifier(identifier=True)
    owner = String(required=True)


class WalletCommandHandler(BaseCommandHandler):
    @handle(OpenWallet)
    def open_wallet(self, command: OpenWallet):
        wallet = Wallet.open(wallet_id=command.wallet_id, owner=command.owner)
        current_domain.repository_for(Wallet).add(wallet)
        return {"opened": command.wallet_id}


class AccountOpened(BaseEvent):
    account_id = Identifier(identifier=True)
    name = String(required=True)


class AccountWithEvent(BaseAggregate):
    account_id = Identifier(identifier=True)
    name = String(required=True)


class OpenAccountWithEvent(BaseCommand):
    account_id = Identifier(identifier=True)
    name = String(required=True)


class AccountWithEventHandler(BaseCommandHandler):
    @handle(OpenAccountWithEvent)
    def open(self, command: OpenAccountWithEvent):
        acct = AccountWithEvent(account_id=command.account_id, name=command.name)
        acct.raise_(AccountOpened(account_id=command.account_id, name=command.name))
        current_domain.repository_for(AccountWithEvent).add(acct)
        return {"opened": command.account_id}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _init_telemetry_in_memory(domain):
    """Set up in-memory OTEL exporters on the domain for testing."""
    service_name = domain.normalized_name
    resource = Resource.create({"service.name": service_name})

    span_exporter = InMemorySpanExporter()
    tracer_provider = SDKTracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    metric_reader = InMemoryMetricReader()
    meter_provider = SDKMeterProvider(resource=resource, metric_readers=[metric_reader])

    domain._otel_tracer_provider = tracer_provider
    domain._otel_meter_provider = meter_provider
    domain._otel_init_attempted = True

    return span_exporter


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account)
    test_domain.register(OpenAccount, part_of=Account)
    test_domain.register(AccountCommandHandler, part_of=Account)
    test_domain.register(FailingCommand, part_of=Account)
    test_domain.register(FailingCommandHandler, part_of=Account)
    test_domain.register(OrderSummary)
    test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
    test_domain.register(OrderSummaryQueryHandler, part_of=OrderSummary)
    test_domain.register(Wallet, event_sourced=True)
    test_domain.register(WalletOpened, part_of=Wallet)
    test_domain.register(OpenWallet, part_of=Wallet)
    test_domain.register(WalletCommandHandler, part_of=Wallet)
    test_domain.register(AccountWithEvent)
    test_domain.register(AccountOpened, part_of=AccountWithEvent)
    test_domain.register(OpenAccountWithEvent, part_of=AccountWithEvent)
    test_domain.register(AccountWithEventHandler, part_of=AccountWithEvent)
    test_domain.init(traverse=False)


@pytest.fixture()
def span_exporter(test_domain):
    """Enable in-memory OTEL and return the span exporter."""
    return _init_telemetry_in_memory(test_domain)


def _process_open_account(domain, **kwargs):
    domain.process(
        OpenAccount(account_id=str(uuid4()), name="Acme"),
        asynchronous=False,
        **kwargs,
    )


def _span(spans, name):
    return next(s for s in spans if s.name == name)


# ---------------------------------------------------------------------------
# Tests: Command processing spans
# ---------------------------------------------------------------------------


class TestCommandProcessSpan:
    """CommandProcessor.process() emits ``protean.command.process``."""

    def test_process_span_carries_command_attributes(self, test_domain, span_exporter):
        acct_id = str(uuid4())
        test_domain.process(
            OpenAccount(account_id=acct_id, name="Acme"),
            asynchronous=False,
        )

        process_span = _span(
            span_exporter.get_finished_spans(), "protean.command.process"
        )
        assert process_span.attributes["protean.command.type"] == OpenAccount.__type__
        assert process_span.attributes["protean.command.id"] == acct_id
        assert process_span.attributes["protean.stream"] != ""
        assert process_span.attributes["protean.correlation_id"] != ""


# ---------------------------------------------------------------------------
# Tests: Enrich child span
# ---------------------------------------------------------------------------


class TestCommandEnrichSpan:
    """CommandProcessor.enrich() emits a child ``protean.command.enrich``."""

    def test_enrich_span_is_child_of_process_with_command_type(
        self, test_domain, span_exporter
    ):
        _process_open_account(test_domain)

        spans = span_exporter.get_finished_spans()
        process_span = _span(spans, "protean.command.process")
        enrich_span = _span(spans, "protean.command.enrich")

        assert enrich_span.parent is not None
        assert enrich_span.parent.span_id == process_span.context.span_id
        assert enrich_span.attributes["protean.command.type"] == OpenAccount.__type__


# ---------------------------------------------------------------------------
# Tests: Handler execution span
# ---------------------------------------------------------------------------


class TestHandlerExecuteSpan:
    """HandlerMixin._handle() emits ``protean.handler.execute``."""

    def test_handler_span_is_child_of_process_with_handler_attributes(
        self, test_domain, span_exporter
    ):
        _process_open_account(test_domain)

        spans = span_exporter.get_finished_spans()
        process_span = _span(spans, "protean.command.process")
        handler_span = _span(spans, "protean.handler.execute")

        assert (
            handler_span.attributes["protean.handler.name"] == "AccountCommandHandler"
        )
        assert handler_span.attributes["protean.handler.type"] == "COMMAND_HANDLER"
        assert handler_span.parent is not None
        assert handler_span.parent.span_id == process_span.context.span_id


# ---------------------------------------------------------------------------
# Tests: Error spans
# ---------------------------------------------------------------------------


class TestErrorSpans:
    """Errors in handlers record exceptions and set ERROR status on spans."""

    @pytest.mark.parametrize(
        "span_name", ["protean.command.process", "protean.handler.execute"]
    )
    def test_error_and_exception_event_recorded_on_span(
        self, test_domain, span_exporter, span_name
    ):
        with pytest.raises(RuntimeError, match="handler exploded"):
            test_domain.process(
                FailingCommand(account_id=str(uuid4())),
                asynchronous=False,
            )

        span = _span(span_exporter.get_finished_spans(), span_name)

        assert span.status.status_code == StatusCode.ERROR
        assert "handler exploded" in span.status.description
        # OTEL records exceptions as span events
        exception_events = [e for e in span.events if e.name == "exception"]
        assert len(exception_events) == 1
        assert "handler exploded" in exception_events[0].attributes["exception.message"]


# ---------------------------------------------------------------------------
# Tests: Query dispatch spans
# ---------------------------------------------------------------------------


class TestQueryDispatchSpan:
    """QueryProcessor.dispatch() emits ``protean.query.dispatch``."""

    def test_query_dispatch_span_wraps_query_handler_span(
        self, test_domain, span_exporter
    ):
        test_domain.dispatch(GetOrdersByCustomer(customer_id="cust-42"))

        spans = span_exporter.get_finished_spans()
        query_span = _span(spans, "protean.query.dispatch")
        handler_span = _span(spans, "protean.handler.execute")

        assert (
            query_span.attributes["protean.query.type"] == GetOrdersByCustomer.__type__
        )
        assert (
            query_span.attributes["protean.handler.name"] == "OrderSummaryQueryHandler"
        )
        assert handler_span.attributes["protean.handler.type"] == "QUERY_HANDLER"
        assert handler_span.parent is not None
        assert handler_span.parent.span_id == query_span.context.span_id


# ---------------------------------------------------------------------------
# Tests: No-op when telemetry not enabled
# ---------------------------------------------------------------------------


class TestNoOpWhenDisabled:
    """When telemetry is not enabled, processing should work without spans."""

    def test_failing_handler_propagates_without_telemetry(self, test_domain):
        with pytest.raises(RuntimeError, match="handler exploded"):
            test_domain.process(
                FailingCommand(account_id=str(uuid4())),
                asynchronous=False,
            )


# ---------------------------------------------------------------------------
# Tests: UnitOfWork commit span
# ---------------------------------------------------------------------------


class TestUoWCommitSpan:
    """UnitOfWork.commit() emits ``protean.uow.commit``."""

    def test_uow_commit_span_has_counts_and_shares_handler_trace(
        self, test_domain, span_exporter
    ):
        _process_open_account(test_domain)

        spans = span_exporter.get_finished_spans()
        handler_span = _span(spans, "protean.handler.execute")
        uow_span = _span(spans, "protean.uow.commit")

        assert uow_span.attributes["protean.uow.event_count"] >= 0
        assert uow_span.attributes["protean.uow.session_count"] >= 0
        # UoW commit is a descendant of handler (parent chain goes through repository.add)
        assert uow_span.parent is not None
        assert uow_span.context.trace_id == handler_span.context.trace_id


class TestUoWCommitSpanOnError:
    """UoW commit span records errors when commit fails."""

    def test_uow_commit_span_records_error_on_failure(
        self, test_domain, span_exporter, monkeypatch
    ):
        """Force a commit failure during event store append and verify
        the UoW commit span is marked ERROR with an exception event."""
        store = test_domain.event_store.store
        original_write = store._write
        call_count = 0

        def _exploding_write(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Let command append succeed (call 1), fail on event append (call 2+)
            if call_count > 1:
                raise RuntimeError("event store exploded")
            return original_write(*args, **kwargs)

        monkeypatch.setattr(store, "_write", _exploding_write)

        with pytest.raises(Exception):
            test_domain.process(
                OpenAccountWithEvent(account_id=str(uuid4()), name="Acme"),
                asynchronous=False,
            )

        spans = span_exporter.get_finished_spans()
        uow_spans = [s for s in spans if s.name == "protean.uow.commit"]
        assert len(uow_spans) >= 1

        # Find the UoW commit span that recorded the error
        # (there may be an earlier internal UoW span from the memory adapter)
        error_spans = [s for s in uow_spans if s.status.status_code == StatusCode.ERROR]
        assert len(error_spans) == 1

        uow_span = error_spans[0]
        assert len(uow_span.events) > 0
        exception_event = next(e for e in uow_span.events if e.name == "exception")
        assert "event store exploded" in exception_event.attributes["exception.message"]


# ---------------------------------------------------------------------------
# Tests: Repository spans
# ---------------------------------------------------------------------------


class TestRepositoryAddSpan:
    """BaseRepository.add() emits ``protean.repository.add``."""

    def test_repository_add_span_is_child_of_handler(self, test_domain, span_exporter):
        _process_open_account(test_domain)

        spans = span_exporter.get_finished_spans()
        handler_span = _span(spans, "protean.handler.execute")
        account_add = next(
            s
            for s in spans
            if s.name == "protean.repository.add"
            and s.attributes.get("protean.aggregate.type") == "Account"
        )

        assert "protean.provider" in account_add.attributes
        assert account_add.parent is not None
        assert account_add.parent.span_id == handler_span.context.span_id


class TestRepositoryGetSpan:
    """BaseRepository.get() emits ``protean.repository.get``."""

    def test_repository_get_span_has_aggregate_type_and_provider(
        self, test_domain, span_exporter
    ):
        acct_id = str(uuid4())
        test_domain.process(
            OpenAccount(account_id=acct_id, name="Acme"),
            asynchronous=False,
        )
        span_exporter.clear()

        test_domain.repository_for(Account).get(acct_id)

        get_span = _span(span_exporter.get_finished_spans(), "protean.repository.get")
        assert get_span.attributes["protean.aggregate.type"] == "Account"
        assert "protean.provider" in get_span.attributes


# ---------------------------------------------------------------------------
# Tests: Event store append span
# ---------------------------------------------------------------------------


class TestEventStoreAppendSpan:
    """BaseEventStore.append() emits ``protean.event_store.append``."""

    def test_event_store_append_span_attributes_and_trace(
        self, test_domain, span_exporter
    ):
        _process_open_account(test_domain)

        spans = span_exporter.get_finished_spans()
        process_span = _span(spans, "protean.command.process")
        append_span = _span(spans, "protean.event_store.append")

        assert append_span.attributes["protean.event_store.stream"] != ""
        assert "protean.event_store.message_type" in append_span.attributes
        assert "protean.event_store.position" in append_span.attributes
        # event_store.append is part of the same trace
        assert append_span.parent is not None
        assert append_span.context.trace_id == process_span.context.trace_id


# ---------------------------------------------------------------------------
# Tests: Full span tree
# ---------------------------------------------------------------------------


class TestSpanTree:
    """Verify the full span tree during command processing."""

    def test_full_span_tree_with_infrastructure(self, test_domain, span_exporter):
        """process → enrich + handler.execute → repository.add + uow.commit → event_store.append."""
        _process_open_account(test_domain)

        spans = span_exporter.get_finished_spans()
        span_names = {s.name for s in spans}

        assert {
            "protean.command.process",
            "protean.command.enrich",
            "protean.handler.execute",
            "protean.repository.add",
            "protean.uow.commit",
            "protean.event_store.append",
        } <= span_names

        # All spans share the same trace ID
        assert len({s.context.trace_id for s in spans}) == 1

        # Enrich and handler are children of process
        process_span = _span(spans, "protean.command.process")
        assert (
            _span(spans, "protean.command.enrich").parent.span_id
            == process_span.context.span_id
        )
        assert (
            _span(spans, "protean.handler.execute").parent.span_id
            == process_span.context.span_id
        )

    def test_es_full_span_tree(self, test_domain, span_exporter):
        test_domain.process(
            OpenWallet(wallet_id=str(uuid4()), owner="Alice"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        span_names = {s.name for s in spans}

        assert {
            "protean.command.process",
            "protean.handler.execute",
            "protean.repository.add",
            "protean.uow.commit",
            "protean.event_store.append",
        } <= span_names
        assert len({s.context.trace_id for s in spans}) == 1


# ---------------------------------------------------------------------------
# Tests: Event-sourced repository spans
# ---------------------------------------------------------------------------


def _event_sourced_span(spans, name):
    return next(
        s
        for s in spans
        if s.name == name
        and s.attributes.get("protean.repository.kind") == "event_sourced"
    )


class TestEventSourcedRepositoryAddSpan:
    """BaseEventSourcedRepository.add() emits ``protean.repository.add``."""

    def test_es_repository_add_span_attributes(self, test_domain, span_exporter):
        test_domain.process(
            OpenWallet(wallet_id=str(uuid4()), owner="Alice"),
            asynchronous=False,
        )

        add_span = _event_sourced_span(
            span_exporter.get_finished_spans(), "protean.repository.add"
        )
        assert add_span.attributes["protean.aggregate.type"] == "Wallet"
        assert "protean.provider" in add_span.attributes


class TestEventSourcedRepositoryGetSpan:
    """BaseEventSourcedRepository.get() emits ``protean.repository.get``."""

    def test_es_repository_get_span_attributes(self, test_domain, span_exporter):
        wallet_id = str(uuid4())
        test_domain.process(
            OpenWallet(wallet_id=wallet_id, owner="Alice"),
            asynchronous=False,
        )
        span_exporter.clear()

        test_domain.repository_for(Wallet).get(wallet_id)

        get_span = _event_sourced_span(
            span_exporter.get_finished_spans(), "protean.repository.get"
        )
        assert get_span.attributes["protean.aggregate.type"] == "Wallet"
        assert "protean.provider" in get_span.attributes


class TestEventSourcedRepositoryGetOrNoneSpan:
    """BaseEventSourcedRepository.get_or_none() emits ``protean.repository.get_or_none``."""

    def test_hit_emits_one_span_and_no_get_span(self, test_domain, span_exporter):
        wallet_id = str(uuid4())
        test_domain.process(
            OpenWallet(wallet_id=wallet_id, owner="Alice"),
            asynchronous=False,
        )
        span_exporter.clear()

        wallet = test_domain.repository_for(Wallet).get_or_none(wallet_id)
        assert wallet is not None

        spans = span_exporter.get_finished_spans()
        get_or_none_spans = [
            s for s in spans if s.name == "protean.repository.get_or_none"
        ]
        assert len(get_or_none_spans) == 1
        span = get_or_none_spans[0]
        assert span.attributes["protean.repository.kind"] == "event_sourced"
        assert span.attributes["protean.aggregate.type"] == "Wallet"
        assert "protean.provider" in span.attributes
        assert not [s for s in spans if s.name == "protean.repository.get"]

    def test_miss_does_not_mark_span_as_error(self, test_domain, span_exporter):
        span_exporter.clear()

        assert test_domain.repository_for(Wallet).get_or_none("missing") is None

        spans = span_exporter.get_finished_spans()
        get_or_none_spans = [
            s for s in spans if s.name == "protean.repository.get_or_none"
        ]
        assert len(get_or_none_spans) == 1
        assert get_or_none_spans[0].status.status_code == StatusCode.UNSET
        assert get_or_none_spans[0].events == ()

    def test_propagated_error_marks_span_as_error(self, test_domain, span_exporter):
        span_exporter.clear()

        with pytest.raises(IncorrectUsageError):
            test_domain.repository_for(Wallet).get_or_none(
                "missing", at_version=0, as_of=datetime.now(UTC)
            )

        spans = span_exporter.get_finished_spans()
        get_or_none_spans = [
            s for s in spans if s.name == "protean.repository.get_or_none"
        ]
        assert len(get_or_none_spans) == 1
        assert get_or_none_spans[0].status.status_code == StatusCode.ERROR


# ---------------------------------------------------------------------------
# Tests: Correlation/causation IDs on handler.execute and uow.commit spans
# ---------------------------------------------------------------------------


def _correlated_uow_span(spans):
    """Return the UoW commit span that has protean.correlation_id.

    There may be multiple UoW commit spans during command processing
    (e.g. one for event store command append, one for handler-level
    persistence). The handler-level UoW commit runs while
    g.message_in_context is set and therefore carries the correlation_id
    (and causation_id when present) attributes.
    """
    correlated = [
        s
        for s in spans
        if s.name == "protean.uow.commit" and "protean.correlation_id" in s.attributes
    ]
    assert len(correlated) >= 1, (
        "Expected at least one UoW commit span with protean.correlation_id"
    )
    return correlated[0]


class TestSpanCorrelationAttributes:
    """``protean.handler.execute`` and ``protean.uow.commit`` carry
    correlation_id and causation_id."""

    def test_explicit_correlation_id_on_handler_and_uow_spans(
        self, test_domain, span_exporter
    ):
        corr_id = "test-corr-123"
        _process_open_account(test_domain, correlation_id=corr_id)

        spans = span_exporter.get_finished_spans()
        handler_span = _span(spans, "protean.handler.execute")
        assert handler_span.attributes["protean.correlation_id"] == corr_id
        assert _correlated_uow_span(spans).attributes["protean.correlation_id"] == (
            corr_id
        )

    def test_root_command_spans_share_generated_correlation_and_omit_causation(
        self, test_domain, span_exporter
    ):
        """Without an explicit correlation_id, an auto-generated one appears on
        every span; a root command has no causation chain, so causation_id is
        absent."""
        _process_open_account(test_domain)

        spans = span_exporter.get_finished_spans()
        process_corr = _span(spans, "protean.command.process").attributes[
            "protean.correlation_id"
        ]
        for span in (
            _span(spans, "protean.handler.execute"),
            _correlated_uow_span(spans),
        ):
            assert span.attributes["protean.correlation_id"] != ""
            assert span.attributes["protean.correlation_id"] == process_corr
            assert "protean.causation_id" not in span.attributes

    def test_causation_id_from_parent_message_context(self, test_domain, span_exporter):
        """When a command is processed while a parent message is in context (as
        if dispatched from an event handler), both spans carry causation_id."""
        wallet = Wallet.open(wallet_id=str(uuid4()), owner="Alice")
        parent = Message.from_domain_object(wallet._events[0])
        parent_msg_id = parent.metadata.headers.id

        g.message_in_context = parent
        try:
            _process_open_account(test_domain)
        finally:
            g.pop("message_in_context", None)

        spans = span_exporter.get_finished_spans()
        handler_span = _span(spans, "protean.handler.execute")
        assert handler_span.attributes["protean.causation_id"] == parent_msg_id
        # The handler-level UoW runs while g.message_in_context has the enriched
        # command (which inherits causation_id from the parent context).
        causation_spans = [
            s
            for s in spans
            if s.name == "protean.uow.commit" and "protean.causation_id" in s.attributes
        ]
        assert len(causation_spans) >= 1
        assert causation_spans[0].attributes["protean.causation_id"] == parent_msg_id
