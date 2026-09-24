"""
Use case with guards: Authorization and existence checks in handler.

This example demonstrates:
- Layer 4 authorization guard (role-based access control)
- Existence check before aggregate mutation
- Command with context field (requested_by_role)
- ValidationError with descriptive error keys
- Full flow: guard → load → mutate → persist → event

Domain: An expense approval system where only managers and finance staff
can approve expenses, and the expense must exist.
"""

from protean import Domain, handle
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String

domain = Domain(__name__)
domain.config["event_processing"] = "sync"


# --- Events ---


@domain.event(part_of="Expense")
class ExpenseSubmitted:
    """Raised when an expense is submitted."""

    expense_id: Identifier(required=True)
    submitter: String(required=True)
    amount: Float(required=True)
    description: String(required=True)


@domain.event(part_of="Expense")
class ExpenseApproved:
    """Raised when an expense is approved."""

    expense_id: Identifier(required=True)
    approved_by: String(required=True)


@domain.event(part_of="Expense")
class ExpenseRejected:
    """Raised when an expense is rejected."""

    expense_id: Identifier(required=True)
    rejected_by: String(required=True)
    reason: String(required=True)


# --- Aggregate ---


ALLOWED_APPROVERS = {"manager", "finance", "admin"}


@domain.aggregate
class Expense:
    """Expense aggregate for tracking expense reports."""

    submitter: String(required=True, max_length=100)
    amount: Float(required=True)
    description: String(required=True, max_length=500)
    status: String(default="pending")
    reviewed_by: String(max_length=100)

    @classmethod
    def submit(cls, submitter, amount, description):
        """Factory: submit a new expense."""
        expense = cls(submitter=submitter, amount=amount, description=description)
        expense.raise_(
            ExpenseSubmitted(
                expense_id=expense.id,
                submitter=submitter,
                amount=amount,
                description=description,
            )
        )
        return expense

    def approve(self, approved_by):
        """Approve this expense."""
        self.status = "approved"
        self.reviewed_by = approved_by
        self.raise_(ExpenseApproved(expense_id=self.id, approved_by=approved_by))

    def reject(self, rejected_by, reason):
        """Reject this expense."""
        self.status = "rejected"
        self.reviewed_by = rejected_by
        self.raise_(
            ExpenseRejected(expense_id=self.id, rejected_by=rejected_by, reason=reason)
        )


# --- Commands ---


@domain.command(part_of="Expense")
class SubmitExpense:
    """Command to submit a new expense."""

    submitter: String(required=True)
    amount: Float(required=True)
    description: String(required=True)


@domain.command(part_of="Expense")
class ApproveExpense:
    """Command to approve an expense."""

    expense_id: Identifier(required=True)
    approved_by: String(required=True)
    requested_by_role: String(required=True)


@domain.command(part_of="Expense")
class RejectExpense:
    """Command to reject an expense."""

    expense_id: Identifier(required=True)
    rejected_by: String(required=True)
    reason: String(required=True)
    requested_by_role: String(required=True)


# --- Command Handler ---


@domain.command_handler(part_of=Expense)
class ExpenseCommandHandler:
    """Handles expense commands with authorization guards."""

    @handle(SubmitExpense)
    def handle_submit(self, command: SubmitExpense):
        """Submit a new expense (no guard needed - anyone can submit)."""
        expense = Expense.submit(
            submitter=command.submitter,
            amount=command.amount,
            description=command.description,
        )
        domain.repository_for(Expense).add(expense)

    @handle(ApproveExpense)
    def handle_approve(self, command: ApproveExpense):
        """Approve an expense with authorization guard."""
        # Layer 4: Authorization guard
        if command.requested_by_role not in ALLOWED_APPROVERS:
            raise ValidationError(
                {
                    "authorization": [
                        "Only managers, finance, or admins can approve expenses"
                    ]
                }
            )

        # Layer 4: Existence check
        expense = domain.repository_for(Expense).get(command.expense_id)

        # Business logic
        expense.approve(approved_by=command.approved_by)
        domain.repository_for(Expense).add(expense)

    @handle(RejectExpense)
    def handle_reject(self, command: RejectExpense):
        """Reject an expense with authorization guard."""
        # Layer 4: Authorization guard
        if command.requested_by_role not in ALLOWED_APPROVERS:
            raise ValidationError(
                {
                    "authorization": [
                        "Only managers, finance, or admins can reject expenses"
                    ]
                }
            )

        # Layer 4: Existence check
        expense = domain.repository_for(Expense).get(command.expense_id)

        # Business logic
        expense.reject(rejected_by=command.rejected_by, reason=command.reason)
        domain.repository_for(Expense).add(expense)
