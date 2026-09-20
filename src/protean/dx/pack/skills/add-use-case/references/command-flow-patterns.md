# Command Flow Patterns

## Create pattern

The handler creates a new aggregate using a factory method.

```python
@handle(RegisterAccount)
def handle_register(self, command):
    account = Account.register(username=command.username, email=command.email)
    domain.repository_for(Account).add(account)
```

**When to use**: Creating new domain objects (registration, submission, initialization).

## Update pattern

The handler loads an existing aggregate, calls a method to mutate state, and persists.

```python
@handle(AssignTicket)
def handle_assign(self, command):
    ticket = domain.repository_for(Ticket).get(command.ticket_id)
    ticket.assign(assignee=command.assignee)
    domain.repository_for(Ticket).add(ticket)
```

**When to use**: Modifying existing domain objects (approval, assignment, status change).

## Guard pattern

The handler performs authorization or context checks before delegating to the aggregate.

```python
@handle(ApproveExpense)
def handle_approve(self, command):
    # Guard: authorization
    if command.requested_by_role not in ALLOWED_ROLES:
        raise ValidationError({"authorization": ["Not authorized"]})

    # Guard: existence
    expense = domain.repository_for(Expense).get(command.expense_id)

    # Business logic
    expense.approve(approved_by=command.approved_by)
    domain.repository_for(Expense).add(expense)
```

**When to use**: Actions requiring authorization, existence validation, or external context checks (Layer 4 validation).

## Key principles

1. **One command, one handler method** — Each command maps to exactly one handler method
2. **Handler orchestrates, aggregate decides** — Business logic belongs in the aggregate, not the handler
3. **Raise events in aggregate methods** — Events are raised inside `self.raise_()`, not in the handler
4. **Persist via repository** — Always use `domain.repository_for(Aggregate).add(aggregate)` to persist
5. **Implicit UnitOfWork** — Handler methods run in an implicit UnitOfWork, no manual transaction management
