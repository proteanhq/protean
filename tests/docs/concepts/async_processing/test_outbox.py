"""The examples on ``docs/concepts/async-processing/outbox.md`` behave as the page says."""

from datetime import timedelta

import pytest

from protean.server import Engine
from protean.utils.outbox import OutboxStatus
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _place_order(example, order_id: str) -> None:
    domain = example.domain
    with domain.domain_context():
        order = example.Order(order_id=order_id, total=25.0)
        order.raise_(example.OrderPlaced(order_id=order_id, total=25.0))
        domain.repository_for(example.Order).add(order)


def _outbox_rows(example):
    return example.domain._get_outbox_repo("default").query.all().items


def test_the_event_is_stored_in_the_outbox_and_published_by_the_engine():
    example = load_example("concepts/async-processing/outbox/001.py")
    example.domain.init(traverse=False)
    _place_order(example, "order-1")

    with example.domain.domain_context():
        broker = example.domain.brokers["default"]
        assert [row.status for row in _outbox_rows(example)] == [
            OutboxStatus.PENDING.value
        ]
        assert broker.read("shop::order", "probe", 10) == []

        Engine(example.domain, test_mode=True).run()

        assert [row.status for row in _outbox_rows(example)] == [
            OutboxStatus.PUBLISHED.value
        ]
        published = broker.read("shop::order", "probe", 10)
        assert [payload["data"]["order_id"] for _, payload in published] == ["order-1"]


def test_only_the_first_worker_claims_a_message():
    example = load_example("concepts/async-processing/outbox/001.py")
    example.domain.init(traverse=False)
    _place_order(example, "order-1")

    with example.domain.domain_context():
        repo = example.domain._get_outbox_repo("default")
        message = _outbox_rows(example)[0]
        now = example.domain.clock.now()

        assert example.claim(repo._dao, message, "worker-1", now) == 1
        assert example.claim(repo._dao, message, "worker-2", now) == 0

        row = repo.get(message.id)
        assert row.status == OutboxStatus.PROCESSING.value
        assert row.locked_by == "worker-1"


def test_a_published_message_cannot_be_claimed():
    example = load_example("concepts/async-processing/outbox/001.py")
    example.domain.init(traverse=False)
    _place_order(example, "order-1")

    with example.domain.domain_context():
        Engine(example.domain, test_mode=True).run()

        repo = example.domain._get_outbox_repo("default")
        message = _outbox_rows(example)[0]
        now = example.domain.clock.now()

        assert example.claim(repo._dao, message, "worker-1", now) == 0
        assert repo.get(message.id).status == OutboxStatus.PUBLISHED.value


def test_a_message_under_an_expired_lock_can_be_reclaimed():
    example = load_example("concepts/async-processing/outbox/001.py")
    example.domain.init(traverse=False)
    _place_order(example, "order-1")

    with example.domain.domain_context():
        repo = example.domain._get_outbox_repo("default")
        message = _outbox_rows(example)[0]
        now = example.domain.clock.now()

        assert example.claim(repo._dao, message, "worker-1", now) == 1
        assert example.claim(repo._dao, message, "worker-2", now) == 0

        after_expiry = now + timedelta(minutes=6)
        assert example.claim(repo._dao, message, "worker-2", after_expiry) == 1
        assert repo.get(message.id).locked_by == "worker-2"


def test_a_message_with_no_retries_left_cannot_be_claimed():
    example = load_example("concepts/async-processing/outbox/001.py")
    example.domain.init(traverse=False)
    _place_order(example, "order-1")

    with example.domain.domain_context():
        repo = example.domain._get_outbox_repo("default")
        message = _outbox_rows(example)[0]
        message.retry_count = message.max_retries
        repo.add(message)
        now = example.domain.clock.now()

        assert example.claim(repo._dao, message, "worker-1", now) == 0
        assert repo.get(message.id).status == OutboxStatus.PENDING.value


def test_a_failed_message_due_for_retry_can_be_claimed():
    example = load_example("concepts/async-processing/outbox/001.py")
    example.domain.init(traverse=False)
    _place_order(example, "order-1")

    with example.domain.domain_context():
        repo = example.domain._get_outbox_repo("default")
        message = _outbox_rows(example)[0]
        now = example.domain.clock.now()
        message.status = OutboxStatus.FAILED.value
        message.next_retry_at = now - timedelta(seconds=1)
        repo.add(message)

        assert example.claim(repo._dao, message, "worker-1", now) == 1
        assert repo.get(message.id).status == OutboxStatus.PROCESSING.value


def test_a_message_waiting_for_its_retry_time_cannot_be_claimed():
    example = load_example("concepts/async-processing/outbox/001.py")
    example.domain.init(traverse=False)
    _place_order(example, "order-1")

    with example.domain.domain_context():
        repo = example.domain._get_outbox_repo("default")
        message = _outbox_rows(example)[0]
        now = example.domain.clock.now()
        message.status = OutboxStatus.FAILED.value
        message.next_retry_at = now + timedelta(minutes=1)
        repo.add(message)

        assert example.claim(repo._dao, message, "worker-1", now) == 0
        assert repo.get(message.id).status == OutboxStatus.FAILED.value
