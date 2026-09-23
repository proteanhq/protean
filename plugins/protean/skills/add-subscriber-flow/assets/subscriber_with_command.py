"""
Subscriber flow with command dispatch (full anti-corruption layer).

This example demonstrates:
- Subscriber consuming external ERP messages from a broker stream
- Anti-corruption layer translating camelCase external format to domain commands
- Multiple external event types handled by different translation methods
- Command dispatched to handler which creates/updates aggregates
- Full flow: external message → subscriber → command → handler → aggregate

Domain: An HR system where employee records are synced from an external ERP.
The ERP sends camelCase JSON; our domain uses snake_case with different naming.
"""

import logging

from protean import Domain, handle
from protean.fields import Identifier, String

domain = Domain(__name__)
domain.config["message_processing"] = "sync"
domain.config["command_processing"] = "sync"

logger = logging.getLogger(__name__)


# --- Aggregate ---


@domain.aggregate
class Employee:
    """Employee aggregate in our HR domain."""

    employee_id: Identifier(identifier=True)
    full_name: String(required=True, max_length=200)
    email: String(required=True, max_length=200)
    department: String(max_length=100)
    source: String(default="direct")


# --- Commands ---


@domain.command(part_of="Employee")
class OnboardEmployee:
    """Command to onboard a new employee from external system."""

    employee_id: Identifier(required=True)
    full_name: String(required=True)
    email: String(required=True)
    department: String()
    source: String(default="erp")


@domain.command(part_of="Employee")
class UpdateEmployeeDepartment:
    """Command to update an employee's department."""

    employee_id: Identifier(required=True)
    department: String(required=True)


# --- Command Handler ---


@domain.command_handler(part_of=Employee)
class EmployeeCommandHandler:
    """Handles employee commands."""

    @handle(OnboardEmployee)
    def handle_onboard(self, command: OnboardEmployee):
        """Create a new employee from onboard command."""
        employee = Employee(
            employee_id=command.employee_id,
            full_name=command.full_name,
            email=command.email,
            department=command.department,
            source=command.source,
        )
        domain.repository_for(Employee).add(employee)

    @handle(UpdateEmployeeDepartment)
    def handle_update_department(self, command: UpdateEmployeeDepartment):
        """Update an employee's department."""
        employee = domain.repository_for(Employee).get(command.employee_id)
        employee.department = command.department
        domain.repository_for(Employee).add(employee)


# --- Subscriber (Anti-Corruption Layer) ---


@domain.subscriber(stream="erp_employee_events")
class ERPEmployeeSubscriber:
    """Anti-corruption layer for external ERP employee events.

    Translates external ERP event payloads into domain commands.
    This is the ONLY place that understands the external ERP format.

    External format:
        {
            "eventType": "employee.hired",
            "payload": {
                "empId": "EMP-001",
                "firstName": "Alice",
                "lastName": "Johnson",
                "emailAddr": "alice@corp.com",
                "dept": "Engineering"
            }
        }
    """

    def __call__(self, payload: dict) -> None:
        """Route external events to translation methods."""
        event_type = payload.get("eventType", "")

        if event_type == "employee.hired":
            self._handle_hired(payload["payload"])
        elif event_type == "employee.transferred":
            self._handle_transferred(payload["payload"])
        else:
            logger.warning("Unknown ERP event type: %s", event_type)

    def _handle_hired(self, data: dict) -> None:
        """Translate ERP employee.hired → OnboardEmployee command."""
        command = OnboardEmployee(
            employee_id=data["empId"],
            full_name=f"{data['firstName']} {data['lastName']}",
            email=data["emailAddr"],
            department=data.get("dept", ""),
            source="erp",
        )
        domain.process(command)

    def _handle_transferred(self, data: dict) -> None:
        """Translate ERP employee.transferred → UpdateEmployeeDepartment."""
        command = UpdateEmployeeDepartment(
            employee_id=data["empId"],
            department=data["newDept"],
        )
        domain.process(command)
