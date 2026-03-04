"""Tests for IRBuilder process manager extraction."""

import pytest

from protean.ir.builder import IRBuilder

from .elements import build_process_manager_domain


@pytest.fixture
def pm_ir():
    """Return the full IR from the process manager test domain."""
    domain = build_process_manager_domain()
    return IRBuilder(domain).build()


@pytest.fixture
def pm(pm_ir):
    """Return the OrderFulfillment process manager dict."""
    pms = pm_ir["flows"]["process_managers"]
    for pm in pms.values():
        if pm["name"] == "OrderFulfillment":
            return pm
    pytest.fail("OrderFulfillment PM not found")


@pytest.mark.no_test_domain
class TestProcessManagerExtraction:
    """Verify process manager IR structure."""

    def test_pm_present(self, pm_ir):
        assert len(pm_ir["flows"]["process_managers"]) == 1

    def test_element_type(self, pm):
        assert pm["element_type"] == "PROCESS_MANAGER"

    def test_name(self, pm):
        assert pm["name"] == "OrderFulfillment"

    def test_fields_present(self, pm):
        assert "order_id" in pm["fields"]
        assert "status" in pm["fields"]

    def test_stream_categories(self, pm):
        # Stream categories are prefixed with domain normalized name
        cats = pm["stream_categories"]
        assert len(cats) == 2
        assert any("flow_order" in c for c in cats)
        assert any("flow_payment" in c for c in cats)

    def test_handlers_present(self, pm):
        assert len(pm["handlers"]) == 3

    def test_handler_has_start(self, pm):
        """The on_order_placed handler should have start=True."""
        found_start = False
        for handler in pm["handlers"].values():
            if handler.get("start"):
                found_start = True
                break
        assert found_start

    def test_handler_has_end(self, pm):
        """The on_payment_failed handler should have end=True."""
        found_end = False
        for handler in pm["handlers"].values():
            if handler.get("end"):
                found_end = True
                break
        assert found_end

    def test_handler_has_correlate(self, pm):
        """All handlers should have correlate="order_id"."""
        for handler in pm["handlers"].values():
            assert handler.get("correlate") == "order_id"

    def test_handler_has_methods(self, pm):
        """Each handler should have a methods list."""
        for handler in pm["handlers"].values():
            assert "methods" in handler
            assert isinstance(handler["methods"], list)
            assert len(handler["methods"]) >= 1

    def test_identity_field(self, pm):
        assert "identity_field" in pm

    def test_subscription_structure(self, pm):
        sub = pm["subscription"]
        assert "config" in sub
        assert "profile" in sub
        assert "type" in sub

    def test_keys_sorted(self, pm):
        keys = list(pm.keys())
        assert keys == sorted(keys)
