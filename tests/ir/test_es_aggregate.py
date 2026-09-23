"""Tests for IRBuilder event-sourced aggregate extraction."""

import pytest

from protean.domain import Domain
from protean.fields import Float, Identifier, String
from protean.ir.builder import IRBuilder

from .elements import build_es_aggregate_domain


def _order_cluster(reserved=None):
    """Build a single-aggregate domain and return the Order cluster's IR."""
    domain = Domain(name="Shop", root_path=".")

    options = {"event_sourced": True}
    if reserved is not None:
        options["reserved"] = reserved

    @domain.aggregate(**options)
    class Order:
        order_id = Identifier(identifier=True)
        amount = Float()
        label = String()

    domain.init(traverse=False)
    ir = IRBuilder(domain).build()
    for cluster in ir["clusters"].values():
        if cluster["aggregate"]["name"] == "Order":
            return cluster
    pytest.fail("Order cluster not found")


@pytest.fixture
def bank_cluster():
    """Return the BankAccount aggregate's cluster."""
    domain = build_es_aggregate_domain()
    ir = IRBuilder(domain).build()
    for cluster in ir["clusters"].values():
        if cluster["aggregate"]["name"] == "BankAccount":
            return cluster
    pytest.fail("BankAccount cluster not found")


@pytest.mark.no_test_domain
class TestESAggregateExtraction:
    """Verify event-sourced aggregate IR structure."""

    def test_is_event_sourced(self, bank_cluster):
        assert bank_cluster["aggregate"]["options"]["is_event_sourced"] is True

    def test_apply_handlers_present(self, bank_cluster):
        assert "apply_handlers" in bank_cluster["aggregate"]

    def test_apply_handlers_map_events(self, bank_cluster):
        handlers = bank_cluster["aggregate"]["apply_handlers"]
        assert len(handlers) == 2

    def test_apply_handlers_values_are_method_names(self, bank_cluster):
        handlers = bank_cluster["aggregate"]["apply_handlers"]
        method_names = list(handlers.values())
        assert "opened" in method_names
        assert "deposited" in method_names

    def test_apply_handlers_keys_are_event_fqns(self, bank_cluster):
        handlers = bank_cluster["aggregate"]["apply_handlers"]
        for key in handlers:
            assert "AccountOpened" in key or "DepositMade" in key

    def test_apply_handlers_keys_sorted(self, bank_cluster):
        handlers = bank_cluster["aggregate"]["apply_handlers"]
        keys = list(handlers.keys())
        assert keys == sorted(keys)

    def test_events_in_cluster(self, bank_cluster):
        assert len(bank_cluster["events"]) >= 2


@pytest.mark.no_test_domain
class TestReservedOptionExtraction:
    """`reserved` is recorded in the aggregate's IR options, sparsely."""

    def test_reserved_recorded_sorted(self):
        cluster = _order_cluster(reserved=["note", "archived"])
        assert cluster["aggregate"]["options"]["reserved"] == ["archived", "note"]

    def test_reserved_absent_when_not_declared(self):
        cluster = _order_cluster()
        assert "reserved" not in cluster["aggregate"]["options"]

    def test_reserved_absent_when_empty(self):
        cluster = _order_cluster(reserved=[])
        assert "reserved" not in cluster["aggregate"]["options"]
