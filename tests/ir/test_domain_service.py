"""Tests for IRBuilder domain service extraction."""

import pytest

from protean.ir.builder import IRBuilder

from .elements import build_domain_service_domain


@pytest.fixture
def flows():
    """Return the flows section from the domain service test domain."""
    domain = build_domain_service_domain()
    ir = IRBuilder(domain).build()
    return ir["flows"]


@pytest.mark.no_test_domain
class TestDomainServiceExtraction:
    """Verify domain service IR structure."""

    def test_domain_service_present(self, flows):
        assert len(flows["domain_services"]) == 1

    def test_element_type(self, flows):
        svc = next(iter(flows["domain_services"].values()))
        assert svc["element_type"] == "DOMAIN_SERVICE"

    def test_name(self, flows):
        svc = next(iter(flows["domain_services"].values()))
        assert svc["name"] == "PlaceOrderService"

    def test_part_of_is_sorted_list(self, flows):
        svc = next(iter(flows["domain_services"].values()))
        assert isinstance(svc["part_of"], list)
        assert len(svc["part_of"]) == 2
        assert svc["part_of"] == sorted(svc["part_of"])

    def test_invariants(self, flows):
        svc = next(iter(flows["domain_services"].values()))
        assert "invariants" in svc
        assert "inventory_must_have_stock" in svc["invariants"]["pre"]

    def test_keys_sorted(self, flows):
        svc = next(iter(flows["domain_services"].values()))
        keys = list(svc.keys())
        assert keys == sorted(keys)
