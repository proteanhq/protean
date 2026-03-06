"""Test external dispatch of published events via outbox.

Covers the full lifecycle:
- Config defaults for ``external_brokers``
- Outbox row creation (internal + external) during UoW commit
- ``target_broker`` filtering in ``find_unprocessed()``
- ``Message.to_external_dict()`` envelope stripping
- ``OutboxProcessor`` in external mode (trace events, envelope, lane skipping)
- Engine creation of external OutboxProcessors
- Validation warning for published events without external brokers
- Backward compatibility when no external brokers are configured
- Multiple external brokers
"""

import asyncio
import logging

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.domain import Domain
from protean.fields import Float, Identifier, Integer, String
from protean.server import Engine
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageHeaders,
    Metadata,
)
from protean.utils.outbox import Outbox, OutboxStatus


# ---------------------------------------------------------------------------
# Domain elements
# ---------------------------------------------------------------------------


class Order(BaseAggregate):
    customer_id: Identifier()
    total: Float()

    @classmethod
    def place(cls, customer_id: str, total: float):
        order = cls(customer_id=customer_id, total=total)
        order.raise_(
            OrderPlaced(order_id=str(order.id), customer_id=customer_id, total=total)
        )
        return order

    def cancel(self):
        self.raise_(OrderCancelled(order_id=str(self.id)))


class OrderPlaced(BaseEvent):
    """Published event — part of the bounded context's public API."""

    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


class OrderCancelled(BaseEvent):
    """Internal event — not published externally."""

    order_id: Identifier(required=True)


class Inventory(BaseAggregate):
    sku: String(max_length=50, required=True)
    qty: Integer(default=0)

    def adjust(self, delta: int):
        self.qty += delta
        self.raise_(StockAdjusted(sku=self.sku, qty=self.qty))


class StockAdjusted(BaseEvent):
    sku: String(required=True)
    qty: Integer(required=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_domain():
    """Domain with outbox enabled and one external broker configured."""
    domain = Domain(name="Test")
    domain.config["enable_outbox"] = True
    domain.config["server"]["default_subscription_type"] = "stream"
    domain.config["outbox"]["external_brokers"] = ["external"]
    domain.config["brokers"]["external"] = {"provider": "inline"}

    with domain.domain_context():
        yield domain


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order, published=True)
    test_domain.register(OrderCancelled, part_of=Order)
    test_domain.register(Inventory)
    test_domain.register(StockAdjusted, part_of=Inventory)
    test_domain.init(traverse=False)


# ===================================================================
# Config defaults
# ===================================================================


class TestConfigDefaults:
    def test_external_brokers_defaults_to_empty_list(self):
        from protean.domain.config import _default_config

        assert _default_config()["outbox"]["external_brokers"] == []


# ===================================================================
# UoW outbox row creation
# ===================================================================


@pytest.mark.database
class TestExternalOutboxRows:
    """UoW creates one internal row per event, plus one external row
    per external broker for each ``published=True`` event."""

    def test_published_event_creates_internal_and_external_rows(self, test_domain):
        order = Order.place(customer_id="C1", total=99.0)
        outbox_repo = test_domain._get_outbox_repo("default")

        with UnitOfWork():
            test_domain.repository_for(Order).add(order)

        placed = [
            r for r in outbox_repo.find_unprocessed() if r.type == OrderPlaced.__type__
        ]

        assert len(placed) == 2
        brokers = sorted(r.target_broker for r in placed)
        assert brokers == ["default", "external"]

        # Same message_id and payload on both rows
        assert placed[0].message_id == placed[1].message_id
        assert placed[0].data == placed[1].data

    def test_non_published_event_only_internal_row(self, test_domain):
        order = Order(customer_id="C2", total=50.0)
        order.cancel()
        outbox_repo = test_domain._get_outbox_repo("default")

        with UnitOfWork():
            test_domain.repository_for(Order).add(order)

        cancelled = [
            r
            for r in outbox_repo.find_unprocessed()
            if r.type == OrderCancelled.__type__
        ]
        assert len(cancelled) == 1
        assert cancelled[0].target_broker == "default"

    def test_mixed_published_and_internal_events_in_one_uow(self, test_domain):
        """An aggregate raising both published and internal events creates
        the right number of rows for each."""
        order = Order.place(customer_id="C3", total=75.0)
        order.cancel()
        outbox_repo = test_domain._get_outbox_repo("default")

        with UnitOfWork():
            test_domain.repository_for(Order).add(order)

        all_rows = outbox_repo.find_unprocessed()
        placed = [r for r in all_rows if r.type == OrderPlaced.__type__]
        cancelled = [r for r in all_rows if r.type == OrderCancelled.__type__]

        assert len(placed) == 2  # internal + external
        assert len(cancelled) == 1  # internal only

    def test_non_published_aggregate_no_external_rows(self, test_domain):
        inv = Inventory(sku="WIDGET", qty=10)
        inv.adjust(5)
        outbox_repo = test_domain._get_outbox_repo("default")

        with UnitOfWork():
            test_domain.repository_for(Inventory).add(inv)

        stock = [
            r
            for r in outbox_repo.find_unprocessed()
            if r.type == StockAdjusted.__type__
        ]
        assert len(stock) == 1
        assert stock[0].target_broker == "default"

    def test_external_row_metadata_matches_internal(self, test_domain):
        """External outbox row carries the same metadata as the internal row."""
        order = Order.place(customer_id="C4", total=120.0)
        outbox_repo = test_domain._get_outbox_repo("default")

        with UnitOfWork():
            test_domain.repository_for(Order).add(order)

        placed = [
            r for r in outbox_repo.find_unprocessed() if r.type == OrderPlaced.__type__
        ]
        internal = next(r for r in placed if r.target_broker == "default")
        external = next(r for r in placed if r.target_broker == "external")

        # Same correlation chain
        assert internal.correlation_id == external.correlation_id
        assert internal.causation_id == external.causation_id
        # Same priority
        assert internal.priority == external.priority


# ===================================================================
# target_broker filtering
# ===================================================================


@pytest.mark.database
class TestTargetBrokerFilter:
    def test_filter_returns_only_matching_broker(self, test_domain):
        order = Order.place(customer_id="CF1", total=42.0)
        outbox_repo = test_domain._get_outbox_repo("default")

        with UnitOfWork():
            test_domain.repository_for(Order).add(order)

        internal = outbox_repo.find_unprocessed(target_broker="default")
        external = outbox_repo.find_unprocessed(target_broker="external")

        assert all(r.target_broker == "default" for r in internal)
        assert all(r.target_broker == "external" for r in external)

    def test_filter_with_nonexistent_broker_returns_empty(self, test_domain):
        order = Order.place(customer_id="CF2", total=10.0)
        outbox_repo = test_domain._get_outbox_repo("default")

        with UnitOfWork():
            test_domain.repository_for(Order).add(order)

        assert outbox_repo.find_unprocessed(target_broker="nonexistent") == []


# ===================================================================
# Backward compatibility (no external brokers)
# ===================================================================


@pytest.mark.database
class TestBackwardCompatibility:
    @pytest.fixture(autouse=True)
    def no_external_brokers(self, test_domain):
        test_domain.config["outbox"]["external_brokers"] = []

    def test_single_row_with_null_target_broker(self, test_domain):
        order = Order.place(customer_id="BC1", total=100.0)
        outbox_repo = test_domain._get_outbox_repo("default")

        with UnitOfWork():
            test_domain.repository_for(Order).add(order)

        placed = [
            r for r in outbox_repo.find_unprocessed() if r.type == OrderPlaced.__type__
        ]
        assert len(placed) == 1
        assert placed[0].target_broker is None  # Legacy behavior

    def test_find_unprocessed_no_filter_returns_all(self, test_domain):
        order = Order.place(customer_id="BC2", total=60.0)
        outbox_repo = test_domain._get_outbox_repo("default")

        with UnitOfWork():
            test_domain.repository_for(Order).add(order)

        assert len(outbox_repo.find_unprocessed()) >= 1


# ===================================================================
# Multiple external brokers
# ===================================================================


@pytest.mark.database
class TestMultipleExternalBrokers:
    @pytest.fixture(autouse=True)
    def two_external_brokers(self, test_domain):
        test_domain.config["outbox"]["external_brokers"] = ["ext1", "ext2"]
        test_domain.config["brokers"]["ext1"] = {"provider": "inline"}
        test_domain.config["brokers"]["ext2"] = {"provider": "inline"}

    def test_one_row_per_external_broker(self, test_domain):
        order = Order.place(customer_id="MB1", total=200.0)
        outbox_repo = test_domain._get_outbox_repo("default")

        with UnitOfWork():
            test_domain.repository_for(Order).add(order)

        placed = [
            r for r in outbox_repo.find_unprocessed() if r.type == OrderPlaced.__type__
        ]
        assert len(placed) == 3  # internal + ext1 + ext2
        assert sorted(r.target_broker for r in placed) == [
            "default",
            "ext1",
            "ext2",
        ]


# ===================================================================
# Message.to_external_dict()
# ===================================================================


class TestMessageExternalDict:
    """Verify envelope stripping for external dispatch."""

    def _make_message(self) -> Message:
        return Message(
            data={"order_id": "123", "total": 99.0},
            metadata=Metadata(
                headers=MessageHeaders(
                    id="msg-001",
                    type="Test.OrderPlaced.v1",
                    time=None,
                    stream="test::order-abc",
                ),
                domain=DomainMeta(
                    fqn="tests.OrderPlaced",
                    kind="EVENT",
                    version=1,
                    correlation_id="corr-1",
                    causation_id="cause-1",
                    stream_category="test::order",
                    origin_stream="test::order-abc",
                    sequence_id="1",
                    expected_version=5,
                    asynchronous=True,
                    priority=3,
                ),
                extensions={"tenant_id": "acme"},
            ),
        )

    def test_strips_internal_domain_fields(self):
        ext = self._make_message().to_external_dict()
        domain = ext["metadata"]["domain"]
        assert "expected_version" not in domain
        assert "asynchronous" not in domain
        assert "priority" not in domain

    def test_keeps_public_header_fields(self):
        ext = self._make_message().to_external_dict()
        headers = ext["metadata"]["headers"]
        assert headers["id"] == "msg-001"
        assert headers["type"] == "Test.OrderPlaced.v1"

    def test_keeps_public_domain_fields(self):
        ext = self._make_message().to_external_dict()
        domain = ext["metadata"]["domain"]
        assert domain["fqn"] == "tests.OrderPlaced"
        assert domain["kind"] == "EVENT"
        assert domain["version"] == 1
        assert domain["correlation_id"] == "corr-1"
        assert domain["causation_id"] == "cause-1"
        assert domain["stream_category"] == "test::order"

    def test_keeps_extensions(self):
        ext = self._make_message().to_external_dict()
        assert ext["metadata"]["extensions"] == {"tenant_id": "acme"}

    def test_strips_event_store(self):
        ext = self._make_message().to_external_dict()
        assert "event_store" not in ext["metadata"]

    def test_envelope_specversion_only(self):
        ext = self._make_message().to_external_dict()
        assert ext["metadata"]["envelope"] == {"specversion": "1.0"}

    def test_data_unchanged(self):
        ext = self._make_message().to_external_dict()
        assert ext["data"] == {"order_id": "123", "total": 99.0}

    def test_no_metadata(self):
        ext = Message(data={"x": 1}).to_external_dict()
        assert ext["data"] == {"x": 1}
        assert ext["metadata"] is None

    def test_metadata_without_headers(self):
        """When headers is falsy (empty MessageHeaders), it should be omitted."""
        msg = Message(
            data={"x": 1},
            metadata=Metadata(
                headers=MessageHeaders(),
                domain=DomainMeta(fqn="t.E", kind="EVENT"),
            ),
        )
        ext = msg.to_external_dict()
        assert "headers" not in ext["metadata"]
        assert ext["metadata"]["domain"]["fqn"] == "t.E"

    def test_metadata_without_domain(self):
        msg = Message(
            data={"x": 1},
            metadata=Metadata(headers=MessageHeaders(id="msg-x")),
        )
        ext = msg.to_external_dict()
        assert ext["metadata"]["headers"]["id"] == "msg-x"
        assert "domain" not in ext["metadata"]

    def test_metadata_without_extensions(self):
        msg = Message(
            data={"x": 1},
            metadata=Metadata(
                headers=MessageHeaders(id="msg-y"),
                domain=DomainMeta(fqn="t.E", kind="EVENT"),
            ),
        )
        ext = msg.to_external_dict()
        assert "extensions" not in ext["metadata"]


# ===================================================================
# OutboxProcessor external mode
# ===================================================================


@pytest.mark.database
class TestOutboxProcessorExternalMode:
    """Test the OutboxProcessor ``is_external`` flag controls envelope,
    trace events, and target-broker filtering."""

    def test_external_processor_publishes_to_external_broker(self, test_domain):
        """End-to-end: an external OutboxProcessor picks up external rows
        and publishes to the external broker."""
        order = Order.place(customer_id="EP1", total=55.0)

        with UnitOfWork():
            test_domain.repository_for(Order).add(order)

        outbox_repo = test_domain._get_outbox_repo("default")
        external_rows = outbox_repo.find_unprocessed(target_broker="external")
        assert len(external_rows) >= 1

        # Build the engine and run the external processor
        engine = Engine(test_domain)
        loop = asyncio.new_event_loop()
        try:
            for proc in engine._outbox_processors.values():
                loop.run_until_complete(proc.initialize())

            ext_procs = {
                name: proc
                for name, proc in engine._outbox_processors.items()
                if proc.is_external
            }
            assert len(ext_procs) >= 1

            ext_proc = next(iter(ext_procs.values()))
            assert ext_proc.is_external is True

            # Process the batch
            loop.run_until_complete(ext_proc.tick())

            # External row should now be PUBLISHED
            all_rows = outbox_repo._dao.query.all().items
            external_placed = [
                r
                for r in all_rows
                if r.type == OrderPlaced.__type__ and r.target_broker == "external"
            ]
            assert len(external_placed) == 1
            assert external_placed[0].status == OutboxStatus.PUBLISHED.value
        finally:
            loop.close()

    def test_internal_processor_ignores_external_rows(self, test_domain):
        """Internal OutboxProcessor should not pick up external-targeted rows."""
        order = Order.place(customer_id="IP1", total=30.0)

        with UnitOfWork():
            test_domain.repository_for(Order).add(order)

        engine = Engine(test_domain)
        loop = asyncio.new_event_loop()
        try:
            for proc in engine._outbox_processors.values():
                loop.run_until_complete(proc.initialize())

            # Find internal processor
            int_procs = {
                name: proc
                for name, proc in engine._outbox_processors.items()
                if not proc.is_external
            }
            int_proc = next(iter(int_procs.values()))
            assert int_proc.is_external is False

            # Process
            loop.run_until_complete(int_proc.tick())

            # Internal row should be PUBLISHED, external row still PENDING
            outbox_repo = test_domain._get_outbox_repo("default")
            all_rows = outbox_repo._dao.query.all().items
            placed = [r for r in all_rows if r.type == OrderPlaced.__type__]

            internal_row = next(r for r in placed if r.target_broker == "default")
            external_row = next(r for r in placed if r.target_broker == "external")

            assert internal_row.status == OutboxStatus.PUBLISHED.value
            assert external_row.status == OutboxStatus.PENDING.value
        finally:
            loop.close()

    def test_external_processor_skips_priority_lanes(self, test_domain):
        """External processors should not apply backfill lane suffixes."""
        # Enable priority lanes
        test_domain.config["server"]["priority_lanes"] = {
            "enabled": True,
            "threshold": 5,
            "backfill_suffix": "backfill",
        }

        engine = Engine(test_domain)

        ext_procs = [
            proc for proc in engine._outbox_processors.values() if proc.is_external
        ]
        assert len(ext_procs) >= 1
        # External processors should not use lanes
        for proc in ext_procs:
            assert proc.is_external is True


# ===================================================================
# Engine creates external processors
# ===================================================================


@pytest.mark.database
class TestEngineExternalProcessors:
    def test_engine_creates_internal_and_external_processors(self, test_domain):
        engine = Engine(test_domain)

        internal = {
            n: p for n, p in engine._outbox_processors.items() if not p.is_external
        }
        external = {n: p for n, p in engine._outbox_processors.items() if p.is_external}

        assert len(internal) >= 1
        assert len(external) >= 1

        # External processor names end with "-external"
        for name in external:
            assert name.endswith("-external")

    def test_engine_raises_on_missing_external_broker(self, test_domain):
        test_domain.config["outbox"]["external_brokers"] = ["nonexistent"]
        with pytest.raises(ValueError, match="nonexistent"):
            Engine(test_domain)

    def test_engine_no_external_processors_when_empty_config(self, test_domain):
        test_domain.config["outbox"]["external_brokers"] = []
        engine = Engine(test_domain)

        external = [p for p in engine._outbox_processors.values() if p.is_external]
        assert len(external) == 0


# ===================================================================
# Validation warning
# ===================================================================


@pytest.mark.no_test_domain
class TestValidationWarning:
    def _make_domain(self, *, external_brokers: list[str] | None = None):
        domain = Domain(name="WarnTest")
        domain.config["enable_outbox"] = True
        domain.config["server"]["default_subscription_type"] = "stream"
        if external_brokers is not None:
            domain.config["outbox"]["external_brokers"] = external_brokers
        else:
            domain.config["outbox"]["external_brokers"] = []
        return domain

    def test_warns_when_published_events_without_external_brokers(self, caplog):
        domain = self._make_domain(external_brokers=[])
        with domain.domain_context():
            domain.register(Order)
            domain.register(OrderPlaced, part_of=Order, published=True)
            with caplog.at_level(logging.WARNING):
                domain.init(traverse=False)

        assert any(
            "published events" in r.message.lower() and "external_brokers" in r.message
            for r in caplog.records
        )

    def test_no_warning_when_external_brokers_configured(self, caplog):
        domain = self._make_domain(external_brokers=["ext"])
        domain.config["brokers"]["ext"] = {"provider": "inline"}
        with domain.domain_context():
            domain.register(Order)
            domain.register(OrderPlaced, part_of=Order, published=True)
            with caplog.at_level(logging.WARNING):
                domain.init(traverse=False)

        assert not any(
            "published events" in r.message.lower() and "external_brokers" in r.message
            for r in caplog.records
        )

    def test_no_warning_when_no_published_events(self, caplog):
        domain = self._make_domain(external_brokers=[])
        with domain.domain_context():
            domain.register(Inventory)
            domain.register(StockAdjusted, part_of=Inventory)
            with caplog.at_level(logging.WARNING):
                domain.init(traverse=False)

        assert not any(
            "published events" in r.message.lower() and "external_brokers" in r.message
            for r in caplog.records
        )


# ===================================================================
# Outbox model — target_broker field
# ===================================================================


class TestOutboxTargetBrokerField:
    def test_create_message_with_target_broker(self):
        msg = Outbox.create_message(
            message_id="test-id",
            stream_name="test::order-1",
            message_type="Test.OrderPlaced.v1",
            data={"x": 1},
            metadata=Metadata(headers=MessageHeaders(id="test-id")),
            target_broker="kafka",
        )
        assert msg.target_broker == "kafka"

    def test_create_message_default_target_broker_is_none(self):
        msg = Outbox.create_message(
            message_id="test-id",
            stream_name="test::order-1",
            message_type="Test.OrderPlaced.v1",
            data={"x": 1},
            metadata=Metadata(headers=MessageHeaders(id="test-id")),
        )
        assert msg.target_broker is None
