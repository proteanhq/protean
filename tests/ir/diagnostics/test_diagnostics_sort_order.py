"""Diagnostics: TestDiagnosticsSortOrder."""

from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    build_diagnostics_test_domain,
)


class TestDiagnosticsSortOrder:
    """Verify mixed diagnostics are sorted by code."""

    def test_mixed_diagnostics_sorted(self):
        """A domain with both UNHANDLED_EVENT and UNUSED_COMMAND should
        have diagnostics sorted alphabetically by code."""
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        codes = [d["code"] for d in ir["diagnostics"]]
        assert codes == sorted(codes)
        # Verify we have both types
        assert "UNHANDLED_EVENT" in codes
        assert "UNUSED_COMMAND" in codes
