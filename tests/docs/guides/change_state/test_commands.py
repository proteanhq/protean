"""Check what docs/guides/change-state/commands.md says about commands.

``006.py`` defines ``PublishArticle``. The ``commands/`` examples define an
``Order`` aggregate with ``PlaceOrder``, ``ReserveStock`` and ``ChargeCard``
commands. Each test loads its example fresh, so every test gets its own domain,
its own memory store and its own memory event store. No Redis is configured,
so no submission is deduplicated.
"""

from datetime import UTC, datetime, timedelta

import pytest

from protean import Domain
from protean.exceptions import (
    IncorrectUsageError,
    ObjectNotFoundError,
    ValidationError,
)
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def activated(domain):
    domain.init(traverse=False)
    return domain.domain_context()


@pytest.fixture
def publishing_example():
    module = load_example("guides/change-state/006.py")
    with activated(module.publishing):
        yield module


@pytest.fixture
def idempotency_example():
    module = load_example("guides/change-state/commands/001.py")
    with activated(module.domain):
        yield module


@pytest.fixture
def modes_example():
    module = load_example("guides/change-state/commands/002.py")
    with activated(module.domain):
        yield module


@pytest.fixture
def deadlines_example():
    module = load_example("guides/change-state/commands/003.py")
    with activated(module.domain):
        yield module


def saved_items(module, order_id):
    return module.domain.repository_for(module.Order).get(order_id).items


class TestDefiningCommands:
    def test_publish_article_accepts_an_article_id(self, publishing_example):
        before = datetime.now(UTC)

        command = publishing_example.PublishArticle(article_id="1")

        assert command.article_id == "1"
        assert before <= command.published_at <= datetime.now(UTC)

    def test_publish_article_requires_an_article_id(self, publishing_example):
        with pytest.raises(ValidationError) as exc_info:
            publishing_example.PublishArticle()

        assert "article_id" in exc_info.value.messages

    def test_a_command_cannot_be_changed_once_created(self, publishing_example):
        command = publishing_example.PublishArticle(article_id="1")
        published_at = command.published_at

        with pytest.raises(IncorrectUsageError) as exc_info:
            command.published_at = datetime.now(UTC) - timedelta(hours=24)

        assert "immutable" in str(exc_info.value)
        assert command.published_at == published_at

    def test_place_order_accepts_an_order_id_and_items(self, idempotency_example):
        command = idempotency_example.PlaceOrder(order_id="ord-42", items=["book"])

        assert command.order_id == "ord-42"
        assert command.items == ["book"]

    def test_place_order_requires_an_order_id_and_items(self, idempotency_example):
        with pytest.raises(ValidationError) as exc_info:
            idempotency_example.PlaceOrder()

        assert {"order_id", "items"} <= set(exc_info.value.messages)


class TestIdempotencyKeys:
    def test_the_handler_reads_the_key_from_the_metadata(self, idempotency_example):
        assert idempotency_example.place_order("ord-42", ["book"]) == "req-abc-123"
        assert saved_items(idempotency_example, "ord-42") == ["book"]

    def test_without_redis_a_repeated_key_runs_the_handler_again(
        self, idempotency_example
    ):
        first = idempotency_example.place_order("ord-1", ["book"])
        second = idempotency_example.place_order("ord-2", ["pen"])

        # The second call was not answered from a cache: its order was saved.
        assert first == second == "req-abc-123"
        assert saved_items(idempotency_example, "ord-1") == ["book"]
        assert saved_items(idempotency_example, "ord-2") == ["pen"]

    def test_without_redis_raise_on_duplicate_raises_nothing(self, idempotency_example):
        assert idempotency_example.place_order_once("ord-1", ["book"]) is None
        assert idempotency_example.place_order_once("ord-2", ["pen"]) is None

        assert saved_items(idempotency_example, "ord-1") == ["book"]
        assert saved_items(idempotency_example, "ord-2") == ["pen"]


class TestProcessingModes:
    def test_synchronous_processing_runs_the_handler_now(self, modes_example):
        command = modes_example.PlaceOrder(order_id="ord-1", items=["book"])

        assert modes_example.process_now(command) == "ord-1"
        assert saved_items(modes_example, "ord-1") == ["book"]

    def test_asynchronous_processing_only_stores_the_command(self, modes_example):
        command = modes_example.PlaceOrder(order_id="ord-2", items=["book"])

        position = modes_example.process_later(command)

        assert isinstance(position, int)
        with pytest.raises(ObjectNotFoundError):
            modes_example.domain.repository_for(modes_example.Order).get("ord-2")


@pytest.fixture
def config_example():
    module = load_example("guides/change-state/commands/004.py")
    with activated(module.domain):
        yield module


@pytest.fixture
def handler_timeout_example():
    module = load_example("guides/change-state/commands/005.py")
    with activated(module.domain):
        yield module


class TestDomainConfiguration:
    def test_the_code_setting_makes_command_processing_sync(self, deadlines_example):
        assert deadlines_example.domain.config["command_processing"] == "sync"

    def test_command_processing_is_async_by_default(self):
        assert Domain(name="Defaults").config["command_processing"] == "async"

    def test_the_config_sets_the_default_modes(self, config_example):
        assert config_example.domain.config["command_processing"] == "sync"
        assert config_example.domain.config["event_processing"] == "async"

    def test_asynchronous_false_handles_the_command_now(self, config_example):
        command = config_example.PlaceOrder(order_id="ord-3", items=["book"])

        assert config_example.place_now(command) == "ord-3"
        assert saved_items(config_example, "ord-3") == ["book"]

    def test_a_sync_domain_ignores_asynchronous_true(self, config_example):
        command = config_example.PlaceOrder(order_id="ord-4", items=["pen"])

        result = config_example.domain.process(command, asynchronous=True)

        assert result == "ord-4"
        assert saved_items(config_example, "ord-4") == ["pen"]


class TestDeadlines:
    def test_the_handler_timeout_is_set_on_the_handler(self, handler_timeout_example):
        meta = handler_timeout_example.OrderCommandHandler.meta_

        assert meta.timeout == 30

    def test_an_absolute_deadline_reaches_the_handler(self, deadlines_example):
        before = datetime.now(UTC)

        deadline = deadlines_example.charge_by_deadline()

        assert before + timedelta(seconds=30) <= deadline
        assert deadline <= datetime.now(UTC) + timedelta(seconds=30)

    def test_a_timeout_becomes_an_absolute_deadline(self, deadlines_example):
        before = datetime.now(UTC)

        deadline = deadlines_example.charge_within_timeout()

        assert before + timedelta(seconds=30) <= deadline
        assert deadline <= datetime.now(UTC) + timedelta(seconds=30)

    def test_a_downstream_command_inherits_the_deadline(self, deadlines_example):
        deadline = datetime.now(UTC) + timedelta(minutes=5)

        deadlines_example.domain.process(
            deadlines_example.PlaceOrder(order_id="ord-42", items=["book"]),
            deadline=deadline,
        )

        assert deadlines_example.reservation_deadlines == [deadline]

    def test_an_expired_command_is_reported_and_changes_nothing(
        self, deadlines_example
    ):
        past_deadline = datetime.now(UTC) - timedelta(seconds=1)
        command = deadlines_example.PlaceOrder(order_id="ord-42", items=["book"])

        command_type, deadline = deadlines_example.process_before(
            command, past_deadline
        )

        assert command_type == deadlines_example.PlaceOrder.__type__
        assert deadline == past_deadline
        assert deadlines_example.reservation_deadlines == []
