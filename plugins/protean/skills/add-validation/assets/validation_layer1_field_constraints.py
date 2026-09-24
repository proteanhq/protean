"""
Layer 1: Field Constraints

This example demonstrates:
- required, min_value, max_value for numeric fields
- min_length, max_length for string fields
- choices for enum validation
- default values
- Custom validators on fields (via validators=[])
- ValidationError behavior for each constraint type

Scenario:
    An Employee aggregate with various field-level constraints:
    name (required, length limits), age (range), department (enum choices),
    salary (positive), and employee_id (custom format).

Usage:
    emp = Employee(
        name="Jane Doe",
        age=30,
        department="ENGINEERING",
        salary=75000.0,
        employee_code="EMP-1234",
    )
"""

from enum import Enum

from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import Float, Integer, String
from protean.fields.validators import RegexValidator

# Domain setup
domain = Domain(__name__)


class Department(Enum):
    ENGINEERING = "ENGINEERING"
    MARKETING = "MARKETING"
    SALES = "SALES"
    HR = "HR"


# Custom validator for employee code format
employee_code_validator = RegexValidator(
    regex=r"^EMP-\d{4}$",
    message="Employee code must be in format EMP-NNNN",
)


@domain.aggregate
class Employee:
    """Employee aggregate demonstrating Layer 1 field constraints.

    Every constraint here is enforced automatically on field assignment.
    No invariants or manual checks are needed for these rules.
    """

    # Required + length constraints
    name: String(required=True, min_length=2, max_length=100)

    # Numeric range constraints
    age: Integer(required=True, min_value=18, max_value=120)

    # Enum choices constraint
    department: String(required=True, max_length=15, choices=Department)

    # Positive value constraint
    salary: Float(required=True, min_value=0.01)

    # Custom format validator
    employee_code: String(
        required=True,
        max_length=8,
        identifier=True,
        validators=[employee_code_validator],
    )

    # Default value
    status: String(max_length=10, default="active")

    # Optional field (no required=True)
    notes: String(max_length=500)


if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)
    with domain.domain_context():
        # Valid employee
        emp = Employee(
            name="Jane Doe",
            age=30,
            department="ENGINEERING",
            salary=75000.0,
            employee_code="EMP-1234",
        )
        print(f"Employee: {emp.name}, Dept: {emp.department}")
        print(f"Status default: {emp.status}")

        # Invalid: missing required field
        try:
            Employee(age=25, department="SALES", salary=50000, employee_code="EMP-0001")
        except ValidationError as e:
            print(f"Missing name: {e}")

        # Invalid: age out of range
        try:
            Employee(
                name="Too Young",
                age=15,
                department="HR",
                salary=30000,
                employee_code="EMP-0002",
            )
        except ValidationError as e:
            print(f"Age too low: {e}")

        # Invalid: bad department choice
        try:
            Employee(
                name="Bad Dept",
                age=25,
                department="FINANCE",
                salary=50000,
                employee_code="EMP-0003",
            )
        except ValidationError as e:
            print(f"Bad department: {e}")

        # Invalid: bad employee code format
        try:
            Employee(
                name="Bad Code",
                age=25,
                department="SALES",
                salary=50000,
                employee_code="INVALID",
            )
        except ValidationError as e:
            print(f"Bad code: {e}")
