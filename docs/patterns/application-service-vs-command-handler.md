# Choose Between Application Services and Command Handlers

## The Problem

Protean provides two mechanisms for coordinating state changes: **application
services** and **command handlers**. Both load aggregates, call domain methods,
and persist results. From the outside, they look interchangeable -- and that
is exactly why teams misuse them.

A developer building a user registration endpoint reaches for a command handler
because "commands sound right for changing state":

```python
@domain.command(part_of=User)
class RegisterUser(BaseCommand):
    email: String(required=True)
    name: String(required=True)
    password: String(required=True)


@domain.command_handler(part_of=User)
class UserCommandHandler(BaseCommandHandler):

    @handle(RegisterUser)
    def register(self, command: RegisterUser):
        repo = current_domain.repository_for(User)
        user = User(
            email=command.email,
            name=command.name,
        )
        user.set_password(command.password)
        repo.add(user)
```

The handler works, but the API endpoint needs the newly created user with its
generated ID. `domain.process()` is fire-and-forget by default -- it stores
the command and returns `None`. The developer forces synchronous execution:

```python
@app.post("/users")
def create_user(payload: CreateUserRequest):
    command = RegisterUser(
        email=payload.email,
        name=payload.name,
        password=payload.password,
    )
    # Force sync to get a return value -- fighting the abstraction
    domain.process(command, asynchronous=False)

    # But domain.process() doesn't return the user...
    # Now we have to query for it by email
    repo = domain.repository_for(User)
    user = repo._dao.query.filter(email=payload.email).first()
    return {"id": user.id, "email": user.email}
```

The code processes the command synchronously and then immediately queries for
the result -- two round-trips where one should suffice. The `asynchronous=False`
flag fights the command handler's natural purpose.

Meanwhile, another developer on the same team uses an application service for
processing incoming webhook events from a payment provider:

```python
@domain.application_service(part_of=Order)
class OrderService(BaseApplicationService):

    @use_case
    def handle_payment_confirmed(self, order_id, payment_id, amount):
        repo = current_domain.repository_for(Order)
        order = repo.get(order_id)
        order.confirm_payment(payment_id, amount)
        repo.add(order)
        return order
```

This works in development. But in production, payment confirmations should be
processed asynchronously -- the webhook needs to return `200 OK` immediately.
The application service cannot be invoked via `domain.process()`, so the
developer adds a queue, a worker, and a polling loop. Infrastructure that
Protean's command handler system already provides.

Both developers chose the wrong tool:

- **The registration endpoint** needs a synchronous return value -- an
  application service would have been simpler and more direct.

- **The payment webhook** needs asynchronous, reliable processing -- a command
  handler with `domain.process()` would have provided that out of the box.

The confusion has deeper consequences:

- **Inconsistent invocation patterns.** Some operations are triggered by
  direct method calls, others by `domain.process()`. The team cannot predict
  which pattern a given operation uses without reading the code.

- **Forced synchrony or forced asynchrony.** Using `asynchronous=False` on
  every `domain.process()` call defeats the purpose of command handlers. Using
  application services for operations that should be fire-and-forget requires
  building custom async infrastructure.

- **Duplicate coordination layers.** Some teams define both an application
  service and a command handler for the same operation "just in case," leading
  to two code paths that must be kept in sync.

The root cause: the team never established a decision rule for when to use
each mechanism.

---

## The Pattern

Choose based on the **caller's needs**, not the operation's name.

### The Decision Tree

```
Does the caller need a return value immediately?
│
├── YES → Application Service
│         (direct invocation, synchronous, returns data)
│
└── NO
    │
    ├── Could this be processed in the background?
    │   │
    │   ├── YES → Command Handler
    │   │         (domain.process(), async by default)
    │   │
    │   └── NO → Application Service
    │             (direct invocation, synchronous)
    │
    └── Is this triggered by a domain event or external message?
        │
        └── YES → Command Handler
                  (domain.process() from event handler or subscriber)
```

### The Core Distinction

| Aspect | Application Service | Command Handler |
|--------|-------------------|-----------------|
| Invocation | Direct method call | `domain.process(command)` |
| Return value | Always returns a result | Fire-and-forget by default |
| Execution | Always synchronous | Async by default, sync optional |
| Caller | API endpoints, CLI, tests | Events, subscribers, scheduled jobs |
| Decorator | `@use_case` | `@handle(Command)` |
| Transaction | Wrapped in UoW by `@use_case` | Wrapped in UoW by engine |
| Idempotency | Caller's responsibility | Built-in via `idempotency_key` |

### The Rule

**Never define both an application service method and a command handler for the
same aggregate operation.** One operation, one coordination path. If your
context is primarily API-driven, lean toward application services. If it is
event-driven with background processing, lean toward command handlers.

---

## Applying the Pattern

### Application Service: User Registration

The API endpoint needs to return the newly created user with its ID -- a
direct, synchronous operation.

```python
# --- Domain elements ---

@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    email: String(required=True, max_length=255)
    name: String(required=True, max_length=100)
    password_hash: String(max_length=255)
    status: String(default="pending")
    registered_at: DateTime()

    def register(self, password: str) -> None:
        """Complete the registration process."""
        self.password_hash = self._hash_password(password)
        self.status = "active"
        self.registered_at = datetime.now(timezone.utc)

        self.raise_(UserRegistered(
            user_id=self.user_id,
            email=self.email,
            name=self.name,
        ))

    def _hash_password(self, password: str) -> str:
        import hashlib
        return hashlib.sha256(password.encode()).hexdigest()


@domain.event(part_of=User)
class UserRegistered(BaseEvent):
    user_id: Identifier(required=True)
    email: String(required=True)
    name: String(required=True)


# --- Application Service ---

@domain.application_service(part_of=User)
class UserService(BaseApplicationService):

    @use_case
    def register_user(self, email: str, name: str, password: str) -> User:
        """Register a new user and return the created user.

        The @use_case decorator wraps this method in a UnitOfWork,
        so the aggregate is persisted and events are published
        automatically when the method returns.
        """
        repo = current_domain.repository_for(User)
        user = User(email=email, name=name)
        user.register(password)
        repo.add(user)
        return user  # (1)
```

1. The application service returns the user directly. The caller receives the
   fully constructed aggregate with its generated ID.

The API endpoint uses the service directly:

```python
@app.post("/users", status_code=201)
def create_user(payload: CreateUserRequest):
    service = UserService()
    user = service.register_user(
        email=payload.email,
        name=payload.name,
        password=payload.password,
    )
    return {
        "id": str(user.user_id),
        "email": user.email,
        "name": user.name,
        "status": user.status,
    }
```

No `domain.process()`, no command object, no async/sync flag. The `@use_case`
decorator wraps the method in a `UnitOfWork`, so the aggregate is persisted
and events are published when the method returns.

### Command Handler: Order Payment Processing

Payment confirmations arrive from an external webhook. The webhook must return
`200 OK` immediately -- a fire-and-forget operation.

```python
# --- Domain elements ---

@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    status: String(default="draft")
    total: Float(default=0.0)
    payment_id: String()
    paid_at: DateTime()

    def confirm_payment(self, payment_id: str, amount: float) -> None:
        """Confirm that payment has been received."""
        if self.status != "pending_payment":
            raise ValidationError(
                {"status": ["Only orders pending payment can be confirmed"]}
            )

        if amount < self.total:
            raise ValidationError(
                {"amount": ["Payment amount is less than order total"]}
            )

        self.status = "paid"
        self.payment_id = payment_id
        self.paid_at = datetime.now(timezone.utc)

        self.raise_(OrderPaid(
            order_id=self.order_id,
            customer_id=self.customer_id,
            payment_id=payment_id,
            amount=amount,
        ))


@domain.command(part_of=Order)
class ConfirmPayment(BaseCommand):
    order_id: Identifier(required=True)
    payment_id: String(required=True)
    amount: Float(required=True)


@domain.event(part_of=Order)
class OrderPaid(BaseEvent):
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    payment_id: String(required=True)
    amount: Float(required=True)


# --- Command Handler ---

@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(ConfirmPayment)
    def confirm_payment(self, command: ConfirmPayment):
        """Process the payment confirmation.

        This handler is invoked by the Protean engine when it reads
        the ConfirmPayment command from the event store. The engine
        wraps the handler in a UoW automatically.
        """
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.confirm_payment(command.payment_id, command.amount)
        repo.add(order)
```

The webhook endpoint dispatches the command and returns immediately:

```python
@app.post("/webhooks/payment", status_code=200)
def payment_webhook(payload: PaymentWebhookPayload):
    domain.process(
        ConfirmPayment(
            order_id=payload.order_id,
            payment_id=payload.payment_id,
            amount=payload.amount,
        )
    )
    return {"status": "accepted"}
```

`domain.process()` stores the command in the event store and returns. The
Protean server picks up the command and routes it to the handler. The webhook
never waits for the order update.

### The Decision Tree in Action

| Scenario | Needs return value? | Async possible? | Event-triggered? | Choice |
|----------|-------------------|-----------------|-----------------|--------|
| Create a product listing | Yes (return the product with ID) | No | No | Application service |
| Place an order from the cart | Yes (return order confirmation) | No | No | Application service |
| Process a refund request | No (customer sees "processing") | Yes | No | Command handler |
| Reserve inventory after order placed | No | Yes | Yes (OrderPlaced event) | Command handler |
| Update user profile | Yes (return updated profile) | No | No | Application service |
| Send welcome email after registration | No | Yes | Yes (UserRegistered event) | Event handler (not a command handler) |
| Cancel expired orders (scheduled job) | No | Yes | No | Command handler |
| Look up order details for display | Yes (return order) | No | No | Neither -- use repository directly or query handler |

### Synchronous Command Processing

Sometimes a command handler makes sense for the domain model, but the caller
needs the result during development or testing. Protean supports this with
two mechanisms:

**Per-call override:**

```python
# Force synchronous processing for this specific call
result = domain.process(
    ConfirmPayment(order_id="ord-123", payment_id="pay-456", amount=99.99),
    asynchronous=False,
)
```

**Global configuration:**

```toml
# domain.toml
[command_processing]
mode = "sync"
```

Use per-call overrides sparingly -- in tests or development only. If you find
yourself setting `asynchronous=False` on every `domain.process()` call, you
probably want an application service instead.

---

## Anti-Patterns

### Defining Both for the Same Operation

```python
# Anti-pattern: two coordination paths for the same operation

@domain.application_service(part_of=Order)
class OrderService(BaseApplicationService):

    @use_case
    def place_order(self, customer_id, items):
        # Path 1: direct invocation from API
        repo = current_domain.repository_for(Order)
        order = Order(customer_id=customer_id)
        for item in items:
            order.add_item(**item)
        order.place()
        repo.add(order)
        return order


@domain.command(part_of=Order)
class PlaceOrder(BaseCommand):
    customer_id: Identifier(required=True)
    items: List(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        # Path 2: async invocation from domain.process()
        repo = current_domain.repository_for(Order)
        order = Order(customer_id=command.customer_id)
        for item in command.items:
            order.add_item(**item)
        order.place()
        repo.add(order)
```

Two code paths doing the same thing. When business rules change, both must be
updated. When a bug is found, it might exist in one path but not the other.

**Fix:** Choose one. If the API needs to return the order, use the application
service. If order placement should be async, use the command handler. Not both.

### Forcing Async When Sync Is Needed

```python
# Anti-pattern: command handler for a synchronous use case

@app.post("/products")
def create_product(payload: CreateProductRequest):
    domain.process(
        CreateProduct(name=payload.name, price=payload.price),
        asynchronous=False,  # Always forcing sync
    )
    # Now we have to query for the product we just created
    repo = domain.repository_for(Product)
    products = repo._dao.query.filter(name=payload.name).all().items
    return {"id": str(products[0].product_id), "name": products[0].name}
```

If you always force synchronous processing and query for the result afterward,
the command handler is the wrong tool:

```python
# Fix: application service for synchronous use case

@domain.application_service(part_of=Product)
class ProductService(BaseApplicationService):

    @use_case
    def create_product(self, name: str, price: float) -> Product:
        repo = current_domain.repository_for(Product)
        product = Product(name=name, price=price)
        repo.add(product)
        return product


@app.post("/products")
def create_product(payload: CreateProductRequest):
    service = ProductService()
    product = service.create_product(
        name=payload.name,
        price=payload.price,
    )
    return {"id": str(product.product_id), "name": product.name}
```

### Using Application Services for Event Reactions

```python
# Anti-pattern: application service called from an event handler

@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # Calling an application service from an event handler
        service = InventoryService()
        service.reserve_inventory(
            product_id=event.product_id,
            quantity=event.quantity,
        )
```

Application services are for external callers (APIs, CLIs), not event-driven
reactions. The event handler already runs inside the engine's processing
pipeline. Calling an application service introduces a nested `UnitOfWork`
(from `@use_case`) inside the event handler's own UoW.

**Fix:** Put the coordination logic directly in the event handler:

```python
@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(event.product_id)
        inventory.reserve(event.quantity)
        repo.add(inventory)
```

Or, if the reaction should produce a command for another aggregate, use
`domain.process()` from within the event handler:

```python
@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        current_domain.process(
            ReserveInventory(
                product_id=event.product_id,
                quantity=event.quantity,
                order_id=event.order_id,
            )
        )
```

### Mixing Invocation Styles Within a Bounded Context

```python
# Anti-pattern: inconsistent coordination within the same context

# Some operations use application services
class OrderService(BaseApplicationService):
    @use_case
    def place_order(self, ...): ...

    @use_case
    def cancel_order(self, ...): ...

# Other operations on the same aggregate use command handlers
class OrderCommandHandler(BaseCommandHandler):
    @handle(ShipOrder)
    def ship_order(self, ...): ...

    @handle(ConfirmPayment)
    def confirm_payment(self, ...): ...
```

A developer looking at the `Order` aggregate sees four operations split across
two coordination mechanisms with no clear rationale. Is it intentional that
placement and cancellation are synchronous while shipping and payment are
async? Or accidental?

**Fix:** Be consistent. If the context is API-driven, use application services
for all API-triggered operations. If a specific operation must be async
(event-triggered or webhook-driven), use a command handler and document why.

---

## Summary

| Dimension | Application Service | Command Handler |
|-----------|-------------------|-----------------|
| **How it's invoked** | `service = MyService()` then `service.method(...)` | `domain.process(command)` |
| **Return value** | Always returns a result to the caller | `None` by default (fire-and-forget) |
| **Execution model** | Synchronous (always) | Async by default, sync with `asynchronous=False` |
| **Transaction management** | `@use_case` wraps in `UnitOfWork` | Engine wraps in `UnitOfWork` |
| **Idempotency** | Caller must implement | Built-in via `idempotency_key` param |
| **Best for** | API-to-aggregate operations needing immediate results | Event-driven, background, and decoupled processing |
| **Triggered by** | API endpoints, CLI handlers, tests | Domain events, subscribers, webhooks, scheduled jobs |
| **Decorator** | `@domain.application_service(part_of=...)` | `@domain.command_handler(part_of=...)` |
| **Method decorator** | `@use_case` | `@handle(CommandClass)` |
| **Requires command object** | No (takes plain arguments) | Yes (typed command class) |
| **Processing config** | Not applicable | `command_processing` in `domain.toml` |
| **Priority lanes** | Not applicable | Supported via `priority` param |

**The principle: if the caller needs the answer now, use an application
service. If the caller can walk away and let the system handle it, use a
command handler. Never both for the same operation.**

---

!!! tip "Related reading"
    **Patterns:**

    - [Thin Handlers, Rich Domain](thin-handlers-rich-domain.md) -- Business logic belongs in aggregates, not coordinators.
    - [Encapsulate State Changes](encapsulate-state-changes.md) -- Named methods for every state transition.

    **Concepts:**

    - [Application Services](../concepts/building-blocks/application-services.md) -- Synchronous use case coordination.
    - [Command Handlers](../concepts/building-blocks/command-handlers.md) -- Async command processing.

    **Guides:**

    - [Application Services](../guides/change-state/application-services.md) -- Defining application services.
    - [Command Handlers](../guides/change-state/command-handlers.md) -- Defining command handlers.
