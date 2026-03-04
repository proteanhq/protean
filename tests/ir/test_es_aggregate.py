"""Tests for IRBuilder event-sourced aggregate extraction."""

import pytest

from protean.ir.builder import IRBuilder

from .elements import build_es_aggregate_domain


@pytest.fixture
def bank_cluster():
    """Return the BankAccount aggregate's cluster."""
    domain = build_es_aggregate_domain()
    ir = IRBuilder(domain).build()
    for _key, cluster in ir["clusters"].items():
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
