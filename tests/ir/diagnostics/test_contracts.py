"""Diagnostics: TestContracts."""

from protean import Domain
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    build_diagnostics_test_domain,
)


class TestContracts:
    """Verify contracts section."""

    def test_contracts_events_empty_when_none_published(self):
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        # No events have published=True in this domain
        assert ir["contracts"]["events"] == []

    def test_contracts_structure(self):
        domain = Domain(name="Test", root_path=".")
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        assert "events" in ir["contracts"]
        assert isinstance(ir["contracts"]["events"], list)
