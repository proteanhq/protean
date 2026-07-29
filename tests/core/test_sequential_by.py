"""Tests for the ``sequential_by`` partition-key publishing infrastructure (#830).

Covers the publishing-side plumbing ratified by ADR-0028: the ``sequential_by``
handler option, registration-time validation (field existence, one key per
category, broker capability gating), and the Unit of Work extracting and
validating the partition key onto each outbox row. The consumer side (ownership
lease, fencing, reclaim) is #831 and is deliberately out of scope here.
"""

from types import SimpleNamespace

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.core.unit_of_work import UnitOfWork
from protean.domain import Domain
from protean.domain.handler_setup import HandlerConfigurator
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import Identifier, Integer, String
from protean.port.broker import BrokerCapabilities
from protean.utils.mixins import handle

# --- Shared elements ---------------------------------------------------------


class Order(BaseAggregate):
    client_id: String(max_length=50)

    def place(self, client_id):
        self.client_id = client_id
        self.raise_(OrderPlaced(order_id=str(self.id), client_id=client_id))


class OrderPlaced(BaseEvent):
    order_id: Identifier()
    client_id: String(max_length=50)


class PlaceOrder(BaseCommand):
    order_id: Identifier()
    client_id: String(max_length=50)


class Widget(BaseAggregate):
    label: String(max_length=50)

    def create(self, label):
        self.label = label
        self.raise_(WidgetCreated(widget_id=str(self.id), label=label))


class WidgetCreated(BaseEvent):
    widget_id: Identifier()
    label: String(max_length=50)


class Account(BaseAggregate):
    tenant: Integer()

    def open(self, tenant):
        self.tenant = tenant
        self.raise_(AccountOpened(account_id=str(self.id), tenant=tenant))


class AccountOpened(BaseEvent):
    account_id: Identifier()
    tenant: Integer()


class _StubBroker:
    """A minimal fake broker for capability assertions (not a mock).

    Only the surface :meth:`validate_sequential_by_capabilities` touches is
    implemented: a name and a capability check.
    """

    def __init__(self, name: str, capabilities: BrokerCapabilities) -> None:
        self.name = name
        self._capabilities = capabilities

    def has_capability(self, capability: BrokerCapabilities) -> bool:
        return capability in self._capabilities


# --- Option storage ----------------------------------------------------------


class TestOptionStorage:
    def test_event_handler_stores_sequential_by(self, test_domain):
        class OrderEventHandler(BaseEventHandler):
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(
            OrderEventHandler, part_of=Order, sequential_by="client_id"
        )
        test_domain.init(traverse=False)

        assert OrderEventHandler.meta_.sequential_by == "client_id"

    def test_event_handler_defaults_to_none(self, test_domain):
        class PlainOrderHandler(BaseEventHandler):
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(PlainOrderHandler, part_of=Order)
        test_domain.init(traverse=False)

        assert PlainOrderHandler.meta_.sequential_by is None

    def test_command_handler_stores_sequential_by(self, test_domain):
        class OrderCommandHandler(BaseCommandHandler):
            @handle(PlaceOrder)
            def on_place(self, command):
                pass

        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(
            OrderCommandHandler, part_of=Order, sequential_by="client_id"
        )
        test_domain.init(traverse=False)

        assert OrderCommandHandler.meta_.sequential_by == "client_id"

    def test_process_manager_stores_sequential_by(self, test_domain):
        class OrderPM(BaseProcessManager):
            order_id = Identifier(identifier=True)

            @handle(OrderPlaced, start=True, correlate="order_id")
            def on_placed(self, event):
                pass

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(OrderPM, sequential_by=True)
        test_domain.init(traverse=False)

        assert OrderPM.meta_.sequential_by is True


# --- Field-existence validation ---------------------------------------------


class TestFieldExistenceValidation:
    def test_missing_field_on_event_handler_raises(self, test_domain):
        class BadHandler(BaseEventHandler):
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(BadHandler, part_of=Order, sequential_by="nonexistent")

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)
        assert "nonexistent" in str(exc.value)

    def test_present_field_on_event_handler_passes(self, test_domain):
        class GoodHandler(BaseEventHandler):
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(GoodHandler, part_of=Order, sequential_by="client_id")
        test_domain.init(traverse=False)

        assert test_domain._partition_keys["test::order"] == "client_id"

    def test_missing_field_on_command_handler_raises(self, test_domain):
        class BadCommandHandler(BaseCommandHandler):
            @handle(PlaceOrder)
            def on_place(self, command):
                pass

        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(
            BadCommandHandler, part_of=Order, sequential_by="nonexistent"
        )

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)
        assert "nonexistent" in str(exc.value)

    def test_missing_correlate_field_on_pm_raises(self, test_domain):
        # correlate maps to an event field that does not exist on the event.
        class BadPM(BaseProcessManager):
            order_id = Identifier(identifier=True)

            @handle(OrderPlaced, start=True, correlate={"order_id": "missing_field"})
            def on_placed(self, event):
                pass

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(BadPM, sequential_by=True)

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)
        assert "missing_field" in str(exc.value)

    def test_pm_partitions_by_correlate_field(self, test_domain):
        class OrderPM(BaseProcessManager):
            order_id = Identifier(identifier=True)

            @handle(OrderPlaced, start=True, correlate="order_id")
            def on_placed(self, event):
                pass

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(OrderPM, sequential_by=True)
        test_domain.init(traverse=False)

        assert test_domain._partition_keys["test::order"] == "order_id"


# --- One-key-per-category validation ----------------------------------------


class TestOneKeyPerCategory:
    def test_conflicting_keys_on_same_category_raise(self, test_domain):
        class HandlerA(BaseEventHandler):
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        class HandlerB(BaseEventHandler):
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(HandlerA, part_of=Order, sequential_by="client_id")
        test_domain.register(HandlerB, part_of=Order, sequential_by="order_id")

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)
        assert "conflicting" in str(exc.value).lower()

    def test_same_key_on_same_category_passes(self, test_domain):
        class HandlerA(BaseEventHandler):
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        class HandlerB(BaseEventHandler):
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(HandlerA, part_of=Order, sequential_by="client_id")
        test_domain.register(HandlerB, part_of=Order, sequential_by="client_id")
        test_domain.init(traverse=False)

        assert test_domain._partition_keys["test::order"] == "client_id"


# --- Capability gating -------------------------------------------------------


def _init_domain_with_partitioned_handler(name):
    domain = Domain(name=name)

    class OrderEventHandler(BaseEventHandler):
        @handle(OrderPlaced)
        def on_placed(self, event):
            pass

    domain.register(Order)
    domain.register(OrderPlaced, part_of=Order)
    domain.register(OrderEventHandler, part_of=Order, sequential_by="client_id")
    with domain.domain_context():
        domain.init(traverse=False)
    return domain


class TestCapabilityGating:
    def test_inline_broker_is_accepted_as_noop(self):
        # The default broker is the single-threaded inline broker, which lacks
        # STREAM_PARTITIONING but is the no-op exception, so init() must pass.
        domain = _init_domain_with_partitioned_handler("CapInline")
        assert domain._partition_keys == {"capinline::order": "client_id"}

    def test_non_partitioning_broker_raises(self):
        domain = _init_domain_with_partitioned_handler("CapNoPart")
        domain.brokers._brokers["default"] = _StubBroker(
            "default", BrokerCapabilities.RELIABLE_MESSAGING
        )
        with pytest.raises(IncorrectUsageError) as exc:
            domain._handler_configurator.validate_sequential_by_capabilities()
        assert "STREAM_PARTITIONING" in str(exc.value)

    def test_partitioning_broker_passes(self):
        domain = _init_domain_with_partitioned_handler("CapPart")
        domain.brokers._brokers["default"] = _StubBroker(
            "default", BrokerCapabilities.STREAM_PARTITIONING
        )
        # Must not raise, and the partition map must survive the gate unchanged.
        domain._handler_configurator.validate_sequential_by_capabilities()
        assert domain._partition_keys == {"cappart::order": "client_id"}


# --- Unit of Work extraction + validation -----------------------------------


def _make_outbox_domain(name, backfill_suffix="backfill"):
    config = {
        "enable_outbox": True,
        "server": {
            "default_subscription_type": "stream",
            "priority_lanes": {"backfill_suffix": backfill_suffix},
        },
    }
    domain = Domain(name=name, config=config)

    class OrderEventHandler(BaseEventHandler):
        @handle(OrderPlaced)
        def on_placed(self, event):
            pass

    domain.register(Order)
    domain.register(OrderPlaced, part_of=Order)
    domain.register(OrderEventHandler, part_of=Order, sequential_by="client_id")
    domain.register(Widget)
    domain.register(WidgetCreated, part_of=Widget)
    domain.init(traverse=False)
    return domain


@pytest.mark.database
class TestUnitOfWorkExtraction:
    def test_partitioned_event_stores_key(self):
        domain = _make_outbox_domain("UoWStore")
        with domain.domain_context():
            order = Order(client_id="placeholder")
            order.place("client-1")
            with UnitOfWork():
                domain.repository_for(Order).add(order)

            outbox_repo = domain._get_outbox_repo("default")
            rows = [
                r
                for r in outbox_repo.find_unprocessed()
                if r.type == OrderPlaced.__type__
            ]
            assert len(rows) == 1, "Expected exactly one OrderPlaced outbox row"
            assert rows[0].partition_key == "client-1"

    def test_non_string_key_is_coerced_to_its_string_form(self):
        # A non-string key field (here an Integer) is coerced to its string form
        # before it becomes the ``{category}:{key}`` stream segment. Locking this
        # keeps the coercion honest: int ``7`` must land as ``"7"`` on the row,
        # not as an int or a repr, so routing stays a stable string.
        config = {
            "enable_outbox": True,
            "server": {
                "default_subscription_type": "stream",
                "priority_lanes": {"backfill_suffix": "backfill"},
            },
        }
        domain = Domain(name="UoWIntKey", config=config)

        class AccountEventHandler(BaseEventHandler):
            @handle(AccountOpened)
            def on_opened(self, event):
                pass

        domain.register(Account)
        domain.register(AccountOpened, part_of=Account)
        domain.register(AccountEventHandler, part_of=Account, sequential_by="tenant")
        domain.init(traverse=False)

        with domain.domain_context():
            account = Account(tenant=0)
            account.open(7)
            with UnitOfWork():
                domain.repository_for(Account).add(account)

            outbox_repo = domain._get_outbox_repo("default")
            rows = [
                r
                for r in outbox_repo.find_unprocessed()
                if r.type == AccountOpened.__type__
            ]
            assert len(rows) == 1, "Expected exactly one AccountOpened outbox row"
            assert rows[0].partition_key == "7"

    def test_non_partitioned_event_leaves_key_none(self):
        domain = _make_outbox_domain("UoWNone")
        with domain.domain_context():
            widget = Widget(label="placeholder")
            widget.create("blue")
            with UnitOfWork():
                domain.repository_for(Widget).add(widget)

            outbox_repo = domain._get_outbox_repo("default")
            rows = [
                r
                for r in outbox_repo.find_unprocessed()
                if r.type == WidgetCreated.__type__
            ]
            assert len(rows) == 1, "Expected exactly one WidgetCreated outbox row"
            assert rows[0].partition_key is None


@pytest.mark.database
class TestUnitOfWorkKeyRejection:
    @pytest.mark.parametrize(
        ("bad_value", "backfill_suffix"),
        [
            (None, "backfill"),
            ("", "backfill"),
            ("has:colon", "backfill"),
            ("dlq", "backfill"),
            ("mybackfill", "mybackfill"),
            ("__partitions__", "backfill"),
            ("__whatever__", "backfill"),
        ],
    )
    def test_invalid_key_fails_and_creates_no_row(self, bad_value, backfill_suffix):
        domain = _make_outbox_domain(
            f"UoWReject{abs(hash((bad_value, backfill_suffix)))}",
            backfill_suffix=backfill_suffix,
        )
        with domain.domain_context():
            outbox_repo = domain._get_outbox_repo("default")
            before = len(outbox_repo.find_unprocessed())

            order = Order(client_id="placeholder")
            order.place(bad_value)

            with pytest.raises(ValidationError):
                with UnitOfWork():
                    domain.repository_for(Order).add(order)

            after = len(outbox_repo.find_unprocessed())
            assert after == before, "A rejected key must create no outbox row"


# --- Non-partitioned handlers are skipped ------------------------------------


class TestNonPartitionedHandlersSkipped:
    """Handlers that do not opt into ``sequential_by`` leave the map untouched."""

    def test_plain_command_handler_is_skipped(self, test_domain):
        # A command handler with no `sequential_by` must be skipped by the
        # partition-map build, not partition its category.
        class PlainCommandHandler(BaseCommandHandler):
            @handle(PlaceOrder)
            def on_place(self, command):
                pass

        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(PlainCommandHandler, part_of=Order)
        test_domain.init(traverse=False)

        assert test_domain._partition_keys == {}

    def test_plain_process_manager_is_skipped(self, test_domain):
        # A process manager without `sequential_by=True` must be skipped.
        class PlainPM(BaseProcessManager):
            order_id = Identifier(identifier=True)

            @handle(OrderPlaced, start=True, correlate="order_id")
            def on_placed(self, event):
                pass

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(PlainPM)
        test_domain.init(traverse=False)

        assert test_domain._partition_keys == {}


# --- Capability gate: no broker resolves -------------------------------------


class TestCapabilityGateNoBroker:
    def test_gate_returns_when_no_broker_resolves(self):
        # With partition keys declared but neither the named nor the default
        # broker present, the gate returns quietly instead of raising.
        domain = _init_domain_with_partitioned_handler("CapNoBroker")
        assert domain._partition_keys  # precondition: past the empty-map guard
        domain.brokers._brokers.clear()

        # Must not raise.
        domain._handler_configurator.validate_sequential_by_capabilities()


# --- Static helper edge cases ------------------------------------------------


class TestStaticHelperEdges:
    def test_event_published_category_none_when_part_of_unset(self):
        # part_of is None: no aggregate, so no category can be derived.
        ev = SimpleNamespace(meta_=SimpleNamespace(part_of=None))
        assert HandlerConfigurator._event_published_category(ev) is None

    def test_event_published_category_none_when_part_of_is_string(self):
        # An unresolved string reference carries no meta_ to read a category off.
        ev = SimpleNamespace(meta_=SimpleNamespace(part_of="Order"))
        assert HandlerConfigurator._event_published_category(ev) is None

    def test_correlate_field_resolves_string_and_dict(self):
        assert HandlerConfigurator._correlate_field("order_id") == "order_id"
        assert HandlerConfigurator._correlate_field({"pm_id": "order_id"}) == "order_id"

    def test_correlate_field_none_for_none_spec(self):
        assert HandlerConfigurator._correlate_field(None) is None

    def test_correlate_field_none_for_empty_dict(self):
        assert HandlerConfigurator._correlate_field({}) is None
