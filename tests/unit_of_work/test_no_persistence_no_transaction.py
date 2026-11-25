"""A handler invocation that touches no repository opens no transaction.

ADR-0031 lets a handler method talk to an external system by putting it in its
own method, and that only costs wall-clock time because such a method never
opens a session. The Unit of Work is lazy: ``start()`` opens nothing, and the
session (on SQLAlchemy the real ``BEGIN``) appears at the first repository
access.

That behaviour is load-bearing rather than incidental. An eager session anywhere
in the start path would silently make every call-out handler hold a pooled
connection for the length of its external call, and nothing else in the suite
would notice.

The contract is about repository access **during the invocation**, not about
what the handler body does: an ``idempotent=True`` handler reads its marker
before the body runs, and that read opens a session regardless.

A sql event store that shares the ``default`` database amends this. A method
that sends a command asynchronously reaches no repository, so its body still
runs with no session. The store holds the command and writes it in the Unit of
Work's transaction, so the method opens its transaction at commit, after its
body returns.
"""

import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Identifier, String
from protean.utils.globals import _uow_context_stack, current_domain
from protean.utils.mixins import handle
from tests.shared import provider_adapter

observed: dict[str, list[str]] = {}
# The pooled connections checked out while a handler body runs.
checked_out: list[int] = []


def _record(label: str) -> None:
    """Snapshot the sessions open on the active Unit of Work.

    Asserts a UoW is actually active, so "a UoW is open with no session" cannot
    be confused with "no UoW ran at all", which is the distinction under test.
    """
    top = _uow_context_stack.top
    assert top is not None, "expected a wrapping UnitOfWork"
    observed[label] = list(top._sessions)


class Order(BaseAggregate):
    name: String()


class Placed(BaseEvent):
    order_id: Identifier()


class Ship(BaseCommand):
    order_id: Identifier()


class Reactions(BaseEventHandler):
    @handle(Placed)
    def calls_out(self, event: Placed) -> None:
        # Stands in for an HTTP call: no repository access at all.
        _record("calls_out")

    @handle(Placed)
    def persists(self, event: Placed) -> None:
        repo = current_domain.repository_for(Order)
        repo.add(Order(name="o"))
        _record("persists")

    @handle(Placed)
    def sends(self, event: Placed) -> None:
        current_domain.process(Ship(order_id=event.order_id), asynchronous=True)
        _record("sends")
        pool = provider_adapter(current_domain, "default")._engine.pool
        checked_out.append(pool.checkedout())


@pytest.fixture(autouse=True)
def registered(test_domain):
    observed.clear()
    checked_out.clear()
    if test_domain is None:
        # The SQLite class carries `no_test_domain` and builds its own domain.
        return None
    test_domain.register(Order)
    test_domain.register(Placed, part_of=Order)
    test_domain.register(Ship, part_of=Order)
    test_domain.register(Reactions, part_of=Order)
    test_domain.init(traverse=False)
    return test_domain


class TestNoRepositoryAccessOpensNoTransaction:
    def test_a_handler_method_that_persists_nothing_opens_no_session(self):
        Reactions._dispatch_handlers([Reactions.calls_out], Placed(order_id="1"))

        assert observed["calls_out"] == []

    def test_a_handler_method_that_persists_does_open_one(self):
        """The negative half: the guarantee is about repository access, so a
        method that does touch a repository must open a session. Without this,
        the test above would pass just as well if sessions never opened."""
        Reactions._dispatch_handlers([Reactions.persists], Placed(order_id="1"))

        assert observed["persists"] != []

    def test_the_unit_of_work_opens_nothing_on_entry(self):
        """`start()` is where an eager session would be introduced."""
        with UnitOfWork() as uow:
            assert uow._sessions == {}

    def test_a_session_appears_at_the_first_repository_access(self, test_domain):
        with UnitOfWork() as uow:
            assert uow._sessions == {}

            test_domain.repository_for(Order).add(Order(name="o"))

            assert uow._sessions != {}


@pytest.mark.sqlite
@pytest.mark.no_test_domain
class TestTheGuaranteeHoldsOnSQLAlchemyToo:
    """The memory provider has no real transaction, so the guarantee only means
    something once a provider that issues a real ``BEGIN`` is under it."""

    @pytest.fixture
    def sqlite_domain(self, tmp_path):
        domain = Domain(name="NoTxnSqlite")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": f"sqlite:///{tmp_path / 'notxn.db'}",
        }
        domain.register(Order)
        domain.register(Placed, part_of=Order)
        domain.init(traverse=False)
        with domain.domain_context():
            provider_adapter(domain, "default").create_schema()
            yield domain

    def test_no_pooled_connection_until_a_repository_is_touched(self, sqlite_domain):
        """Assert the pool directly, not ``_sessions``. The contract the
        changelog ships is "holds no pooled connection", and the two coincide
        only because ``_initialize_session`` is the sole place a connection is
        checked out today. A warm-up or health probe on ``start()`` would leave
        ``_sessions`` empty while checking a connection out, so the pool is what
        the guarantee is actually about."""
        pool = provider_adapter(sqlite_domain, "default")._engine.pool

        with UnitOfWork():
            assert pool.checkedout() == 0

            sqlite_domain.repository_for(Order).add(Order(name="o"))

            assert pool.checkedout() == 1


@pytest.mark.sqlite
@pytest.mark.no_test_domain
class TestASharedSqlEventStoreOpensTheTransactionAtCommit:
    @pytest.fixture
    def shared_domain(self, tmp_path):
        domain = Domain(name="NoTxnShared")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": f"sqlite:///{tmp_path / 'shared.db'}",
        }
        domain.config["event_store"] = {"provider": "sql"}
        domain.config["command_processing"] = "async"
        domain.register(Order)
        domain.register(Placed, part_of=Order)
        domain.register(Ship, part_of=Order)
        domain.register(Reactions, part_of=Order)
        domain.init(traverse=False)
        with domain.domain_context():
            provider_adapter(domain, "default").create_schema()
            domain.event_store._require_adapter().create_schema()
            yield domain
            domain.event_store._require_adapter().close()
            provider_adapter(domain, "default").close()

    def test_the_body_runs_with_no_session_and_the_command_commits(self, shared_domain):
        Reactions._dispatch_handlers([Reactions.sends], Placed(order_id="1"))

        assert observed["sends"] == []
        assert checked_out == [0]
        store = shared_domain.event_store._require_adapter()
        types = [row["type"] for row in store.get_all_messages()]
        assert len(types) == 1
        assert types[0].endswith("Ship.v1")
