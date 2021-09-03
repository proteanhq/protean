import logging
import sys

from datetime import datetime
from typing import Dict

import pytest

from protean import (
    BaseAggregate,
    BaseApplicationService,
    BaseEvent,
    BaseSubscriber,
    UnitOfWork,
)
from protean.fields import DateTime, Float, Identifier, Integer, String
from protean.globals import current_domain
from protean.infra.eventing import EventLog, EventLogStatus
from protean.infra.job import Job
from protean.server import Server
from protean.utils import EventExecution, EventStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(threadName)10s %(name)18s: %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger("EventingTests")

ACCOUNT_NUMBER_1 = 1
ACCOUNT_NUMBER_2 = 2


class Account(BaseAggregate):
    account_number = Integer(identifier=True)
    name = String(required=True)
    balance = Float(default=0.0)


class InvalidTransaction(Exception):
    """Raised on invalid input to perform transaction"""


class Transaction(BaseAggregate):
    from_account_number = Integer(required=True)
    to_account_number = Integer(required=True)
    amount = Float(min_value=0.0)
    transacted_at = DateTime(default=datetime.utcnow)

    @classmethod
    def perform(cls, from_account_number, to_account_number, amount):
        if from_account_number != to_account_number and amount > 0.0:
            transaction = cls(
                from_account_number=from_account_number,
                to_account_number=to_account_number,
                amount=amount,
            )

            current_domain.publish(
                Transacted(
                    transaction_id=transaction.id,
                    from_account_number=from_account_number,
                    to_account_number=to_account_number,
                    amount=amount,
                    transacted_at=transaction.transacted_at,
                )
            )

            return transaction
        else:
            values = locals()
            raise InvalidTransaction(
                {
                    key: values[key]
                    for key in ["from_account_number", "to_account_number", "amount"]
                }
            )


class Transacted(BaseEvent):
    transaction_id = Identifier()
    from_account_number = Integer()
    to_account_number = Integer()
    amount = Float()
    transacted_at = DateTime()


class TransactionService(BaseApplicationService):
    @classmethod
    def perform_transaction(cls, from_account_number, to_account_number, amount):
        with UnitOfWork():
            transaction = Transaction.perform(
                from_account_number, to_account_number, amount
            )
            current_domain.repository_for(Transaction).add(transaction)


class UpdateBalances(BaseSubscriber):
    class Meta:
        event = Transacted

    def __call__(self, event: Dict):
        with UnitOfWork():
            account_repo = current_domain.repository_for(Account)

            account1 = account_repo.get(event["from_account_number"])
            account1.balance -= event["amount"]

            account2 = account_repo.get(event["to_account_number"])
            account2.balance += event["amount"]

            account_repo.add(account1)
            account_repo.add(account2)


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(Account)
    test_domain.register(Transaction)
    test_domain.register(Transacted)
    test_domain.register(TransactionService)
    test_domain.register(UpdateBalances)


@pytest.fixture(autouse=True)
def setup(test_domain):
    account_repo = test_domain.repository_for(Account)
    account_repo.add(
        Account(account_number=ACCOUNT_NUMBER_1, name="John Doe", balance=100.0)
    )
    account_repo.add(
        Account(account_number=ACCOUNT_NUMBER_2, name="Jane Doe", balance=100.0)
    )


def verify_event_state_is(test_domain, state):
    eventlog_repo = test_domain.repository_for(EventLog)
    event = eventlog_repo.get_most_recent_event_by_type_cls(Transacted)

    assert event is not None
    assert event.status == state


def verify_account_balances(test_domain):
    account_repo = test_domain.repository_for(Account)
    account1 = account_repo.get(ACCOUNT_NUMBER_1)
    assert account1.balance == 80.0

    account2 = account_repo.get(ACCOUNT_NUMBER_2)
    assert account2.balance == 120.0


def test_inline_execution(test_domain):
    test_domain.config["EVENT_STRATEGY"] = EventStrategy.INLINE.value

    TransactionService.perform_transaction(ACCOUNT_NUMBER_1, ACCOUNT_NUMBER_2, 20.0)

    assert len(test_domain.repository_for(EventLog).all()) == 0
    verify_account_balances(test_domain)


@pytest.mark.redis
def test_broker_based_execution(test_domain):
    test_domain.config["EVENT_STRATEGY"] = EventStrategy.INLINE.value
    test_domain.config["BROKERS"] = {
        "default": {
            "PROVIDER": "protean.adapters.broker.redis.RedisBroker",
            "URI": "redis://127.0.0.1:6379/0",
            "IS_ASYNC": True,
        },
    }

    TransactionService.perform_transaction(ACCOUNT_NUMBER_1, ACCOUNT_NUMBER_2, 20.0)

    server = Server(test_domain, test_mode=True)
    server.run()

    assert len(test_domain.repository_for(EventLog).all()) == 0
    verify_account_balances(test_domain)


def test_inline_execution_with_event_persistence(test_domain):
    test_domain.config["EVENT_STRATEGY"] = EventStrategy.INLINE_WITH_EVENTLOG.value

    TransactionService.perform_transaction(ACCOUNT_NUMBER_1, ACCOUNT_NUMBER_2, 20.0)

    verify_event_state_is(test_domain, EventLogStatus.PUBLISHED.value)
    verify_account_balances(test_domain)


@pytest.mark.redis
def test_eventlog_driven_execution(test_domain):
    test_domain.config["EVENT_STRATEGY"] = EventStrategy.DB_SUPPORTED.value
    test_domain.config["BROKERS"] = {
        "default": {
            "PROVIDER": "protean.adapters.broker.redis.RedisBroker",
            "URI": "redis://127.0.0.1:6379/0",
            "IS_ASYNC": True,
        },
    }

    TransactionService.perform_transaction(ACCOUNT_NUMBER_1, ACCOUNT_NUMBER_2, 20.0)

    server = Server(test_domain, test_mode=True)
    server.run()

    verify_event_state_is(test_domain, EventLogStatus.PUBLISHED.value)
    verify_account_balances(test_domain)

    # No Jobs are created in raw DB_SUPPORTED mode
    assert len(test_domain.repository_for(Job).all()) == 0


@pytest.mark.redis
def test_eventlog_driven_execution_with_jobs(test_domain):
    test_domain.config["EVENT_STRATEGY"] = EventStrategy.DB_SUPPORTED_WITH_JOBS.value
    test_domain.config["BROKERS"] = {
        "default": {
            "PROVIDER": "protean.adapters.broker.redis.RedisBroker",
            "URI": "redis://127.0.0.1:6379/0",
            "IS_ASYNC": True,
        },
    }

    TransactionService.perform_transaction(ACCOUNT_NUMBER_1, ACCOUNT_NUMBER_2, 20.0)

    server = Server(test_domain, test_mode=True)
    server.run()

    verify_event_state_is(test_domain, EventLogStatus.PUBLISHED.value)
    verify_account_balances(test_domain)

    jobs = test_domain.repository_for(Job).all()
    assert len(jobs) == 1
    assert jobs[0].status == "COMPLETED"


@pytest.mark.redis
def test_eventlog_driven_execution_with_jobs_in_threads(test_domain):
    test_domain.config["EVENT_STRATEGY"] = EventStrategy.DB_SUPPORTED_WITH_JOBS.value
    test_domain.config["EVENT_EXECUTION"] = EventExecution.THREADED.value
    test_domain.config["BROKERS"] = {
        "default": {
            "PROVIDER": "protean.adapters.broker.redis.RedisBroker",
            "URI": "redis://127.0.0.1:6379/0",
            "IS_ASYNC": True,
        },
    }

    TransactionService.perform_transaction(ACCOUNT_NUMBER_1, ACCOUNT_NUMBER_2, 20.0)

    server = Server(test_domain, test_mode=True)
    server.run()

    verify_event_state_is(test_domain, EventLogStatus.PUBLISHED.value)
    verify_account_balances(test_domain)

    jobs = test_domain.repository_for(Job).all()
    assert len(jobs) == 1
    assert jobs[0].status == "COMPLETED"
