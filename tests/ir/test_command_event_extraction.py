"""Tests for IRBuilder command and event extraction."""

import pytest

from protean.ir.builder import IRBuilder

from .elements import build_command_event_test_domain


@pytest.fixture
def order_cluster():
    """Return the Order aggregate's cluster from the command/event test domain."""
    domain = build_command_event_test_domain()
    ir = IRBuilder(domain).build()
    for _key, cluster in ir["clusters"].items():
        if cluster["aggregate"]["name"] == "Order":
            return cluster
    pytest.fail("Order cluster not found")


@pytest.mark.no_test_domain
class TestCommandExtraction:
    """Verify command IR dict structure."""

    def test_commands_present(self, order_cluster):
        assert len(order_cluster["commands"]) == 2

    def test_command_element_type(self, order_cluster):
        for cmd in order_cluster["commands"].values():
            assert cmd["element_type"] == "COMMAND"

    def test_command_type_format(self, order_cluster):
        for cmd in order_cluster["commands"].values():
            # Type format: DomainName.ClassName.vN
            assert cmd["__type__"].startswith("Ordering.")
            assert cmd["__type__"].endswith(".v1")

    def test_command_version(self, order_cluster):
        for cmd in order_cluster["commands"].values():
            assert cmd["__version__"] == "v1"

    def test_command_part_of(self, order_cluster):
        agg_fqn = order_cluster["aggregate"]["fqn"]
        for cmd in order_cluster["commands"].values():
            assert cmd["part_of"] == agg_fqn

    def test_command_fields(self, order_cluster):
        place_order = None
        for cmd in order_cluster["commands"].values():
            if cmd["name"] == "PlaceOrder":
                place_order = cmd
                break
        assert place_order is not None
        assert "customer_name" in place_order["fields"]

    def test_command_keys_sorted(self, order_cluster):
        for cmd in order_cluster["commands"].values():
            keys = list(cmd.keys())
            assert keys == sorted(keys)

    def test_commands_sorted_by_fqn(self, order_cluster):
        keys = list(order_cluster["commands"].keys())
        assert keys == sorted(keys)


@pytest.mark.no_test_domain
class TestEventExtraction:
    """Verify event IR dict structure."""

    def test_events_present(self, order_cluster):
        # 2 explicit events + 1 auto-generated fact event
        assert len(order_cluster["events"]) >= 2

    def test_event_element_type(self, order_cluster):
        for evt in order_cluster["events"].values():
            assert evt["element_type"] == "EVENT"

    def test_event_type_format(self, order_cluster):
        for evt in order_cluster["events"].values():
            assert evt["__type__"].startswith("Ordering.")

    def test_event_version(self, order_cluster):
        for evt in order_cluster["events"].values():
            assert evt["__version__"] == "v1"

    def test_event_part_of(self, order_cluster):
        agg_fqn = order_cluster["aggregate"]["fqn"]
        for evt in order_cluster["events"].values():
            assert evt["part_of"] == agg_fqn

    def test_event_is_fact_event_field(self, order_cluster):
        for evt in order_cluster["events"].values():
            assert "is_fact_event" in evt

    def test_explicit_event_not_fact_event(self, order_cluster):
        for evt in order_cluster["events"].values():
            if evt["name"] == "OrderPlaced":
                assert evt["is_fact_event"] is False
                return
        pytest.fail("OrderPlaced event not found")

    def test_event_fields(self, order_cluster):
        for evt in order_cluster["events"].values():
            if evt["name"] == "OrderPlaced":
                assert "order_id" in evt["fields"]
                assert "customer_name" in evt["fields"]
                return
        pytest.fail("OrderPlaced event not found")

    def test_event_keys_sorted(self, order_cluster):
        for evt in order_cluster["events"].values():
            keys = list(evt.keys())
            assert keys == sorted(keys)

    def test_events_sorted_by_fqn(self, order_cluster):
        keys = list(order_cluster["events"].keys())
        assert keys == sorted(keys)


@pytest.mark.no_test_domain
class TestFactEvent:
    """Verify auto-generated fact events are captured."""

    def test_fact_event_exists(self, order_cluster):
        fact_events = [
            e for e in order_cluster["events"].values() if e["is_fact_event"]
        ]
        assert len(fact_events) >= 1

    def test_fact_event_auto_generated(self, order_cluster):
        for evt in order_cluster["events"].values():
            if evt["is_fact_event"]:
                assert evt.get("auto_generated") is True
                return
        pytest.fail("No fact event found")
