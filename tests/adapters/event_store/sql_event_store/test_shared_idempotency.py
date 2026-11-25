"""An idempotency key for a command a shared store holds is recorded only when
the Unit of Work commits.

Requires a running Redis and the ``--redis`` flag. The redis leg also passes
``--postgresql``, so the shared store runs on PostgreSQL here.
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Identifier
from protean.utils.globals import current_domain
from protean.utils.mixins import handle
from tests.shared import REDIS_URI, provider_adapter

from .conftest import row_count

REDIS_IDEMPOTENCY_URL = f"{REDIS_URI}/6"

pytestmark = [pytest.mark.redis, pytest.mark.no_test_domain]


class Account(BaseAggregate):
    pass


class Notify(BaseCommand):
    account_id = Identifier(required=True)


class Open(BaseCommand):
    account_id = Identifier(required=True)


# What ``send`` returned inside ``AccountHandler.open``.
returned: list[int | None] = []


class NotifyHandler(BaseCommandHandler):
    @handle(Notify)
    def notify(self, command: Notify) -> None:
        pass


class AccountHandler(BaseCommandHandler):
    @handle(Open)
    def open(self, command: Open) -> None:
        returned.append(send(str(uuid4())))


def register(domain: Domain) -> None:
    domain.config["idempotency"]["redis_url"] = REDIS_IDEMPOTENCY_URL
    domain.register(Account)
    domain.register(Notify, part_of=Account)
    domain.register(NotifyHandler, part_of=Account)
    domain.register(Open, part_of=Account)
    domain.register(AccountHandler, part_of=Account)


def send(key: str) -> int | None:
    return current_domain.process(
        Notify(account_id="a1"), asynchronous=True, idempotency_key=key
    )


@pytest.mark.postgresql
class TestASharedStore:
    @pytest.fixture
    def backend(self) -> str:
        return "postgresql"

    @pytest.fixture(params=["sync", "async"])
    def domain(self, request, make_shared_domain) -> Iterator[Domain]:
        domain = make_shared_domain(register, command_processing=request.param)
        assert domain.idempotency_store.is_active
        domain.idempotency_store.flush()
        yield domain
        domain.idempotency_store.flush()

    def test_a_rollback_records_no_key_and_stores_no_command(self, domain):
        key = str(uuid4())

        with pytest.raises(RuntimeError, match="rolled back"):
            with UnitOfWork():
                send(key)
                raise RuntimeError("rolled back")

        assert domain.idempotency_store.check(key) is None
        assert row_count(domain, "messages") == 0

    def test_the_commit_records_the_key(self, domain):
        key = str(uuid4())

        with UnitOfWork():
            send(key)
            assert domain.idempotency_store.check(key) is None

        assert domain.idempotency_store.check(key) is not None
        assert row_count(domain, "messages") == 1


@pytest.mark.postgresql
class TestASharedStoreInsideAHandler:
    @pytest.fixture
    def backend(self) -> str:
        return "postgresql"

    def test_process_returns_none(self, make_shared_domain):
        returned.clear()
        domain = make_shared_domain(register, command_processing="async")
        try:
            domain.process(Open(account_id="a1"), asynchronous=False)
        finally:
            domain.idempotency_store.flush()

        assert returned == [None]
        assert row_count(domain, "messages") == 2


@pytest.mark.postgresql
class TestASharedStoreOutsideAUnitOfWork:
    @pytest.fixture
    def backend(self) -> str:
        return "postgresql"

    def test_process_returns_the_position(self, make_shared_domain):
        domain = make_shared_domain(register, command_processing="async")
        try:
            assert send(str(uuid4())) == 0
        finally:
            domain.idempotency_store.flush()


class TestTheMemoryStore:
    @pytest.fixture
    def domain(self) -> Iterator[Domain]:
        domain = Domain(name="MemoryIdempotency")
        domain.config["command_processing"] = "async"
        register(domain)
        domain.init(traverse=False)
        with domain.domain_context():
            assert domain.idempotency_store.is_active
            domain.idempotency_store.flush()
            yield domain
            domain.idempotency_store.flush()
            provider_adapter(domain, "default").close()

    def test_the_key_is_recorded_before_process_returns(self, domain):
        key = str(uuid4())

        with UnitOfWork():
            position = send(key)
            assert domain.idempotency_store.check(key) == {
                "status": "success",
                "result": position,
            }

        assert position == 0
