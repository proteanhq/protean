---
name: command-handler
description: Define a Protean command handler, a class responsible for receiving domain commands and orchestrating state changes in aggregates. Command handlers extract data from commands, load or create aggregates, invoke aggregate methods, and persist state changes. They are always associated with one aggregate via part_of and use the @handle decorator to process specific command types. Use when you need to process a command, handle a domain action, write a command handler, implement the handler for a command, connect a command to aggregate logic, or implement the write side of CQRS. Each handler method runs within an implicit UnitOfWork for transactional safety.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
  diagnostic_codes:
    - COMMAND_HANDLER_CROSS_CLUSTER
    - HANDLER_TOO_BROAD
    - HANDLER_PERSISTS_AND_CALLS_OUT
---

# Command Handler

A command handler turns one aggregate's commands into changes to that aggregate: it loads or creates the aggregate, calls a method on it, and persists it. This skill defines handlers, their options, and how they fail.

## Basic structure

```python
from protean import Domain, handle
from protean.fields import Identifier, String

domain = Domain()

@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    status: String(default="draft")

    def place(self):
        self.status = "placed"

@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)

@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        order = Order(order_id=command.order_id)
        order.place()
        domain.repository_for(Order).add(order)
```

## Key rules

1. **part_of is required**: Handler must be associated with an aggregate: `@domain.command_handler(part_of=Order)`
2. **Commands must match the same aggregate**: Commands handled must have `part_of` pointing to the SAME aggregate as the handler
3. **One handler per command**: A command can only be processed by ONE handler (Protean enforces this)
4. **Use @handle decorator**: Each handler method is decorated with `@handle(CommandClass)`
5. **Handler methods take self and command**: Signature: `def method_name(self, command: CommandClass)`
6. **Implicit Unit of Work**: `@handle` wraps every handler call in its own Unit of Work, which is one real database transaction on a provider with transactions, such as the SQL databases ([ADR-0027](https://docs.proteanhq.com/adr/0027-unit-of-work-is-a-real-transaction/)). Do not wrap the body yourself. See [Unit of Work](references/unit-of-work.md)
7. **Change one aggregate per transaction**: A handler should persist one aggregate root. This is a design rule: the Unit of Work can hold changes to several aggregates and does not stop you. To change another aggregate, raise an event; an event handler in the owning aggregate's cluster issues a command to the other aggregate
8. **Import handle from protean**: `from protean import handle` (not from protean.core)
9. **part_of on a handler takes the class or a string**: A handler usually passes the class, `part_of=AggregateClass`. A string, `part_of="AggregateName"`, also works on the handler and resolves at `init`, so the aggregate may be defined after the handler. Commands use the string form

## Handler options

| Option | Default | Description |
|--------|---------|-------------|
| `part_of` | `None` | The aggregate this handler belongs to, as a class or a string name. Required: registration fails without it |
| `stream_category` | derived from part_of | The command stream the handler reads, `<aggregate stream category>:command`. Always derived from the aggregate; a value you pass is replaced |
| `timeout` | `None` | Default validity window, in seconds or a `timedelta`, for commands this handler processes. Overrides the domain's `command_default_timeout`; a deadline or timeout passed to `domain.process()` overrides both |
| `retries` | `None` | Maximum retries when the handler fails with a transient exception. Overrides the domain's `server.transient_retry` setting; `None` uses that setting |
| `backoff` | `None` | Delay strategy between transient retries: `"exponential"`, `"linear"` or `"fixed"`. `None` uses the domain setting |
| `retry_exceptions` | `None` | Exception types treated as transient, as classes or dotted paths. `None` uses the domain setting |
| `sequential_by` | `None` | Name of an attribute on every command this handler handles. Registration checks that every handled command has the attribute. Commands do not go through the outbox yet, so they are not split by this value. See [Sequential processing](https://docs.proteanhq.com/reference/server/sequential-by/) for what the option does on a command handler today |
| `subscription_type` | `None` | `SubscriptionType` for the server's subscription. `None` uses the default |
| `subscription_profile` | `None` | `SubscriptionProfile` preset for the subscription. `None` uses the default |
| `subscription_config` | `{}` | Custom subscription settings that override the type and profile defaults |
| `suppress_checks` | `()` | Diagnostic codes `protean check` should not report for this handler |

## Quick example: Multiple commands

```python
@domain.aggregate
class Account:
    account_id: Identifier(identifier=True)
    email: String(required=True)
    status: String(default="pending")

    def activate(self):
        self.status = "active"

@domain.command(part_of="Account")
class RegisterAccount:
    account_id: Identifier(required=True)
    email: String(required=True)

@domain.command(part_of="Account")
class ActivateAccount:
    account_id: Identifier(required=True)

@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(RegisterAccount)
    def handle_register(self, command: RegisterAccount):
        account = Account(
            account_id=command.account_id,
            email=command.email,
        )
        domain.repository_for(Account).add(account)

    @handle(ActivateAccount)
    def handle_activate(self, command: ActivateAccount):
        account = domain.repository_for(Account).get(command.account_id)
        account.activate()
        domain.repository_for(Account).add(account)
```

## Error handling

Override `handle_error` classmethod for custom error recovery during async processing:

```python
import logging

from protean.fields import Decimal, Identifier, String

logger = logging.getLogger(__name__)

@domain.aggregate
class Payment:
    payment_id: Identifier(identifier=True)
    amount: Decimal(precision=19, scale=4, required=True)
    status: String(default="pending")

    def execute(self):
        self.status = "completed"

@domain.command(part_of="Payment")
class TransferFunds:
    payment_id: Identifier(required=True)
    amount: Decimal(precision=19, scale=4, required=True)

@domain.command_handler(part_of=Payment)
class PaymentCommandHandler:
    @handle(TransferFunds)
    def handle_transfer(self, command: TransferFunds):
        payment = Payment(payment_id=command.payment_id, amount=command.amount)
        payment.execute()
        domain.repository_for(Payment).add(payment)

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        logger.error(f"Payment failed: {exc}")
```

## Processing commands

Initialize the domain once every element is registered, then process commands inside a domain context:

```python
domain.init(traverse=False)

with domain.domain_context():
    # Synchronous - blocks until done, returns handler result
    result = domain.process(PlaceOrder(order_id="ORD-001"), asynchronous=False)

    # Asynchronous (default) - returns position in event store
    position = domain.process(PlaceOrder(order_id="ORD-002"))
```

## Common mistakes

### Wrapping in UnitOfWork manually

```python
# fragment
@handle(PlaceOrder)
def handle_place_order(self, command):
    with UnitOfWork():  # Unnecessary! Already implicit
        order = Order(order_id=command.order_id)
        domain.repository_for(Order).add(order)
```

Instead: Let the implicit Unit of Work handle it. A `with UnitOfWork():` inside the handler joins the outer one and adds nothing.

### What `check` reports

`check` inspects your command handlers and reports these diagnostics:

- `COMMAND_HANDLER_CROSS_CLUSTER`: the handler processes a command that belongs to another cluster, which puts that aggregate's write path outside its own consistency boundary. Move the handler into the owning cluster, or model the interaction as an event reaction across the boundary.
- `HANDLER_TOO_BROAD`: the handler handles more message types than the configured `[lint] handler_breadth_limit`, so it has grown into a catch-all. Split it into focused handlers, or raise the limit if the breadth is intentional.
- `HANDLER_PERSISTS_AND_CALLS_OUT`: one handler method calls an external system after its first `repository_for(...)`, so the call runs with the Unit of Work's transaction open, holding row locks and a pooled connection for as long as the call takes, and a retry re-runs the method and re-issues the call. A call made before any repository access runs outside the transaction and is not flagged. Split the method into one that persists and one that calls out; when the call must follow the write, have the persisting method raise an event and handle that. If the write genuinely needs the call's result, keep both and pass the remote system's idempotency key so a retry does not duplicate the effect.

## Detailed references

### Core Concepts
- [Loading Aggregates](references/loading-aggregates.md): Hydrating aggregates from the repository
- [Unit of Work](references/unit-of-work.md): The transaction each handler call runs in
- [Error Handling](references/error-handling.md): Custom error recovery with handle_error
- [Return Values](references/return-values.md): Returning data from handlers
- [Anti-patterns](references/anti-patterns.md): Common mistakes and how to avoid them

### Complete Examples
- [Simple Handler](assets/command_handler_simple.py): Basic handler with one command
- [Multiple Commands](assets/command_handler_multiple_commands.py): Handler with multiple @handle methods
- [Handler with Events](assets/command_handler_with_events.py): Aggregate raises events during handling
- [Error Handling](assets/command_handler_error_handling.py): Custom handle_error classmethod
- [Create Aggregate](assets/command_handler_create_aggregate.py): Creating new aggregates vs. loading

### Related Skills
- `command`: Commands are the input to command handlers
- `aggregate`: Command handlers operate on aggregates
- `event`: Aggregates may raise events during handler processing
- `event-handler`: Downstream processing of events raised during command handling

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
