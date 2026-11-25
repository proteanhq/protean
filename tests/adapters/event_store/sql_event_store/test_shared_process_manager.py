"""A process manager on a shared store stores its transition and its commands
only when its handler's Unit of Work commits."""

from pathlib import Path
from uuid import uuid4

import pytest

from protean import Domain
from protean.adapters.event_store.sql.store import SqlEventStore
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.process_manager import BaseProcessManager
from protean.exceptions import ExpectedVersionError
from protean.fields import Boolean, Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle
from tests.shared import POSTGRES_URI

from .conftest import BACKENDS, PG_SCHEMA, row_count

# Runs inside the handler, before the commit, when a test sets it.
during_handler: list = []


class Order(BaseAggregate):
    status = String(default="new")


class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    fail = Boolean(default=False)


class Reserve(BaseCommand):
    order_id = Identifier(required=True)


class Fulfilment(BaseProcessManager):
    order_id = Identifier()
    status = String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.status = "reserving"
        current_domain.process(Reserve(order_id=event.order_id), asynchronous=True)
        for action in during_handler:
            action(event)
        if event.fail:
            raise RuntimeError("the process manager fails")


def register(domain: Domain) -> None:
    domain.register(Order)
    domain.register(OrderPlaced, part_of=Order)
    domain.register(Reserve, part_of=Order)
    domain.register(Fulfilment, stream_categories=["shared0::order"])


def transition_stream(order_id: str) -> str:
    return f"{Fulfilment.meta_.stream_category}-{order_id}"


@pytest.fixture(autouse=True)
def reset_actions():
    during_handler.clear()
    yield
    during_handler.clear()


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
class TestTheTransitionCommitsWithTheHandler:
    @pytest.fixture
    def domain(self, make_shared_domain) -> Domain:
        return make_shared_domain(register, command_processing="async")

    def test_a_raising_handler_stores_neither_transition_nor_command(self, domain):
        order_id = str(uuid4())

        with pytest.raises(RuntimeError, match="the process manager fails"):
            Fulfilment._handle(OrderPlaced(order_id=order_id, fail=True))

        assert row_count(domain, "messages") == 0

    def test_the_handler_stores_the_transition_and_the_command(self, domain):
        order_id = str(uuid4())

        Fulfilment._handle(OrderPlaced(order_id=order_id))

        store = domain.event_store._require_adapter()
        assert len(store.get_stream_messages(transition_stream(order_id))) == 1
        types = [row["type"] for row in store.get_all_messages()]
        assert any(t.endswith("Reserve.v1") for t in types)

    def test_another_writer_on_the_stream_fails_the_commit(
        self, domain, backend, tmp_path: Path
    ):
        order_id = str(uuid4())
        config = (
            {"provider": "sql", "database_uri": f"sqlite:///{tmp_path / 'shared.db'}"}
            if backend == "sqlite"
            else {"provider": "sql", "database_uri": POSTGRES_URI, "schema": PG_SCHEMA}
        )
        other = SqlEventStore("other", domain, config)
        positions: list[int | None] = []

        def write_first(event: OrderPlaced) -> None:
            positions.append(
                other.write_message(transition_stream(event.order_id), "Other", {})
            )

        during_handler.append(write_first)
        try:
            with pytest.raises(ExpectedVersionError):
                Fulfilment._handle(OrderPlaced(order_id=order_id))
        finally:
            other.close()

        assert positions == [0]
        # Only the other writer's row is stored. The command and the
        # transition rolled back with the Unit of Work.
        store = domain.event_store._require_adapter()
        assert [row["type"] for row in store.get_all_messages()] == ["Other"]
