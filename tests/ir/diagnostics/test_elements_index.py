"""Diagnostics: TestElementsIndex."""

import pytest

from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    build_diagnostics_test_domain,
)


class TestElementsIndex:
    """Verify elements index structure."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.domain = build_diagnostics_test_domain()
        self.ir = IRBuilder(self.domain).build()

    def test_elements_has_all_types(self):
        expected_types = [
            "AGGREGATE",
            "APPLICATION_SERVICE",
            "COMMAND",
            "COMMAND_HANDLER",
            "DATABASE_MODEL",
            "DOMAIN_SERVICE",
            "ENTITY",
            "EVENT",
            "EVENT_HANDLER",
            "PROCESS_MANAGER",
            "PROJECTION",
            "PROJECTOR",
            "QUERY",
            "QUERY_HANDLER",
            "REPOSITORY",
            "SUBSCRIBER",
            "VALUE_OBJECT",
        ]
        for etype in expected_types:
            assert etype in self.ir["elements"], f"Missing element type: {etype}"

    def test_aggregate_in_index(self):
        agg_list = self.ir["elements"]["AGGREGATE"]
        assert any("Order" in fqn for fqn in agg_list)

    def test_command_in_index(self):
        cmd_list = self.ir["elements"]["COMMAND"]
        assert any("PlaceOrder" in fqn for fqn in cmd_list)

    def test_event_in_index(self):
        evt_list = self.ir["elements"]["EVENT"]
        assert any("OrderPlaced" in fqn for fqn in evt_list)

    def test_elements_lists_sorted(self):
        for etype, fqn_list in self.ir["elements"].items():
            assert fqn_list == sorted(fqn_list), f"{etype} list not sorted"

    def test_empty_types_are_empty_lists(self):
        assert self.ir["elements"]["DOMAIN_SERVICE"] == []
        assert self.ir["elements"]["SUBSCRIBER"] == []
