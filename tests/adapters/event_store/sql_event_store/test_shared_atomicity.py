"""A store that shares ``default`` commits and rolls back with the Unit of Work.

A command handler saves an event-sourced aggregate, saves a state-based
aggregate whose events go to the outbox, and sends a command for later. A
raise in the handler leaves no row in any of the tables.
"""

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from protean import Domain
from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Boolean, Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle

from .conftest import BACKENDS, row_count

notified: list[str] = []


class Opened(BaseEvent):
    account_id = Identifier(required=True)


class Account(BaseAggregate):
    name = String()

    @apply
    def on_opened(self, event: Opened) -> None:
        self.id = event.account_id


class Invoiced(BaseEvent):
    invoice_id = Identifier(required=True)


class Invoice(BaseAggregate):
    number = String()


class Open(BaseCommand):
    account_id = Identifier(required=True)
    fail = Boolean(default=False)


class Notify(BaseCommand):
    account_id = Identifier(required=True)


class AccountHandler(BaseCommandHandler):
    @handle(Open)
    def open(self, command: Open) -> None:
        account = Account(id=command.account_id)
        account.raise_(Opened(account_id=command.account_id))
        current_domain.repository_for(Account).add(account)

        invoice = Invoice(number="1")
        invoice.raise_(Invoiced(invoice_id=invoice.id))
        current_domain.repository_for(Invoice).add(invoice)

        current_domain.process(Notify(account_id=command.account_id), asynchronous=True)
        if command.fail:
            raise RuntimeError("the handler fails after every write")


class NotifyHandler(BaseCommandHandler):
    @handle(Notify)
    def notify(self, command: Notify) -> None:
        notified.append(command.account_id)


def register(domain: Domain) -> None:
    domain.register(Account, event_sourced=True)
    domain.register(Opened, part_of=Account)
    domain.register(Open, part_of=Account)
    domain.register(Notify, part_of=Account)
    domain.register(AccountHandler, part_of=Account)
    domain.register(NotifyHandler, part_of=Account)
    domain.register(Invoice)
    domain.register(Invoiced, part_of=Invoice)


# Stream subscriptions turn the outbox on.
STREAM = {"default_subscription_type": "stream"}


def counts(domain: Domain) -> dict[str, int]:
    return {
        table: row_count(domain, table) for table in ("messages", "invoice", "outbox")
    }


@pytest.fixture(autouse=True)
def reset_notified():
    notified.clear()


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("processing", ["sync", "async"])
class TestAHandlerCommitsOrRollsBackEveryWrite:
    def test_a_raise_leaves_no_row_in_any_table(self, make_shared_domain, processing):
        domain = make_shared_domain(
            register, command_processing=processing, server=STREAM
        )

        with pytest.raises(RuntimeError, match="the handler fails"):
            AccountHandler().open(Open(account_id="a1", fail=True))

        assert counts(domain) == {"messages": 0, "invoice": 0, "outbox": 0}
        assert notified == []

    def test_without_the_raise_every_write_commits(
        self, make_shared_domain, processing
    ):
        domain = make_shared_domain(
            register, command_processing=processing, server=STREAM
        )

        AccountHandler().open(Open(account_id="a1"))

        result = counts(domain)
        assert result["invoice"] == 1
        assert result["outbox"] >= 1
        store = domain.event_store._require_adapter()
        types = [row["type"] for row in store.get_all_messages()]
        assert any(t.endswith("Opened.v1") for t in types)
        assert any(t.endswith("Notify.v1") for t in types)
        # The sync processor runs the deferred command after the commit.
        assert notified == (["a1"] if processing == "sync" else [])


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
class TestAnOwnDatabaseStoreWritesAtOnce:
    def test_a_raise_keeps_the_rows_the_store_wrote(self, make_shared_domain, tmp_path):
        domain = make_shared_domain(
            register,
            command_processing="async",
            event_store={
                "provider": "sql",
                "database_uri": f"sqlite:///{tmp_path / 'own.db'}",
            },
        )
        store = domain.event_store._require_adapter()

        with pytest.raises(RuntimeError, match="the handler fails"):
            AccountHandler().open(Open(account_id="a1", fail=True))

        types = [row["type"] for row in store.get_all_messages()]
        assert any(t.endswith("Notify.v1") for t in types)
        assert row_count(domain, "invoice") == 0

    def test_an_append_inside_a_unit_of_work_returns_its_position(
        self, make_shared_domain, tmp_path
    ):
        make_shared_domain(
            event_store={
                "provider": "sql",
                "database_uri": f"sqlite:///{tmp_path / 'own.db'}",
            },
        )
        store = current_domain.event_store._require_adapter()

        with UnitOfWork():
            assert store.write_message("user-1", "Registered", {}) == 0
            assert len(store.get_stream_messages("user-1")) == 1


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
class TestANestedUnitOfWork:
    def test_a_nested_append_commits_with_the_outermost(self, make_shared_domain):
        store = make_shared_domain().event_store._require_adapter()

        with UnitOfWork():
            with UnitOfWork():
                assert store.write_message("user-1", "Registered", {}) is None
            assert store.get_stream_messages("user-1") == []

        assert len(store.get_stream_messages("user-1")) == 1

    def test_a_nested_failure_discards_the_append(self, make_shared_domain):
        store = make_shared_domain().event_store._require_adapter()

        with pytest.raises(RuntimeError, match="the nested block fails"):
            with UnitOfWork():
                with UnitOfWork():
                    store.write_message("user-1", "Registered", {})
                    raise RuntimeError("the nested block fails")

        assert store.get_stream_messages("user-1") == []

    def test_an_append_outside_a_unit_of_work_returns_its_position(
        self, make_shared_domain
    ):
        store = make_shared_domain().event_store._require_adapter()

        assert store.write_message("user-1", "Registered", {}) == 0


def append_spans(exporter: InMemorySpanExporter) -> list[ReadableSpan]:
    spans = [
        span
        for span in exporter.get_finished_spans()
        if span.name == "protean.event_store.append"
    ]
    assert spans != []
    return spans


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
class TestTheAppendSpan:
    @pytest.fixture
    def exporter(self, make_shared_domain) -> InMemorySpanExporter:
        domain = make_shared_domain(register, command_processing="async")
        exporter = InMemorySpanExporter()
        tracer_provider = SDKTracerProvider()
        tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
        domain._otel_tracer_provider = tracer_provider
        domain._otel_init_attempted = True
        return exporter

    def test_a_held_append_sets_no_position(self, exporter):
        with UnitOfWork():
            current_domain.process(Notify(account_id="a1"), asynchronous=True)

        for span in append_spans(exporter):
            assert "protean.event_store.position" not in span.attributes

    def test_an_append_outside_sets_the_position(self, exporter):
        current_domain.process(Notify(account_id="a1"), asynchronous=True)

        positions = [
            span.attributes["protean.event_store.position"]
            for span in append_spans(exporter)
        ]
        assert positions == [0]
