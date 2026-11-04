"""Diagnostics: TestUnusedCommand."""

from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    build_diagnostics_test_domain,
)


class TestUnusedCommand:
    """Verify UNUSED_COMMAND diagnostics."""

    def test_unused_command_detected(self):
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        unused = [d for d in ir["diagnostics"] if d["code"] == "UNUSED_COMMAND"]
        assert len(unused) == 1
        assert "PlaceOrder" in unused[0]["element"]
        assert unused[0]["level"] == "warning"
        assert "no registered handler" in unused[0]["message"]
