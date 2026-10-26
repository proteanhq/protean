"""Tests for subscription lag monitoring.

Every test builds a real domain and reads the statuses through
``collect_subscription_statuses``. The core tests use the memory event store,
the inline broker and the memory database. The Redis tests run against a live
Redis with the Redis Streams broker as the default broker, and register a
``sequential_by`` handler to get a partitioned category.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import redis

from protean.cli.recover import _perform_resets, _verdict
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector
from protean.core.subscriber import BaseSubscriber
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
    checkpoint_ahead_of_failed_stream,
    reconstruct_unresolved,
)
from protean.server.subscription_status import (
    RecoveryCheckpointStatus,
    SubscriptionStatus,
    collect_recovery_checkpoint_statuses,
    collect_subscription_statuses,
    reset_checkpoint_to_head,
    reset_recovery_checkpoint,
)
from protean.utils import fqn
from protean.utils.eventing import DomainMeta, MessageHeaders, MessageType, Metadata
from protean.utils.mixins import handle
from protean.utils.outbox import Outbox
from tests.shared import REDIS_URI, FrozenClock

STATUS_LOGGER = "protean.server.subscription_status"

# ---------------------------------------------------------------------------
# Domain elements
# ---------------------------------------------------------------------------


class Order(BaseAggregate):
    client_id = String()


class OrderPlaced(BaseEvent):
    order_id = Identifier(identifier=True)
    client_id = String()


class PlaceOrder(BaseCommand):
    order_id = Identifier(identifier=True)


class CancelOrder(BaseCommand):
    order_id = Identifier(identifier=True)


class Account(BaseAggregate):
    name = String()


class AccountOpened(BaseEvent):
    account_id = Identifier(identifier=True)


class OpenAccount(BaseCommand):
    account_id = Identifier(identifier=True)


class OrderNotifier(BaseEventHandler):
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        pass


class OrderMirror(BaseEventHandler):
    """Registered with ``subscription_type="stream"``."""

    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        pass


class OrderSequencer(BaseEventHandler):
    """Registered with ``sequential_by``."""

    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        pass


class AccountWatcher(BaseEventHandler):
    @handle(AccountOpened)
    def on_opened(self, event: AccountOpened) -> None:
        pass


class PlaceOrderHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder) -> None:
        pass


class CancelOrderHandler(BaseCommandHandler):
    @handle(CancelOrder)
    def cancel(self, command: CancelOrder) -> None:
        pass


class OpenAccountHandler(BaseCommandHandler):
    @handle(OpenAccount)
    def open(self, command: OpenAccount) -> None:
        pass


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)


class OrderSummaryProjector(BaseProjector):
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        pass


class Fulfillment(BaseProcessManager):
    order_id = Identifier()

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_placed(self, event: OrderPlaced) -> None:
        pass


class PartnerFeed(BaseSubscriber):
    def __call__(self, payload: dict) -> None:
        pass


def _statuses(domain: Domain) -> dict[str, SubscriptionStatus]:
    return {status.name: status for status in collect_subscription_statuses(domain)}


def _register_order(domain: Domain) -> str:
    domain.register(Order)
    domain.register(OrderPlaced, part_of=Order)
    return Order.meta_.stream_category


def _write_events(store, stream_category: str, count: int) -> None:
    with_metadata = {"headers": {"id": str(uuid4()), "type": "OrderPlaced"}}
    for n in range(count):
        store._write(f"{stream_category}-1", "OrderPlaced", {"n": n}, with_metadata)


def _write_checkpoint(store, position_stream: str, position: int) -> None:
    """Write a ``Read`` position record, the shape a live subscription writes."""
    store._write(position_stream, "Read", {"position": position})


# ---------------------------------------------------------------------------
# SubscriptionStatus dataclass
# ---------------------------------------------------------------------------


class TestSubscriptionStatusDataclass:
    def test_to_dict_returns_all_fields(self):
        status = SubscriptionStatus(
            name="handler-1",
            handler_name="OrderProjector",
            subscription_type="event_store",
            stream_category="order",
            lag=5,
            pending=0,
            current_position="10",
            head_position="15",
            status="lagging",
            consumer_count=0,
            dlq_depth=0,
        )
        d = status.to_dict()
        assert d["name"] == "handler-1"
        assert d["handler_name"] == "OrderProjector"
        assert d["subscription_type"] == "event_store"
        assert d["stream_category"] == "order"
        assert d["lag"] == 5
        assert d["pending"] == 0
        assert d["current_position"] == "10"
        assert d["head_position"] == "15"
        assert d["status"] == "lagging"
        assert d["consumer_count"] == 0
        assert d["dlq_depth"] == 0
        assert "last_updated" in d
        assert d["last_updated"] is None
        assert "lag_seconds" in d
        assert d["lag_seconds"] is None

    def test_to_dict_with_none_lag(self):
        status = SubscriptionStatus(
            name="handler-1",
            handler_name="Handler",
            subscription_type="stream",
            stream_category="test",
            lag=None,
            pending=0,
            current_position=None,
            head_position=None,
            status="unknown",
            consumer_count=0,
            dlq_depth=0,
        )
        d = status.to_dict()
        assert d["lag"] is None
        assert d["status"] == "unknown"


# ---------------------------------------------------------------------------
# Which subscriptions are reported
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_empty_domain_reports_nothing(self, test_domain):
        test_domain.init(traverse=False)
        assert collect_subscription_statuses(test_domain) == []

    def test_event_handler_is_read_from_the_event_store(self, test_domain):
        category = _register_order(test_domain)
        test_domain.register(OrderNotifier, part_of=Order)
        test_domain.init(traverse=False)

        status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.handler_name == "OrderNotifier"
        assert status.subscription_type == "event_store"
        assert status.stream_category == category
        assert status.position_stream == f"position-{fqn(OrderNotifier)}-{category}"

    def test_explicit_stream_category_wins(self, test_domain):
        _register_order(test_domain)
        test_domain.register(OrderNotifier, stream_category="audit")
        test_domain.init(traverse=False)

        status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.stream_category == "audit"
        assert status.position_stream == f"position-{fqn(OrderNotifier)}-audit"

    def test_stream_handler_without_a_redis_broker_is_unknown(self, test_domain):
        """The inline broker has no Redis client, so there is nothing to read."""
        category = _register_order(test_domain)
        test_domain.register(OrderMirror, part_of=Order, subscription_type="stream")
        test_domain.init(traverse=False)

        status = _statuses(test_domain)[fqn(OrderMirror)]

        assert status.subscription_type == "stream"
        assert status.stream_category == category
        assert status.status == "unknown"
        assert status.lag is None
        assert status.position_stream is None

    def test_sequential_by_on_a_non_partitioning_broker_reads_the_base_stream(
        self, test_domain
    ):
        """``sequential_by`` is a no-op under the inline broker, so the
        category is not read as partitions."""
        category = _register_order(test_domain)
        test_domain.register(
            OrderSequencer,
            part_of=Order,
            sequential_by="client_id",
            subscription_type="stream",
        )
        test_domain.init(traverse=False)

        status = _statuses(test_domain)[fqn(OrderSequencer)]

        assert status.stream_category == category
        assert status.current_position is None
        assert status.status == "unknown"

    def test_command_handlers_on_one_stream_share_one_dispatcher(self, test_domain):
        """The Engine runs one dispatcher per command stream, named
        ``protean.server.engine.Commands:{stream}``, and the status reads that
        dispatcher's checkpoint."""
        _register_order(test_domain)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(CancelOrder, part_of=Order)
        test_domain.register(PlaceOrderHandler, part_of=Order)
        test_domain.register(CancelOrderHandler, part_of=Order)
        test_domain.init(traverse=False)
        command_stream = f"{Order.meta_.stream_category}:command"

        statuses = collect_subscription_statuses(test_domain)

        assert [s.name for s in statuses] == [f"commands:{command_stream}"]
        assert statuses[0].handler_name == "PlaceOrderHandler"
        assert statuses[0].subscription_type == "event_store"
        assert statuses[0].stream_category == command_stream
        assert statuses[0].position_stream == (
            f"position-protean.server.engine.Commands:{command_stream}-{command_stream}"
        )

    def test_stream_command_handler_is_read_from_the_broker(self, test_domain):
        _register_order(test_domain)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(
            PlaceOrderHandler, part_of=Order, subscription_type="stream"
        )
        test_domain.init(traverse=False)
        command_stream = f"{Order.meta_.stream_category}:command"

        status = _statuses(test_domain)[f"commands:{command_stream}"]

        assert status.subscription_type == "stream"
        assert status.status == "unknown"

    def test_projector_reports_one_row_per_stream_category(self, test_domain):
        category = _register_order(test_domain)
        test_domain.register(OrderSummary)
        test_domain.register(
            OrderSummaryProjector,
            projector_for=OrderSummary,
            stream_categories=[category, "test::payment"],
        )
        test_domain.init(traverse=False)
        name = fqn(OrderSummaryProjector)

        statuses = collect_subscription_statuses(test_domain)

        assert [(s.name, s.subscription_type, s.stream_category) for s in statuses] == [
            (f"{name}-{category}", "event_store", category),
            (f"{name}-test::payment", "event_store", "test::payment"),
        ]

    def test_stream_projector_is_read_from_the_broker(self, test_domain):
        category = _register_order(test_domain)
        test_domain.register(OrderSummary)
        test_domain.register(
            OrderSummaryProjector,
            projector_for=OrderSummary,
            stream_categories=[category],
            subscription_type="stream",
        )
        test_domain.init(traverse=False)

        status = _statuses(test_domain)[f"{fqn(OrderSummaryProjector)}-{category}"]

        assert status.subscription_type == "stream"
        assert status.status == "unknown"

    def test_process_manager_reports_one_row_per_stream_category(self, test_domain):
        category = _register_order(test_domain)
        test_domain.register(Fulfillment, stream_categories=[category, "test::payment"])
        test_domain.init(traverse=False)
        name = fqn(Fulfillment)

        statuses = collect_subscription_statuses(test_domain)

        assert [(s.name, s.subscription_type, s.stream_category) for s in statuses] == [
            (f"{name}-{category}", "event_store", category),
            (f"{name}-test::payment", "event_store", "test::payment"),
        ]

    def test_stream_process_manager_is_read_from_the_broker(self, test_domain):
        category = _register_order(test_domain)
        test_domain.register(
            Fulfillment, stream_categories=[category], subscription_type="stream"
        )
        test_domain.init(traverse=False)

        status = _statuses(test_domain)[f"{fqn(Fulfillment)}-{category}"]

        assert status.subscription_type == "stream"
        assert status.status == "unknown"

    @pytest.mark.no_test_domain
    def test_handlers_with_no_stream_category_are_left_out(self, caplog):
        """A handler whose ``part_of`` never resolved to an aggregate has no
        stream to read. It is left out, with the reason logged at DEBUG."""
        domain = Domain(name="Unresolved")
        domain.register(OrderNotifier, part_of="Order")
        domain.register(PlaceOrderHandler, part_of="Order")

        with caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER):
            result = collect_subscription_statuses(domain)

        assert result == []
        skipped = [r for r in caplog.records if "out of the subscription" in r.message]
        assert [r.getMessage() for r in skipped] == [
            f"Leaving {fqn(OrderNotifier)} out of the subscription status",
            f"Leaving {fqn(PlaceOrderHandler)} out of the subscription status",
        ]
        assert [r.levelno for r in skipped] == [logging.DEBUG, logging.DEBUG]
        assert [type(r.exc_info[1]) for r in skipped] == [ValueError, ValueError]


# ---------------------------------------------------------------------------
# Event-store subscriptions
# ---------------------------------------------------------------------------


class TestEventStoreStatus:
    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        self.category = _register_order(test_domain)
        test_domain.register(OrderNotifier, part_of=Order)
        test_domain.init(traverse=False)
        self.store = test_domain.event_store.store
        self.position_stream = f"position-{fqn(OrderNotifier)}-{self.category}"

    def test_lag_is_head_minus_checkpoint(self, test_domain):
        test_domain.clock = FrozenClock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
        _write_events(self.store, self.category, 5)
        _write_checkpoint(self.store, self.position_stream, 2)
        test_domain.clock.advance(timedelta(seconds=30))

        status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.current_position == "2"
        assert status.head_position == "5"
        assert status.lag == 3
        assert status.status == "lagging"
        assert status.last_updated == "2026-01-01T12:00:00+00:00"
        assert status.lag_seconds == 30.0

    def test_caught_up_is_ok_with_zero_seconds(self, test_domain):
        test_domain.clock = FrozenClock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
        _write_events(self.store, self.category, 3)
        _write_checkpoint(self.store, self.position_stream, 3)
        test_domain.clock.advance(timedelta(seconds=30))

        status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.lag == 0
        assert status.status == "ok"
        assert status.lag_seconds == 0.0

    def test_clock_behind_the_checkpoint_clamps_seconds_to_zero(self, test_domain):
        test_domain.clock = FrozenClock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
        _write_events(self.store, self.category, 3)
        _write_checkpoint(self.store, self.position_stream, 1)
        test_domain.clock = FrozenClock(datetime(2026, 1, 1, 11, 59, 57, tzinfo=UTC))

        status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.lag == 2
        assert status.lag_seconds == 0.0

    def test_checkpoint_past_the_head_is_zero_lag(self, test_domain):
        """A checkpoint past the head is what ``protean recover
        --reset-beyond-head`` repairs. The status shows it as caught up, not as
        a negative lag."""
        _write_events(self.store, self.category, 3)
        _write_checkpoint(self.store, self.position_stream, 10)

        status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.current_position == "10"
        assert status.head_position == "3"
        assert status.lag == 0
        assert status.status == "ok"

    def test_no_checkpoint_counts_the_whole_stream_with_no_seconds(self, test_domain):
        """A subscription that never wrote a checkpoint counts from -1, so its
        lag covers the whole stream. With no write time its seconds behind are
        unknown, not 0."""
        _write_events(self.store, self.category, 3)

        status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.current_position == "-1"
        assert status.head_position == "3"
        assert status.lag == 4
        assert status.last_updated is None
        assert status.lag_seconds is None

    def test_empty_stream_is_unknown(self, test_domain):
        status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.head_position == "-1"
        assert status.lag is None
        assert status.status == "unknown"
        assert status.lag_seconds is None

    def test_store_read_failure_is_unknown_and_keeps_recovery_streams(
        self, test_domain
    ):
        with patch.object(
            self.store, "_read_last_message", side_effect=RuntimeError("store down")
        ):
            status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.status == "unknown"
        assert status.lag is None
        assert status.recovery_checkpoint_stream == (
            f"recovery-checkpoint-{fqn(OrderNotifier)}-{self.category}"
        )
        assert status.failed_positions_stream == (
            f"failed-{fqn(OrderNotifier)}-{self.category}"
        )

    def test_reset_targets_the_stream_the_subscription_reads(self, test_domain):
        """The stream a reset writes to (status.position_stream) is exactly the
        stream a live EventStoreSubscription loads its checkpoint from. Binds the
        two independent ``position-...`` derivations so a drift cannot send the
        reset to a dead stream the engine never reads."""
        engine = Engine(test_domain, test_mode=True)
        subscription = EventStoreSubscription(engine, self.category, OrderNotifier)

        status = _statuses(test_domain)[fqn(OrderNotifier)]

        assert status.position_stream == subscription.subscriber_stream_name


@pytest.mark.no_test_domain
def test_event_store_status_is_unknown_when_the_domain_has_no_store():
    """An uninitialized domain has no event store. The status is unknown but
    still names the recovery streams, so ``protean recover`` can scan them."""
    domain = Domain(name="NoStore")
    domain.register(OrderNotifier, stream_category="order")

    status = _statuses(domain)[fqn(OrderNotifier)]

    assert status.status == "unknown"
    assert status.subscription_type == "event_store"
    assert status.position_stream is None
    assert status.recovery_checkpoint_stream == (
        f"recovery-checkpoint-{fqn(OrderNotifier)}-order"
    )
    assert status.failed_positions_stream == f"failed-{fqn(OrderNotifier)}-order"


# ---------------------------------------------------------------------------
# Broker subscribers on a broker with no Redis client
# ---------------------------------------------------------------------------


class TestBrokerStatusWithoutRedis:
    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(PartnerFeed, stream="partner-feed", broker="default")
        test_domain.init(traverse=False)
        self.broker = test_domain.brokers["default"]

    def test_counts_come_from_broker_info(self, test_domain):
        """The inline broker's ``info()`` reports no pending count, so the
        subscriber reads as caught up."""
        self.broker.publish("partner-feed", {"n": 1})
        self.broker.get_next("partner-feed", fqn(PartnerFeed))

        status = _statuses(test_domain)[fqn(PartnerFeed)]

        assert status.subscription_type == "broker"
        assert status.stream_category == "partner-feed"
        assert status.lag == 0
        assert status.pending == 0
        assert status.consumer_count == 0
        assert status.status == "ok"
        assert status.head_position is None

    def test_pending_reported_by_broker_info_is_lagging(self, test_domain):
        """A broker adapter that reports a pending count in ``info()`` shows
        that count as the lag. No broker that ships with Protean other than
        Redis reports one, so the reply stands for a third-party adapter's."""
        reply = {
            "consumer_groups": {fqn(PartnerFeed): {"pending": 2, "consumer_count": 1}}
        }

        with patch.object(self.broker, "info", return_value=reply):
            status = _statuses(test_domain)[fqn(PartnerFeed)]

        assert status.lag == 2
        assert status.pending == 2
        assert status.consumer_count == 1
        assert status.status == "lagging"

    def test_info_failure_is_unknown(self, test_domain):
        with patch.object(self.broker, "info", side_effect=RuntimeError("down")):
            status = _statuses(test_domain)[fqn(PartnerFeed)]

        assert status.subscription_type == "broker"
        assert status.status == "unknown"
        assert status.lag is None


@pytest.mark.no_test_domain
def test_broker_subscriber_on_an_unconfigured_broker_is_unknown():
    domain = Domain(name="NoBroker")
    domain.register(PartnerFeed, stream="partner-feed", broker="partner")

    status = _statuses(domain)[fqn(PartnerFeed)]

    assert status.subscription_type == "broker"
    assert status.stream_category == "partner-feed"
    assert status.status == "unknown"


# ---------------------------------------------------------------------------
# Outbox processors
# ---------------------------------------------------------------------------


def _outbox_domain(*, external_brokers: list[str] | None = None) -> Domain:
    domain = Domain(name="OutboxStatus")
    domain.config["enable_outbox"] = True
    domain.config["server"] = {"default_subscription_type": "stream"}
    domain.config["databases"]["unmanaged"] = {"provider": "memory", "managed": False}
    domain.config["outbox"] = {
        "broker": "default",
        "external_brokers": external_brokers or [],
    }
    for broker_name in external_brokers or []:
        domain.config["brokers"][broker_name] = {"provider": "inline"}
    domain._initialize()
    _register_order(domain)
    return domain


def _add_outbox_rows(domain: Domain, provider: str, rows: list[tuple[str, str]]):
    """Add one outbox row per ``(status, target_broker)`` pair."""
    metadata = Metadata(
        headers=MessageHeaders(
            id="status-test", type="OrderPlaced", time=datetime.now(UTC), stream="s"
        ),
        domain=DomainMeta(
            fqn="tests.OrderPlaced",
            kind="event",
            origin_stream="order-1",
            version="1.0",
            sequence_id="1",
        ),
    )
    repo = domain._get_outbox_repo(provider)
    for n, (row_status, target_broker) in enumerate(rows):
        row = Outbox.create_message(
            message_id=f"{provider}-{n}",
            stream_name="order-1",
            message_type="OrderPlaced",
            data={},
            metadata=metadata,
            target_broker=target_broker,
        )
        row.status = row_status
        repo.add(row)


@pytest.mark.no_test_domain
class TestOutboxStatus:
    def test_no_outbox_means_no_rows(self, test_domain):
        domain = Domain(name="NoOutbox")
        domain._initialize()
        _register_order(domain)
        domain.init(traverse=False)

        assert collect_subscription_statuses(domain) == []

    def test_one_row_per_provider_an_aggregate_uses(self):
        """The memory provider holds no aggregate and the unmanaged one runs no
        processor, so only ``default`` is reported."""
        domain = _outbox_domain()
        domain.init(traverse=False)
        with domain.domain_context():
            _add_outbox_rows(
                domain,
                "default",
                [
                    ("pending", "default"),
                    ("pending", "default"),
                    ("processing", "default"),
                    ("failed", "default"),
                    ("abandoned", "default"),
                    ("published", "default"),
                ],
            )

        statuses = collect_subscription_statuses(domain)

        assert [s.name for s in statuses] == ["outbox-processor-default-to-default"]
        status = statuses[0]
        assert status.handler_name == "OutboxProcessor"
        assert status.subscription_type == "outbox"
        assert status.stream_category == "default → default"
        assert status.lag == 3
        assert status.pending == 2
        assert status.dlq_depth == 2
        assert status.status == "lagging"

    def test_drained_outbox_is_ok(self):
        domain = _outbox_domain()
        domain.init(traverse=False)
        with domain.domain_context():
            _add_outbox_rows(domain, "default", [("published", "default")])

        [status] = collect_subscription_statuses(domain)

        assert status.lag == 0
        assert status.status == "ok"

    def test_every_provider_an_aggregate_uses_gets_a_row(self):
        domain = _outbox_domain(external_brokers=["partner"])
        domain.config["databases"]["ledger"] = {"provider": "memory"}
        domain._initialize()
        _register_order(domain)
        domain.register(Account, provider="ledger")
        domain.init(traverse=False)

        names = [s.name for s in collect_subscription_statuses(domain)]

        assert names == [
            "outbox-processor-default-to-default",
            "outbox-processor-ledger-to-default",
            "outbox-processor-default-to-partner-external",
            "outbox-processor-ledger-to-partner-external",
        ]

    def test_each_processor_counts_only_rows_for_its_broker(self):
        domain = _outbox_domain(external_brokers=["partner", "analytics"])
        domain.init(traverse=False)
        with domain.domain_context():
            _add_outbox_rows(
                domain,
                "default",
                [
                    ("pending", "default"),
                    ("pending", "partner"),
                    ("pending", "partner"),
                    ("failed", "partner"),
                ],
            )

        statuses = collect_subscription_statuses(domain)

        assert [(s.name, s.stream_category, s.lag, s.dlq_depth) for s in statuses] == [
            (
                "outbox-processor-default-to-default",
                "default → default",
                1,
                0,
            ),
            (
                "outbox-processor-default-to-partner-external",
                "default → partner (external)",
                2,
                1,
            ),
            (
                "outbox-processor-default-to-analytics-external",
                "default → analytics (external)",
                0,
                0,
            ),
        ]

    def test_without_external_brokers_every_row_is_counted(self):
        """The single processor owns every row, whatever its target broker."""
        domain = _outbox_domain()
        domain.init(traverse=False)
        with domain.domain_context():
            _add_outbox_rows(
                domain, "default", [("pending", "default"), ("pending", "partner")]
            )

        [status] = collect_subscription_statuses(domain)

        assert status.lag == 2

    def test_count_failure_is_unknown(self):
        domain = _outbox_domain()
        domain.init(traverse=False)
        with domain.domain_context():
            repo = domain._get_outbox_repo("default")

        with patch.object(repo, "count_by_status", side_effect=RuntimeError("db")):
            [status] = collect_subscription_statuses(domain)

        assert status.name == "outbox-processor-default-to-default"
        assert status.status == "unknown"
        assert status.lag is None


# ---------------------------------------------------------------------------
# Redis Streams broker
# ---------------------------------------------------------------------------


def _redis_domain() -> Domain:
    domain = Domain(name="StatusRedis")
    domain.config["brokers"]["default"] = {
        "provider": "redis",
        "URI": f"{REDIS_URI}/13",
    }
    domain._initialize()
    _register_order(domain)
    domain.register(Account)
    domain.register(AccountOpened, part_of=Account)
    domain.register(OpenAccount, part_of=Account)
    domain.register(
        OrderSequencer,
        part_of=Order,
        sequential_by="client_id",
        subscription_type="stream",
    )
    domain.register(AccountWatcher, part_of=Account, subscription_type="stream")
    domain.register(OpenAccountHandler, part_of=Account, subscription_type="stream")
    domain.register(PartnerFeed, stream="partner-feed", broker="default")
    domain.init(traverse=False)
    return domain


@pytest.fixture
def redis_domain():
    domain = _redis_domain()
    with domain.domain_context():
        domain.brokers["default"]._data_reset()
        yield domain
        domain.brokers["default"]._data_reset()


def _raise_on(real, stream: str, exc: Exception):
    """A side effect that raises for one stream and passes the rest through."""

    def side_effect(name, *args, **kwargs):
        if name == stream:
            raise exc
        return real(name, *args, **kwargs)

    return side_effect


def _lose_native_lag(broker, stream: str, group: str) -> None:
    """Publish four entries, read the first as ``group``, then delete the third.

    Redis 7 cannot compute a lag across a deleted entry, so ``XINFO GROUPS``
    reports ``lag`` as nil. Two entries are left after the last-delivered id.
    """
    for n in range(4):
        broker.publish(stream, {"n": n})
    broker.get_next(stream, group)
    third_id = broker.redis_instance.xrange(stream)[2][0]
    broker.redis_instance.xdel(stream, third_id)
    [info] = [
        g
        for g in broker.redis_instance.xinfo_groups(stream)
        if g["name"] == group.encode()
    ]
    assert info["lag"] is None


def _messages_about(caplog, *streams: str) -> list[str]:
    """The status log lines that name one of ``streams`` exactly. Every other
    subscription in the domain is probed in the same call and logs about its
    own stream."""
    patterns = [re.compile(rf" {re.escape(stream)}(: |$)") for stream in streams]
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == STATUS_LOGGER
        and any(pattern.search(r.getMessage()) for pattern in patterns)
    ]


@pytest.mark.redis
@pytest.mark.no_test_domain
class TestRedisStreamStatus:
    @pytest.fixture(autouse=True)
    def setup(self, redis_domain):
        self.domain = redis_domain
        self.broker = redis_domain.brokers["default"]
        self.redis = self.broker.redis_instance
        self.stream = Account.meta_.stream_category
        self.group = fqn(AccountWatcher)

    def _status(self) -> SubscriptionStatus:
        return _statuses(self.domain)[self.group]

    def test_lag_pending_and_consumers_come_from_the_group(self, caplog):
        for n in range(4):
            self.broker.publish(self.stream, {"n": n})
        first_id, _ = self.broker.get_next(self.stream, self.group)

        with caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER):
            status = self._status()

        assert status.subscription_type == "stream"
        assert status.stream_category == self.stream
        assert status.lag == 3
        assert status.pending == 1
        assert status.consumer_count == 1
        assert status.head_position == "4"
        assert status.current_position == first_id
        assert status.status == "lagging"
        assert _messages_about(caplog, self.stream) == []

    def test_caught_up_group_is_ok(self):
        self.broker.publish(self.stream, {"n": 1})
        self.redis.xgroup_create(self.stream, self.group, id="$")

        status = self._status()

        assert status.lag == 0
        assert status.pending == 0
        assert status.status == "ok"

    def test_stream_without_the_group_is_unknown(self):
        """No consumer group means no reading, and that is unknown lag, not 0."""
        self.broker.publish(self.stream, {"n": 1})

        status = self._status()

        assert status.head_position == "1"
        assert status.current_position is None
        assert status.lag is None
        assert status.pending == 0
        assert status.status == "unknown"

    def test_another_group_on_the_stream_is_ignored(self):
        self.broker.publish(self.stream, {"n": 1})
        self.broker.publish(self.stream, {"n": 2})
        self.broker.get_next(self.stream, "someone-else")
        self.redis.xgroup_create(self.stream, self.group, id="$")

        status = self._status()

        assert status.lag == 0
        assert status.pending == 0
        assert status.consumer_count == 0

    def test_dlq_depth_is_the_length_of_the_dlq_stream(self):
        self.broker.publish(self.stream, {"n": 1})
        self.redis.xgroup_create(self.stream, self.group, id="$")
        self.redis.xadd(f"{self.stream}:dlq", {"n": 1})
        self.redis.xadd(f"{self.stream}:dlq", {"n": 2})

        assert self._status().dlq_depth == 2

    def test_command_dispatcher_group_is_read(self):
        command_stream = f"{self.stream}:command"
        dispatcher = f"protean.server.engine.Commands:{command_stream}"
        self.broker.publish(command_stream, {"n": 1})
        self.broker.publish(command_stream, {"n": 2})
        self.broker.get_next(command_stream, dispatcher)

        status = _statuses(self.domain)[f"commands:{command_stream}"]

        assert status.handler_name == "OpenAccountHandler"
        assert status.lag == 1
        assert status.pending == 1
        assert status.consumer_count == 1

    def test_unreadable_lengths_show_zero_and_are_logged(self, caplog):
        self.broker.publish(self.stream, {"n": 1})
        self.redis.xgroup_create(self.stream, self.group, id="$")
        error = redis.ConnectionError("length gone")

        with (
            patch.object(self.redis, "xlen", side_effect=error),
            caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER),
        ):
            status = self._status()

        assert status.head_position == "0"
        assert status.dlq_depth == 0
        assert status.lag == 0
        assert _messages_about(caplog, self.stream) == [
            f"Could not read length of {self.stream}: {error!r}",
            f"Could not read DLQ depth of {self.stream}: {error!r}",
        ]

    def test_unreadable_groups_are_unknown_and_logged(self, caplog):
        self.broker.publish(self.stream, {"n": 1})
        self.broker.get_next(self.stream, self.group)

        with (
            patch.object(
                self.redis,
                "xinfo_groups",
                side_effect=redis.ConnectionError("redis down"),
            ),
            caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER),
        ):
            status = self._status()

        assert status.lag is None
        assert status.pending == 0
        assert status.status == "unknown"
        [record] = [
            r
            for r in caplog.records
            if r.getMessage()
            == f"Could not read group {self.group} on stream {self.stream}"
        ]
        assert record.levelno == logging.DEBUG
        assert str(record.exc_info[1]) == "redis down"

    def test_lag_redis_cannot_report_is_counted_after_the_last_delivered_entry(
        self,
    ):
        """Deleting an entry past the group's last-delivered id makes Redis 7
        send a nil ``lag``. The entries left after that id are counted."""
        _lose_native_lag(self.broker, self.stream, self.group)

        status = self._status()

        assert status.lag == 2
        assert status.pending == 1
        assert status.status == "lagging"

    def test_lag_that_cannot_be_counted_is_unknown_and_logged(self, caplog):
        """With nothing pending, reading a failed count as 0 would show the
        subscription as caught up."""
        _lose_native_lag(self.broker, self.stream, self.group)
        self.redis.xack(self.stream, self.group, self._status().current_position)
        error = redis.ConnectionError("range gone")

        with (
            patch.object(self.redis, "xrange", side_effect=error),
            caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER),
        ):
            status = self._status()

        assert status.lag is None
        assert status.pending == 0
        assert status.status == "unknown"
        assert _messages_about(caplog, self.stream) == [
            f"Could not count lag of {self.stream}: {error!r}"
        ]


@pytest.mark.redis
@pytest.mark.no_test_domain
class TestRedisBrokerSubscriberStatus:
    @pytest.fixture(autouse=True)
    def setup(self, redis_domain):
        self.domain = redis_domain
        self.broker = redis_domain.brokers["default"]
        self.redis = self.broker.redis_instance
        self.group = fqn(PartnerFeed)

    def _status(self) -> SubscriptionStatus:
        return _statuses(self.domain)[self.group]

    def test_lag_pending_and_consumers_come_from_the_group(self):
        for n in range(3):
            self.broker.publish("partner-feed", {"n": n})
        first_id, _ = self.broker.get_next("partner-feed", self.group)

        status = self._status()

        assert status.subscription_type == "broker"
        assert status.stream_category == "partner-feed"
        assert status.lag == 2
        assert status.pending == 1
        assert status.consumer_count == 1
        assert status.head_position == "3"
        assert status.current_position == first_id
        assert status.status == "lagging"

    def test_another_group_on_the_stream_is_ignored(self):
        self.broker.publish("partner-feed", {"n": 1})
        self.broker.get_next("partner-feed", "someone-else")

        status = self._status()

        assert status.lag is None
        assert status.pending == 0
        assert status.consumer_count == 0
        assert status.status == "unknown"

    def test_unreadable_length_shows_zero_and_is_logged(self, caplog):
        self.broker.publish("partner-feed", {"n": 1})
        self.broker.get_next("partner-feed", self.group)
        error = redis.ConnectionError("length gone")

        with (
            patch.object(self.redis, "xlen", side_effect=error),
            caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER),
        ):
            status = self._status()

        assert status.head_position == "0"
        assert status.lag == 0
        assert _messages_about(caplog, "partner-feed") == [
            f"Could not read length of partner-feed: {error!r}"
        ]

    def test_unreadable_groups_are_unknown_and_logged(self, caplog):
        self.broker.publish("partner-feed", {"n": 1})

        with (
            patch.object(
                self.redis,
                "xinfo_groups",
                side_effect=redis.ConnectionError("redis down"),
            ),
            caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER),
        ):
            status = self._status()

        assert status.lag is None
        assert status.pending == 0
        [record] = [
            r
            for r in caplog.records
            if r.getMessage()
            == f"Could not read group {self.group} on stream partner-feed"
        ]
        assert record.levelno == logging.DEBUG
        assert str(record.exc_info[1]) == "redis down"

    def test_lag_redis_cannot_report_is_counted_after_the_last_delivered_entry(
        self,
    ):
        _lose_native_lag(self.broker, "partner-feed", self.group)

        status = self._status()

        assert status.lag == 2
        assert status.pending == 1
        assert status.status == "lagging"

    def test_lag_that_cannot_be_counted_is_unknown_and_logged(self, caplog):
        _lose_native_lag(self.broker, "partner-feed", self.group)
        error = redis.ConnectionError("range gone")

        with (
            patch.object(self.redis, "xrange", side_effect=error),
            caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER),
        ):
            status = self._status()

        assert status.lag is None
        assert status.pending == 1
        assert status.status == "unknown"
        assert _messages_about(caplog, "partner-feed") == [
            f"Could not count lag of partner-feed: {error!r}"
        ]


@pytest.mark.redis
@pytest.mark.no_test_domain
class TestRedisPartitionedStatus:
    """``OrderSequencer`` declares ``sequential_by``, so its category is
    published to one ``{category}:{key}`` stream per key and the status sums
    the partitions."""

    @pytest.fixture(autouse=True)
    def setup(self, redis_domain):
        self.domain = redis_domain
        self.broker = redis_domain.brokers["default"]
        self.redis = self.broker.redis_instance
        self.category = Order.meta_.stream_category
        self.group = fqn(OrderSequencer)
        self.streams = (self.category, f"{self.category}:a", f"{self.category}:b")

    def _status(self) -> SubscriptionStatus:
        return _statuses(self.domain)[self.group]

    def _publish(self, key: str, count: int, *, group_at: str | None = "0") -> str:
        partition = f"{self.category}:{key}"
        self.broker.record_partition(self.category, key)
        for n in range(count):
            self.broker.publish(partition, {"key": key, "n": n})
        if group_at is not None:
            self.redis.xgroup_create(partition, self.group, id=group_at)
        return partition

    def _read(self, partition: str, consumer: str, count: int) -> None:
        self.redis.xreadgroup(self.group, consumer, {partition: ">"}, count=count)

    def test_lag_and_length_are_summed_across_partitions(self, caplog):
        self._publish("a", 3)
        self._publish("b", 4)

        with caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER):
            status = self._status()

        assert status.subscription_type == "stream"
        assert status.stream_category == self.category
        assert status.current_position == "2 partition(s)"
        assert status.head_position == "7"
        assert status.lag == 7
        assert status.pending == 0
        assert status.consumer_count == 0
        assert status.status == "lagging"
        assert _messages_about(caplog, *self.streams) == []

    def test_caught_up_partitions_are_ok(self):
        self._publish("a", 2, group_at="$")
        self._publish("b", 1, group_at="$")

        status = self._status()

        assert status.lag == 0
        assert status.pending == 0
        assert status.status == "ok"

    def test_pending_is_summed_and_one_worker_counts_once(self):
        a = self._publish("a", 3)
        b = self._publish("b", 4)
        self._read(a, "worker-1", 2)
        self._read(b, "worker-1", 3)

        status = self._status()

        assert status.pending == 5
        assert status.lag == 2
        assert status.consumer_count == 1

    def test_distinct_workers_are_counted(self):
        a = self._publish("a", 1)
        b = self._publish("b", 1)
        self._read(a, "worker-1", 1)
        self._read(b, "worker-2", 1)

        status = self._status()

        assert status.consumer_count == 2
        assert status.lag == 0
        assert status.pending == 2
        assert status.status == "lagging"

    def test_no_partitions_yet_is_zero_lag(self):
        status = self._status()

        assert status.lag == 0
        assert status.pending == 0
        assert status.head_position == "0"
        assert status.current_position is None
        assert status.status == "ok"

    def test_dlq_depth_is_the_length_of_the_category_dlq(self):
        self._publish("a", 1, group_at="$")
        self.redis.xadd(f"{self.category}:dlq", {"n": 1})

        assert self._status().dlq_depth == 1

    def test_an_unreadable_partition_is_skipped_and_logged(self, caplog):
        """Partition ``a`` was recorded but its stream does not exist, so Redis
        rejects the group read. ``b`` is still counted."""
        self._publish("a", 0, group_at=None)
        b = self._publish("b", 9)
        self._read(b, "worker-1", 1)

        with caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER):
            status = self._status()

        assert status.current_position == "2 partition(s)"
        assert status.lag == 8
        assert status.pending == 1
        assert status.consumer_count == 1
        [record] = [
            r
            for r in caplog.records
            if r.getMessage() == f"Could not read groups of partition {self.category}:a"
        ]
        assert record.levelno == logging.DEBUG
        assert isinstance(record.exc_info[1], redis.ResponseError)

    def test_no_readable_partition_is_unknown(self):
        self._publish("a", 0, group_at=None)

        status = self._status()

        assert status.lag is None
        assert status.status == "unknown"

    def test_another_groups_entries_are_ignored(self):
        """A partition read only by some other group gives no reading of this
        group's lag, and that is unknown, not zero."""
        partition = self._publish("a", 3, group_at=None)
        self.redis.xgroup_create(partition, "someone-else", id="0")
        self.redis.xreadgroup("someone-else", "worker-9", {partition: ">"}, count=1)

        status = self._status()

        assert status.lag is None
        assert status.pending == 0
        assert status.consumer_count == 0
        assert status.status == "unknown"

    def test_group_read_failure_on_one_partition_is_logged(self, caplog):
        self._publish("a", 2)
        self._publish("b", 3)

        with (
            patch.object(
                self.redis,
                "xinfo_groups",
                side_effect=_raise_on(
                    self.redis.xinfo_groups,
                    f"{self.category}:a",
                    redis.ConnectionError("redis down"),
                ),
            ),
            caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER),
        ):
            status = self._status()

        assert status.lag == 3
        [record] = [
            r
            for r in caplog.records
            if r.getMessage() == f"Could not read groups of partition {self.category}:a"
        ]
        assert str(record.exc_info[1]) == "redis down"

    def test_unreadable_consumers_count_nobody_and_are_logged(self, caplog):
        a = self._publish("a", 4)
        self._read(a, "worker-1", 1)
        error = redis.ConnectionError("consumers gone")

        with (
            patch.object(self.redis, "xinfo_consumers", side_effect=error),
            caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER),
        ):
            status = self._status()

        assert status.lag == 3
        assert status.pending == 1
        assert status.consumer_count == 0
        assert _messages_about(caplog, *self.streams) == [
            f"Could not read consumers of {self.category}:a: {error!r}"
        ]

    def test_unreadable_lengths_show_zero_and_are_logged(self, caplog):
        self._publish("a", 2)
        error = redis.ConnectionError("length gone")

        with (
            patch.object(self.redis, "xlen", side_effect=error),
            caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER),
        ):
            status = self._status()

        assert status.head_position == "0"
        assert status.dlq_depth == 0
        assert status.lag == 2
        assert _messages_about(caplog, *self.streams) == [
            f"Could not read length of {self.category}:a: {error!r}",
            f"Could not read DLQ depth of {self.category}: {error!r}",
        ]

    def test_unreadable_partition_index_is_unknown(self, caplog):
        self._publish("a", 2)

        with (
            patch.object(
                self.broker,
                "_partition_keys",
                side_effect=redis.ConnectionError("index gone"),
            ),
            caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER),
        ):
            status = self._status()

        assert status.lag is None
        assert status.status == "unknown"
        assert _messages_about(caplog, *self.streams) == [
            f"Error listing partitions for {self.category}: index gone"
        ]

    def test_lag_redis_cannot_report_is_counted_per_partition(self):
        """A group created at an entry in the middle of a partition has no
        native ``lag`` on Redis 7. That partition's entries after the group's
        last-delivered id are counted and added to the native lag of the
        others."""
        a = self._publish("a", 4, group_at=None)
        second_id = self.redis.xrange(a)[1][0]
        self.redis.xgroup_create(a, self.group, id=second_id)
        self._publish("b", 3)

        status = self._status()

        assert status.lag == 2 + 3
        assert status.status == "lagging"

    def test_partition_lag_that_cannot_be_counted_adds_nothing(self, caplog):
        """Partition ``a`` has no native lag and its count fails, so only ``b``
        is summed. A category whose only partition fails is unknown."""
        a = self._publish("a", 4, group_at=None)
        self.redis.xgroup_create(a, self.group, id=self.redis.xrange(a)[1][0])
        error = redis.ConnectionError("range gone")

        with patch.object(self.redis, "xrange", side_effect=error):
            assert self._status().status == "unknown"

        self._publish("b", 3)
        with (
            patch.object(self.redis, "xrange", side_effect=error),
            caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER),
        ):
            status = self._status()

        assert status.lag == 3
        assert _messages_about(caplog, *self.streams) == [
            f"Could not count lag of {a}: {error!r}"
        ]

    def test_a_group_name_that_is_not_utf8_makes_the_category_unknown(self, caplog):
        """Another client can name a group with bytes that are not UTF-8. The
        partition reader cannot decode the name, and the status reports the
        category as unknown instead of raising."""
        a = self._publish("a", 2)
        self.redis.xgroup_create(a, b"a\xff", id="0")

        with caplog.at_level(logging.DEBUG, logger=STATUS_LOGGER):
            status = self._status()

        assert status.lag is None
        assert status.status == "unknown"
        [message] = [
            r.getMessage()
            for r in caplog.records
            if r.getMessage().startswith(
                f"Error collecting stream subscription status for {self.group}: "
            )
        ]
        assert "can't decode byte 0xff" in message

    def test_an_unpartitioned_category_on_the_same_domain_reads_its_base_stream(
        self,
    ):
        """Partitioning is decided per category: ``AccountWatcher`` declares no
        ``sequential_by`` and is read from its base stream."""
        self._publish("a", 2)
        account_stream = Account.meta_.stream_category
        self.broker.publish(account_stream, {"n": 1})
        first_id, _ = self.broker.get_next(account_stream, fqn(AccountWatcher))

        status = _statuses(self.domain)[fqn(AccountWatcher)]

        assert status.current_position == first_id
        assert status.head_position == "1"


# ---------------------------------------------------------------------------
# reset_checkpoint_to_head
# ---------------------------------------------------------------------------


def _es_status(
    *,
    name: str = "sub",
    handler_name: str = "Handler",
    subscription_type: str = "event_store",
    stream_category: str = "order",
    current_position: str | None = "999",
    head_position: str | None = "0",
    position_stream: str | None = "position-Handler-order",
) -> SubscriptionStatus:
    return SubscriptionStatus(
        name=name,
        handler_name=handler_name,
        subscription_type=subscription_type,
        stream_category=stream_category,
        lag=0,
        pending=0,
        current_position=current_position,
        head_position=head_position,
        status="ok",
        consumer_count=0,
        dlq_depth=0,
        position_stream=position_stream,
    )


def _seed_checkpoint(store, position_stream: str, position: int) -> None:
    """Write a ``Read`` position record, the shape a live subscription writes."""
    store._write(position_stream, "Read", {"position": position})


class TestResetCheckpointToHead:
    def test_writes_status_head_to_checkpoint_stream(self, test_domain):
        """The reset writes the head recorded on the status (from verification),
        readable back from the checkpoint stream, in the same ``Read`` record shape
        the runtime writes. It uses that recorded head, not a fresh store read, so
        the live store head deliberately differs here to pin which one is used."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            # Live store head for `order` is 2; the status carries head 7 from
            # verification. The reset must write 7, not the live 2.
            store._write("order-1", "Placed", {"n": 1})
            store._write("order-1", "Placed", {"n": 2})
            assert store.stream_head_position("order") == 2
            # A stale checkpoint sitting well past the head.
            _seed_checkpoint(store, "position-Handler-order", 99)

        status = _es_status(
            stream_category="order",
            current_position="99",
            head_position="7",
            position_stream="position-Handler-order",
        )
        new_position = reset_checkpoint_to_head(test_domain, status)

        assert new_position == 7
        with test_domain.domain_context():
            last = store._read_last_message("position-Handler-order")
        assert last is not None
        assert last["data"]["position"] == 7
        # Same record type the runtime EventStoreSubscription.write_position writes.
        assert last["type"] == "Read"

    def test_reset_then_verify_reads_consistent(self, test_domain):
        """Round-trip: after a reset, the subscription verifies as
        consistent against the same head."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            store._write("order-1", "Placed", {"n": 1})
            head = store.stream_head_position("order")
            _seed_checkpoint(store, "position-RT-order", head + 5)

        stale = _es_status(
            stream_category="order",
            current_position=str(head + 5),
            head_position=str(head),
            position_stream="position-RT-order",
        )
        assert _verdict(stale) == "beyond_head"

        reset_checkpoint_to_head(test_domain, stale)

        with test_domain.domain_context():
            written = store._read_last_message("position-RT-order")["data"]["position"]
        verified = _es_status(
            stream_category="order",
            current_position=str(written),
            head_position=str(head),
            position_stream="position-RT-order",
        )
        assert _verdict(verified) == "consistent"

    def test_empty_stream_resets_to_minus_one(self, test_domain):
        """A restored stream with no events has head ``-1``; the reset writes that,
        which sends the subscription back to the start of the stream."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = store.stream_head_position("empty")
        assert head == -1

        status = _es_status(
            stream_category="empty",
            current_position="4",
            head_position="-1",
            position_stream="position-Handler-empty",
        )
        new_position = reset_checkpoint_to_head(test_domain, status)

        assert new_position == -1
        with test_domain.domain_context():
            last = store._read_last_message("position-Handler-empty")
        assert last is not None
        assert last["data"]["position"] == -1

    def test_raises_for_non_event_store_status(self, test_domain):
        status = _es_status(subscription_type="broker")
        with pytest.raises(ValueError, match="not an event-store"):
            reset_checkpoint_to_head(test_domain, status)

    def test_raises_when_checkpoint_stream_missing(self, test_domain):
        status = _es_status(position_stream=None)
        with pytest.raises(ValueError, match="no checkpoint stream"):
            reset_checkpoint_to_head(test_domain, status)

    def test_raises_when_head_position_unknown(self, test_domain):
        status = _es_status(head_position=None)
        with pytest.raises(ValueError, match="stream head is unknown"):
            reset_checkpoint_to_head(test_domain, status)

    def test_raises_when_head_position_not_numeric(self, test_domain):
        status = _es_status(head_position="abc")
        with pytest.raises(ValueError, match="not a number"):
            reset_checkpoint_to_head(test_domain, status)

    @pytest.mark.no_test_domain
    def test_raises_when_store_not_configured(self):
        """An uninitialized domain has no event store to write to."""
        domain = Domain(name="NoStore")

        status = _es_status()
        with pytest.raises(ValueError, match="no.*event store"):
            reset_checkpoint_to_head(domain, status)


class TestPerformResetsScope:
    """End-to-end scope check on real infrastructure: a reset run touches only
    the beyond-head checkpoints and leaves at-or-below-head and unknown ones
    alone."""

    def test_only_beyond_head_checkpoint_is_modified(self, test_domain):
        store = test_domain.event_store.store
        with test_domain.domain_context():
            store._write("order-1", "Placed", {"n": 1})
            store._write("payment-1", "Paid", {"n": 1})
            order_head = store.stream_head_position("order")
            payment_head = store.stream_head_position("payment")

            # A healthy checkpoint sitting exactly at head, an unknown one, and a
            # stale one pointing past head.
            _seed_checkpoint(store, "position-Healthy-payment", payment_head)
            _seed_checkpoint(store, "position-Unknown-order", 3)
            _seed_checkpoint(store, "position-Bad-order", order_head + 5)
            healthy_before = store._read_last_message("position-Healthy-payment")
            unknown_before = store._read_last_message("position-Unknown-order")

        bad = _es_status(
            name="bad",
            handler_name="Bad",
            stream_category="order",
            current_position=str(order_head + 5),
            head_position=str(order_head),
            position_stream="position-Bad-order",
        )
        healthy = _es_status(
            name="healthy",
            handler_name="Healthy",
            stream_category="payment",
            current_position=str(payment_head),
            head_position=str(payment_head),
            position_stream="position-Healthy-payment",
        )
        # An unknown row: its positions could not be parsed, so it must be skipped.
        unknown = _es_status(
            name="unknown",
            handler_name="Unknown",
            stream_category="order",
            current_position=None,
            head_position=None,
            position_stream="position-Unknown-order",
        )

        resets, failures = _perform_resets(
            test_domain,
            [bad, healthy, unknown],
            ["beyond_head", "consistent", "unknown"],
        )

        assert failures == []
        assert len(resets) == 1
        assert resets[0]["name"] == "bad"
        assert resets[0]["previous_position"] == str(order_head + 5)
        assert resets[0]["new_position"] == str(order_head)

        with test_domain.domain_context():
            bad_after = store._read_last_message("position-Bad-order")
            healthy_after = store._read_last_message("position-Healthy-payment")
            unknown_after = store._read_last_message("position-Unknown-order")

        # The beyond-head checkpoint advanced to head.
        assert bad_after["data"]["position"] == order_head
        # The healthy and unknown checkpoints got no new record: same
        # global_position (a stray append would raise it), same value.
        assert healthy_after["global_position"] == healthy_before["global_position"]
        assert healthy_after["data"]["position"] == payment_head
        assert unknown_after["global_position"] == unknown_before["global_position"]
        assert unknown_after["data"]["position"] == 3


# ---------------------------------------------------------------------------
# Recovery-tracking checkpoints
# ---------------------------------------------------------------------------


def _rec_status(
    *,
    name: str = "sub",
    handler_name: str = "Handler",
    subscription_type: str = "event_store",
    stream_category: str = "order",
    head_position: str | None = "2",
    recovery_checkpoint_stream: str | None = "recovery-checkpoint-Handler-order",
    failed_positions_stream: str | None = "failed-Handler-order",
) -> SubscriptionStatus:
    return SubscriptionStatus(
        name=name,
        handler_name=handler_name,
        subscription_type=subscription_type,
        stream_category=stream_category,
        lag=0,
        pending=0,
        current_position=head_position,
        head_position=head_position,
        status="ok",
        consumer_count=0,
        dlq_depth=0,
        recovery_checkpoint_stream=recovery_checkpoint_stream,
        failed_positions_stream=failed_positions_stream,
    )


def _seed_recovery_checkpoint(
    store, recovery_stream: str, watermark: int, unresolved: dict, category="order"
) -> None:
    """Write a ``Checkpoint`` record, the shape a live subscription writes."""
    store._write(
        recovery_stream,
        "Checkpoint",
        {"watermark": watermark, "unresolved": unresolved},
        metadata={
            "headers": {
                "id": str(uuid4()),
                "type": "Checkpoint",
                "time": "2026-01-01T00:00:00+00:00",
                "stream": recovery_stream,
            },
            "domain": {
                "kind": MessageType.READ_POSITION.value,
                "origin_stream": category,
            },
        },
    )


def _seed_failed_record(
    store,
    failed_stream: str,
    record_type: str,
    position: int,
    category="order",
    stream_name=None,
    stream_position=None,
) -> None:
    """Write a ``Failed``/``Resolved``/``Exhausted`` record to the failed stream.

    ``stream_name``/``stream_position`` default to ``None`` so the recovery re-read
    falls back to the category stream at ``position``; pass a specific stream to
    exercise the specific-stream re-read path.
    """
    store._write(
        failed_stream,
        record_type,
        {
            "position": position,
            "message_type": "Placed",
            "message_id": "abc",
            "retry_count": 1,
            "stream_name": stream_name,
            "stream_position": stream_position,
        },
        metadata={
            "headers": {
                "id": str(uuid4()),
                "type": record_type,
                "time": "2026-01-01T00:00:00+00:00",
                "stream": failed_stream,
            },
            "domain": {
                "kind": MessageType.READ_POSITION.value,
                "origin_stream": category,
            },
        },
    )


def _seed_event(
    store, stream_name: str, event_type: str, data: dict, category="order"
) -> None:
    """Write a domain event to a specific stream, with the metadata a real event
    carries so ``store.read`` can deserialize it back (the recovery re-read does).
    """
    store._write(
        stream_name,
        event_type,
        data,
        metadata={
            "headers": {
                "id": str(uuid4()),
                "type": event_type,
                "time": "2026-01-01T00:00:00+00:00",
                "stream": stream_name,
            },
            "domain": {
                "kind": MessageType.EVENT.value,
                "origin_stream": category,
            },
        },
    )


class TestReconstructUnresolved:
    """The shared reconstruction both the runtime rebuild and ``protean recover``
    call: checkpoint snapshot merged with failed-stream records after the
    watermark."""

    def test_snapshot_only(self, test_domain):
        store = test_domain.event_store.store
        with test_domain.domain_context():
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "5": {
                        "retry_count": 1,
                        "stream_name": "order-9",
                        "stream_position": 0,
                    },
                },
            )
            unresolved, watermark, _read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
            )

        assert set(unresolved) == {5}
        assert watermark == 0

    def test_failed_stream_after_watermark_is_merged(self, test_domain):
        store = test_domain.event_store.store
        with test_domain.domain_context():
            # Snapshot at watermark 0 with one position; the failed stream adds a
            # second and a terminal record retires a third.
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "3": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                    "8": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )
            _seed_failed_record(store, "failed-Handler-order", "Failed", 9)
            _seed_failed_record(store, "failed-Handler-order", "Resolved", 8)

            unresolved, watermark, _read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
            )

        # 3 stays (snapshot), 9 added (Failed), 8 removed (Resolved). Watermark
        # advances past the two failed-stream records read (positions 0, 1 -> 2).
        assert set(unresolved) == {3, 9}
        assert watermark == 2

    def test_no_checkpoint_reads_failed_stream_from_zero(self, test_domain):
        store = test_domain.event_store.store
        with test_domain.domain_context():
            _seed_failed_record(store, "failed-Handler-order", "Failed", 4)
            unresolved, watermark, _read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
            )

        assert set(unresolved) == {4}
        assert watermark == 1

    def test_pages_through_the_whole_stream(self, test_domain):
        """The failed stream is paged in full, not capped: a record past the first
        page is still merged, so a long failure history is not silently truncated.
        """
        store = test_domain.event_store.store
        with test_domain.domain_context():
            for pos in (4, 5, 6, 7, 8):
                _seed_failed_record(store, "failed-Handler-order", "Failed", pos)
            # A tiny page size forces several pages; every record must still merge.
            unresolved, watermark, records_read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
                page_size=2,
            )

        assert set(unresolved) == {4, 5, 6, 7, 8}
        assert records_read == 5
        # Watermark advances past the last record (per-stream positions 0..4 -> 5).
        assert watermark == 5

    def test_stale_high_watermark_keeps_snapshot_and_does_not_resurrect(
        self, test_domain
    ):
        """A restore can leave the checkpoint watermark ahead of the failed stream.
        Reconstruction is best-effort: it trusts the snapshot and reads only from
        the stored watermark, so it does not re-read a surviving old failed record
        below the watermark. That old record's terminal (Resolved/Exhausted) row
        may have been truncated, so re-reading it would resurrect an already-
        resolved position. Here a resolved position (5, whose Resolved was rolled
        back) stays out of the set and the snapshot is returned unchanged."""

        store = test_domain.event_store.store
        with test_domain.domain_context():
            # A surviving old Failed(5) row at per-stream position 0. Its Resolved
            # row was rolled back by the restore, so it is not in the stream.
            _seed_failed_record(store, "failed-Handler-order", "Failed", 5)
            # The checkpoint watermark (10) is past that tail; its snapshot excludes
            # 5 (it was resolved before the restore).
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=10,
                unresolved={
                    "99": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )
            unresolved, watermark, records_read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
            )

        # 5 is NOT resurrected (the old survivor below the watermark is not
        # re-read); the snapshot (99) is returned unchanged.
        assert set(unresolved) == {99}
        assert watermark == 10
        assert records_read == 0

    def test_merges_records_after_watermark(self, test_domain):
        """The normal case: the snapshot is kept and only records after the
        watermark are merged. A record at or below the watermark is not re-read."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            # Three failed-stream records at per-stream positions 0, 1, 2.
            _seed_failed_record(store, "failed-Handler-order", "Failed", 7)
            _seed_failed_record(store, "failed-Handler-order", "Failed", 8)
            _seed_failed_record(store, "failed-Handler-order", "Failed", 9)
            # Watermark 2: positions 0, 1 are already accounted for; only the
            # record at position 2 (global 9) is after it.
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=2,
                unresolved={
                    "5": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )
            unresolved, watermark, records_read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
            )

        # Snapshot (5) kept; only the record after the watermark (9) merged in;
        # positions 7, 8 (at/below the watermark) not re-read.
        assert set(unresolved) == {5, 9}
        assert watermark == 3
        assert records_read == 1

    def test_float_watermark_is_read_from_zero(self, test_domain):
        """A corrupt checkpoint with a float watermark is not trusted as a read
        cursor. Used directly, 1.5 would read from position >= 1.5 and skip the
        records at positions 0 and 1, returning an incomplete set as if clean.
        Instead the whole failed stream is re-read from the start."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            # Two failed records at per-stream positions 0 and 1.
            _seed_failed_record(store, "failed-Handler-order", "Failed", 3)
            _seed_failed_record(store, "failed-Handler-order", "Failed", 4)
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=1.5,
                unresolved={},
            )
            unresolved, watermark, records_read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
            )

        # Both records are read, not skipped; the watermark is a real int again.
        assert set(unresolved) == {3, 4}
        assert watermark == 2
        assert records_read == 2

    def test_bool_watermark_is_read_from_zero(self, test_domain):
        """``bool`` is an ``int`` subclass, so a ``True`` watermark passes a plain
        int check yet reads from position >= 1 and skips position 0. It is treated
        as corrupt and the failed stream is re-read from the start."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            # One failed record at per-stream position 0.
            _seed_failed_record(store, "failed-Handler-order", "Failed", 3)
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=True,
                unresolved={},
            )
            unresolved, watermark, records_read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
            )

        # Position 0 is read, not skipped past by True (== 1).
        assert set(unresolved) == {3}
        assert watermark == 1
        assert records_read == 1

    @pytest.mark.no_test_domain
    def test_record_without_position_raises(self):
        """A failed record whose last page entry carries no per-stream position
        cannot advance the cursor. Rather than silently return a partial scan as
        if complete, it raises so the CLI reports the subscription unverified."""
        store = MagicMock()
        store._read_last_message.return_value = None  # no checkpoint
        msg = MagicMock()
        msg.data.get.side_effect = lambda k, default=None: {
            "position": 5,
            "retry_count": 0,
            "stream_name": None,
            "stream_position": None,
        }.get(k, default)
        msg.metadata.headers.type = "Failed"
        # A full page (page_size 1) whose only record lacks a per-stream position.
        msg.metadata.event_store.position = None
        store.read.return_value = [msg]

        with pytest.raises(ValueError, match="no per-stream position"):
            reconstruct_unresolved(store, "rec-stream", "failed-stream", page_size=1)

    @pytest.mark.no_test_domain
    def test_record_without_position_on_short_page_does_not_raise(self):
        """A positionless trailing record on a short (final) page does not raise:
        pagination is already complete, so no cursor advance is needed. The set is
        returned best-effort so one malformed trailing record does not fail
        subscription startup. (A full page in this state still raises.)"""
        store = MagicMock()
        store._read_last_message.return_value = None  # no checkpoint
        msg = MagicMock()
        msg.data.get.side_effect = lambda k, default=None: {
            "position": 5,
            "retry_count": 0,
            "stream_name": None,
            "stream_position": None,
        }.get(k, default)
        msg.metadata.headers.type = "Failed"
        # A short page (one record, page_size 2) whose last record has no
        # per-stream position: pagination is done, so this stops without raising.
        msg.metadata.event_store.position = None
        store.read.return_value = [msg]

        unresolved, watermark, records_read = reconstruct_unresolved(
            store, "rec-stream", "failed-stream", page_size=2
        )

        # The record is still merged; the watermark does not advance (no position
        # to advance to); no exception.
        assert set(unresolved) == {5}
        assert watermark == 0
        assert records_read == 1

    @pytest.mark.no_test_domain
    def test_non_advancing_cursor_raises(self):
        """A full page whose last record does not move the cursor forward (a
        non-monotonic or duplicate position) would loop forever; it raises so the
        CLI reports the subscription unverified instead of hanging."""
        store = MagicMock()
        store._read_last_message.return_value = None  # cursor starts at 0
        msg = MagicMock()
        msg.data.get.side_effect = lambda k, default=None: {
            "position": 9,
            "retry_count": 0,
            "stream_name": None,
            "stream_position": None,
        }.get(k, default)
        msg.metadata.headers.type = "Failed"
        # position + 1 == 0, not greater than the starting cursor 0: no progress.
        msg.metadata.event_store.position = -1
        # A full page that always comes back the same would loop without the guard.
        store.read.return_value = [msg]

        with pytest.raises(ValueError, match="did not advance"):
            reconstruct_unresolved(store, "rec-stream", "failed-stream", page_size=1)


class TestCheckpointAheadOfFailedStream:
    """The shared inconsistency check both the runtime rebuild and the CLI use."""

    def test_no_checkpoint_is_not_ahead(self, test_domain):
        store = test_domain.event_store.store
        assert checkpoint_ahead_of_failed_stream(store, "rec", "failed") is False

    def test_non_integer_watermark_is_not_ahead(self, test_domain):
        """A corrupt checkpoint whose watermark is not an int is left for the
        reconstruction to handle, not read as ahead-of-stream (which would compare
        a string to an int and raise)."""
        store = test_domain.event_store.store
        store._write("rec", "Checkpoint", {"watermark": "oops"})
        assert checkpoint_ahead_of_failed_stream(store, "rec", "failed") is False


class TestCollectRecoveryCheckpointStatuses:
    def _seed_order_head(self, store) -> int:
        _seed_event(store, "order-1", "Placed", {"n": 1})
        _seed_event(store, "order-1", "Placed", {"n": 2})
        return store.stream_head_position("order")

    def test_flags_beyond_head_unresolved_entry(self, test_domain):
        """An unresolved entry past the head is named as stale."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    str(head + 3): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                    "1": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].name == "sub"
        assert findings[0].handler_name == "Handler"
        assert findings[0].verdict == "stale"
        assert findings[0].stale_positions == [head + 3]
        assert findings[0].head_position == head

    def test_checkpoint_ahead_of_failed_stream_is_unknown(self, test_domain):
        """A restore can leave the checkpoint watermark ahead of the failed
        stream it references. That state cannot be reconstructed reliably (the
        failed stream reuses positions after the truncation and the snapshot has
        no resolved-position tombstones), so the subscription is reported
        ``unknown`` rather than verified. Reset already refuses a non-stale
        finding, so it never touches an unverifiable checkpoint."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            # Watermark 10 sits past the (empty) failed stream's tail (-1): the
            # checkpoint is ahead of the stream it references.
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=10,
                unresolved={
                    str(head + 3): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].verdict == "unknown"
        assert findings[0].stale_positions == []

    def test_ahead_checkpoint_with_surviving_failed_row_is_unknown(self, test_domain):
        """Copilot's resurrection case, reported honestly. The history was
        ``Failed(5), Resolved(5)`` (position 5 resolved); a restore kept the
        checkpoint (watermark past both rows, snapshot excludes 5) but truncated
        the failed stream to the first row only. Rather than replay ``Failed(5)``
        and resurrect a resolved position (a duplicate delivery, or a false stale
        report), the inconsistent state is reported ``unknown``."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            # Only the surviving Failed(5) row (per-stream position 0); its
            # Resolved(5) row was rolled back.
            _seed_failed_record(store, "failed-Handler-order", "Failed", 5)
            # Checkpoint watermark 2 is past the truncated tail (0); its snapshot
            # correctly excludes 5.
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=2,
                unresolved={},
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].verdict == "unknown"
        # 5 is neither resurrected as unresolved nor falsely reported stale.
        assert findings[0].stale_positions == []

    def test_watermark_at_tail_is_not_flagged_unknown(self, test_domain):
        """A checkpoint whose watermark sits at the failed stream's tail+1 is the
        normal, consistent case, not an inconsistent restore. It is verified (its
        stale entry is reported stale), not reported unknown. Guards the ahead-of
        check against flagging a healthy checkpoint."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            # Two failed-stream records -> tail per-stream position 1.
            _seed_failed_record(store, "failed-Handler-order", "Failed", 7)
            _seed_failed_record(store, "failed-Handler-order", "Failed", 8)
            # Watermark 2 == tail(1)+1: consistent, not ahead of the stream.
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=2,
                unresolved={
                    str(head + 3): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].verdict == "stale"
        assert findings[0].stale_positions == [head + 3]

    def test_empty_category_head_minus_one_flags_every_tracked_position(
        self, test_domain
    ):
        """The maximal rollback leaves an empty category (head ``-1``); every
        tracked position is then past the head and flagged."""

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = store.stream_head_position("order")
            assert head == -1
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "0": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position="-1")]
        )

        assert len(findings) == 1
        assert findings[0].stale_positions == [0]

    def test_category_entries_with_present_messages_not_flagged(self, test_domain):
        """Entries re-read through the category stream whose messages are still
        present are not stale. Both a below-head position (0) and an at-head
        position resolve here because their category messages exist; staleness is
        decided by the re-read finding nothing, not by comparing to the head."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    str(head): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                    "0": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert findings == []

    def test_stale_only_in_failed_stream_is_caught(self, test_domain):
        """A position that began failing after the last checkpoint lives only in
        the failed stream; reconstruction merges it and the re-read (no specific
        stream recorded, so the category stream at its position) finds nothing."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            _seed_recovery_checkpoint(
                store, "recovery-checkpoint-Handler-order", watermark=0, unresolved={}
            )
            _seed_failed_record(store, "failed-Handler-order", "Failed", head + 7)

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].stale_positions == [head + 7]

    def test_removed_specific_stream_below_head_is_flagged(self, test_domain):
        """A failed record points at a specific stream a restore removed, but
        another aggregate has a later event so the category head stays above it.
        Comparing the global position to the head would miss it; re-reading the
        specific stream catches it."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)  # order-1 holds events; head == 2
            # A tracked position at global_position 1 (<= head) whose own stream
            # `order-removed` no longer exists.
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "1": {
                        "retry_count": 1,
                        "stream_name": "order-removed",
                        "stream_position": 0,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].verdict == "stale"
        assert findings[0].stale_positions == [1]

    def test_present_specific_stream_is_not_flagged(self, test_domain):
        """A tracked position whose specific stream still holds its message is
        healthy and left unreported, even below the head."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)  # order-1 holds events at pos 0, 1
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "1": {
                        "retry_count": 1,
                        "stream_name": "order-1",
                        "stream_position": 0,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert findings == []

    @pytest.mark.no_test_domain
    def test_non_event_store_subscription_skipped(self):
        # A broker subscription is skipped before any domain access.

        findings = collect_recovery_checkpoint_statuses(
            None, [_rec_status(subscription_type="broker")]
        )
        assert findings == []

    def test_scans_when_read_position_head_is_unknown(self, test_domain):
        """The recovery lane reads the head itself, so it still runs and flags a
        stale entry when the read-position collection failed and left the status
        with no head (an unreadable read-position checkpoint must not hide
        readable recovery tracking)."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)  # store is readable
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    str(head + 3): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )

        # head_position None models a read-position collection that failed but
        # still carried the derived recovery stream names.
        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=None)]
        )

        assert len(findings) == 1
        assert findings[0].verdict == "stale"
        assert findings[0].stale_positions == [head + 3]
        # The head was read from the store, not taken from the (unknown) status.
        assert findings[0].head_position == head

    @pytest.mark.no_test_domain
    def test_missing_recovery_streams_skipped(self):
        # A status with no recovery streams is skipped before any domain access.

        findings = collect_recovery_checkpoint_statuses(
            None, [_rec_status(recovery_checkpoint_stream=None)]
        )
        assert findings == []

    def test_no_tracking_returns_no_finding(self, test_domain):
        """An event-store subscription that never failed a position has no
        recovery streams to read, so it is not a finding."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )
        assert findings == []

    def test_store_read_failure_is_reported_unknown(self, test_domain):
        """A store read that raises is reported as an unverified finding, not
        crashed and not silently folded into clean."""
        store = test_domain.event_store.store
        # The head read also fails, so it falls back to the status head; a
        # non-numeric status head (a foreign store) is reported as -1 rather than
        # crashing the int parse.
        with (
            patch.object(store, "_read_last_message", side_effect=RuntimeError("boom")),
            patch.object(
                store, "stream_head_position", side_effect=RuntimeError("head boom")
            ),
        ):
            findings = collect_recovery_checkpoint_statuses(
                test_domain, [_rec_status(head_position="abc")]
            )
        assert len(findings) == 1
        assert findings[0].verdict == "unknown"
        assert findings[0].stale_positions == []
        assert findings[0].head_position == -1

    def test_reuses_status_head_and_skips_the_store_read(self, test_domain):
        """When the read-position collection already recorded a head, the recovery
        lane reuses it and does not pay a second (potentially expensive) store
        head read; the stale entry is still reported."""
        store = test_domain.event_store.store
        # A checkpoint tracking one position, an empty failed stream, and no
        # event at that position (message gone -> stale).
        with test_domain.domain_context():
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "5": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    }
                },
            )

        # Would raise if the head were read; the test proves it is not.
        with patch.object(
            store, "stream_head_position", side_effect=RuntimeError("head boom")
        ) as head_read:
            findings = collect_recovery_checkpoint_statuses(
                test_domain, [_rec_status(head_position="7")]
            )

        assert len(findings) == 1
        assert findings[0].verdict == "stale"
        assert findings[0].stale_positions == [5]
        # The status head (7) was reused; the store head was never read.
        assert findings[0].head_position == 7
        head_read.assert_not_called()

    @pytest.mark.no_test_domain
    def test_store_not_configured_is_reported_unknown(self):
        """A domain with no event store yields an unverified finding, not silence
        and not a raise."""
        domain = Domain(name="NoStore")
        findings = collect_recovery_checkpoint_statuses(domain, [_rec_status()])
        assert len(findings) == 1
        assert findings[0].verdict == "unknown"

    def test_corrupt_checkpoint_record_is_reported_unknown(self, test_domain):
        """A restore can leave a checkpoint record whose ``data`` is malformed;
        the reconstruction raises and the subscription is reported unverified."""
        store = test_domain.event_store.store
        # ``unresolved`` is a list, so reading its entries as a mapping raises.
        with test_domain.domain_context():
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved=["not", "a", "dict"],
            )
        findings = collect_recovery_checkpoint_statuses(test_domain, [_rec_status()])
        assert len(findings) == 1
        assert findings[0].verdict == "unknown"

    def test_read_error_on_one_position_keeps_confirmed_stale(self, test_domain):
        """A re-read that raises for one position must not discard the stale
        entries already confirmed for the same subscription."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            # A metadata-less message makes ``store.read`` raise on that stream.
            store._write("order-corrupt", "Placed", {"n": 1})
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "5": {
                        "retry_count": 1,
                        "stream_name": "order-removed",
                        "stream_position": 0,
                    },
                    "6": {
                        "retry_count": 1,
                        "stream_name": "order-corrupt",
                        "stream_position": 0,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        # 5 (order-removed) is confirmed gone and reported; 6's read raised, so it
        # is skipped rather than dropping 5.
        assert len(findings) == 1
        assert findings[0].verdict == "stale"
        assert findings[0].stale_positions == [5]

    def test_read_error_with_no_confirmed_stale_is_unknown(self, test_domain):
        """When the only re-read that could run raises and nothing is confirmed
        stale, the subscription is reported unverified rather than clean."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            store._write("order-corrupt", "Placed", {"n": 1})
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "6": {
                        "retry_count": 1,
                        "stream_name": "order-corrupt",
                        "stream_position": 0,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].verdict == "unknown"

    def test_malformed_failed_record_is_skipped(self, test_domain):
        """A failed record missing its position is skipped, not merged as a
        phantom entry."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            # A record whose data carries no position at all.
            store._write(
                "failed-Handler-order",
                "Failed",
                {"position": None, "retry_count": 1},
                metadata={
                    "headers": {
                        "id": "x",
                        "type": "Failed",
                        "time": "2026-01-01T00:00:00+00:00",
                        "stream": "failed-Handler-order",
                    },
                    "domain": {
                        "kind": MessageType.READ_POSITION.value,
                        "origin_stream": "order",
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )
        assert findings == []

    def test_collect_does_not_modify_any_stream(self, test_domain):
        """A verify-only collection never writes to the recovery stream."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    str(head + 3): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )
            before = store._read_last_message("recovery-checkpoint-Handler-order")

        collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        with test_domain.domain_context():
            after = store._read_last_message("recovery-checkpoint-Handler-order")

        # No new record appended: same global_position, same content.
        assert after["global_position"] == before["global_position"]
        assert after["data"] == before["data"]


class TestResetRecoveryCheckpoint:
    def _seed_order_head(self, store) -> int:
        _seed_event(store, "order-1", "Placed", {"n": 1})
        _seed_event(store, "order-1", "Placed", {"n": 2})
        return store.stream_head_position("order")

    def test_drops_stale_keeps_healthy_and_reverifies_clean(self, test_domain):
        """Round-trip: the reset drops the entry whose message is gone (head+3, the
        category re-read finds nothing) and keeps the one whose message is still
        present (position 1, re-read from its specific stream order-1), and a later
        collection finds nothing."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    str(head + 3): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                    "1": {
                        "retry_count": 2,
                        "stream_name": "order-1",
                        "stream_position": 0,
                    },
                },
            )

        status = _rec_status(head_position=str(head))
        findings = collect_recovery_checkpoint_statuses(test_domain, [status])
        assert findings[0].stale_positions == [head + 3]

        cleared = reset_recovery_checkpoint(test_domain, findings[0])
        assert cleared == [head + 3]

        # The healthy entry survived, the stale one is gone.
        with test_domain.domain_context():
            last = store._read_last_message("recovery-checkpoint-Handler-order")
        assert set(last["data"]["unresolved"]) == {"1"}

        # A later collection is clean.
        assert collect_recovery_checkpoint_statuses(test_domain, [status]) == []

    def test_reset_holds_when_stale_only_in_failed_stream(self, test_domain):
        """A stale position present only in the failed stream is cleared and the
        watermark is advanced past it, so a later collection stays clean."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            _seed_recovery_checkpoint(
                store, "recovery-checkpoint-Handler-order", watermark=0, unresolved={}
            )
            _seed_failed_record(store, "failed-Handler-order", "Failed", head + 7)

        status = _rec_status(head_position=str(head))
        findings = collect_recovery_checkpoint_statuses(test_domain, [status])
        assert findings[0].stale_positions == [head + 7]

        reset_recovery_checkpoint(test_domain, findings[0])

        # The rewritten checkpoint carries a watermark past the failed record, so
        # reconstruction no longer re-reads it.
        with test_domain.domain_context():
            last = store._read_last_message("recovery-checkpoint-Handler-order")
        assert last["data"]["watermark"] == 1
        assert last["data"]["unresolved"] == {}
        assert collect_recovery_checkpoint_statuses(test_domain, [status]) == []

    @pytest.mark.no_test_domain
    def test_raises_when_store_not_configured(self):
        domain = Domain(name="NoStore")

        finding = RecoveryCheckpointStatus(
            name="sub",
            handler_name="Handler",
            stream_category="order",
            recovery_checkpoint_stream="recovery-checkpoint-Handler-order",
            head_position=2,
            verdict="stale",
            stale_positions=[5],
            unresolved={
                5: {"retry_count": 1, "stream_name": None, "stream_position": None}
            },
            watermark=0,
        )
        with pytest.raises(ValueError, match="no event store"):
            reset_recovery_checkpoint(domain, finding)

    def test_refuses_to_reset_an_unknown_finding(self, test_domain):
        """An unknown finding carries an empty snapshot, so resetting it would
        wipe the subscription's real recovery state. It is refused, and the real
        checkpoint is left untouched."""
        store = test_domain.event_store.store
        with test_domain.domain_context():
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=3,
                unresolved={
                    "5": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    }
                },
            )
            before = store._read_last_message("recovery-checkpoint-Handler-order")

        finding = RecoveryCheckpointStatus(
            name="sub",
            handler_name="Handler",
            stream_category="order",
            recovery_checkpoint_stream="recovery-checkpoint-Handler-order",
            head_position=2,
            verdict="unknown",
            stale_positions=[],
            unresolved={},
            watermark=0,
        )
        with pytest.raises(ValueError, match="not 'stale'"):
            reset_recovery_checkpoint(test_domain, finding)

        # The real snapshot was not overwritten with the finding's empty one.
        with test_domain.domain_context():
            after = store._read_last_message("recovery-checkpoint-Handler-order")
        assert after["data"] == before["data"]
