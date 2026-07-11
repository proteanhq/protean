"""Diagnostics: TestUnusedCommand."""

from protean import Domain, handle
from protean.fields.simple import String
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

    def test_unused_command_format(self):
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        unused = [d for d in ir["diagnostics"] if d["code"] == "UNUSED_COMMAND"]
        for diag in unused:
            assert diag["level"] == "warning"
            assert "no registered handler" in diag["message"]

    def test_no_unused_when_handler_exists(self):
        domain = Domain(name="HandledCmd", root_path=".")

        @domain.command(part_of="Task")
        class CreateTask:
            title = String(required=True)

        @domain.aggregate
        class Task:
            title = String(max_length=100)

        @domain.command_handler(part_of=Task)
        class TaskCommandHandler:
            @handle(CreateTask)
            def handle_create(self, command):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        unused = [d for d in ir["diagnostics"] if d["code"] == "UNUSED_COMMAND"]
        assert len(unused) == 0
