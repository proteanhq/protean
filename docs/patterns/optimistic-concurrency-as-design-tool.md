# Use Optimistic Concurrency as a Design Tool

## The Problem

Protean tracks aggregate versions automatically. Every aggregate carries a
`_version` field, and when the `UnitOfWork` commits, the framework checks
that the version in the database matches what was loaded. If another
transaction modified the aggregate in the meantime, the commit raises
`ExpectedVersionError`.

Most teams treat this error as infrastructure noise -- a generic "something
went wrong, try again" situation:

```python
from protean.exceptions import ExpectedVersionError


@domain.application_service(part_of=Order)
class OrderService(BaseApplicationService):

    @use_case
    def update_order(self, order_id: str, data: dict) -> Order:
        repo = current_domain.repository_for(Order)
        order = repo.get(order_id)

        order.update_details(**data)
        repo.add(order)
        return order
```

When two users edit the same order concurrently, one of them gets an
`ExpectedVersionError`. The API layer catches it and returns a generic
HTTP 409:

```python
# In the API layer
try:
    order_service.update_order(order_id, data)
except ExpectedVersionError:
    return {"error": "Conflict. Please try again."}, 409
```

This is correct mechanically -- the version check prevented data corruption.
But it is lazy architecturally. The user sees "try again" with no explanation
of what happened, what they lost, or whether trying again will even work.

Worse, the same generic handler is used whether the conflict is:

- Two users changing display settings at the same time (harmless -- either
  value is fine)
- Two users booking the same concert seat (critical -- one of them must be
  told the seat is taken)
- Two users adding items to a shared shopping cart (mergeable -- both
  additions can coexist)

These are fundamentally different situations that deserve fundamentally
different responses. A version conflict is not a failure -- it is a
**signal** that tells you something meaningful about how your domain is
being used under contention.

---

## The Pattern

Stop treating `ExpectedVersionError` as a generic infrastructure error.
Instead, classify version conflicts by their **business meaning** and handle
each category deliberately.

There are three categories:

### 1. Last writer wins

The conflict does not matter. Either value is acceptable. Reload the
aggregate, apply the change again, and persist.

**Examples:** user preferences, display settings, notification toggles,
profile descriptions.

### 2. Conflict means a real problem

The conflict signals that the operation is no longer valid. Catch the error
and raise a domain-specific exception that tells the user exactly what
happened.

**Examples:** seat reservations, inventory allocation, one-time coupon
redemption, unique username registration.

### 3. Merge if possible

The conflict does not invalidate the operation, but you cannot blindly
overwrite. Load the latest version, check whether the specific change still
makes sense, and either apply it or reject it with a clear explanation.

**Examples:** adding items to a shared cart, appending tags to a document,
collaborative editing of independent fields.

For **event-sourced aggregates**, version conflicts carry even more weight.
The event store uses `_version` to prevent contradictory event sequences from
being appended. An `ExpectedVersionError` from the event store is the system
working correctly -- it prevents an impossible history from being recorded.
Silencing it with a blind retry can introduce logical contradictions in the
event stream.

---

## Applying the Pattern

### Category 1: Last writer wins -- retry loop

When concurrent changes are harmless and either outcome is acceptable, catch
the version conflict, reload the aggregate with the latest version, reapply
the operation, and commit.

```python
from protean.exceptions import ExpectedVersionError


@domain.aggregate
class UserPreferences(BaseAggregate):
    user_id: Auto(identifier=True)
    theme: String(default="light")
    language: String(default="en")
    notifications_enabled: Boolean(default=True)
    sidebar_collapsed: Boolean(default=False)

    def update_theme(self, theme: str) -> None:
        self.theme = theme
        self.raise_(ThemeUpdated(
            user_id=self.user_id,
            theme=theme,
        ))

    def toggle_notifications(self, enabled: bool) -> None:
        self.notifications_enabled = enabled
        self.raise_(NotificationsToggled(
            user_id=self.user_id,
            enabled=enabled,
        ))
```

The application service implements a retry loop. If a version conflict
occurs, the operation is safe to retry because each change is independent
and idempotent -- setting the theme to "dark" produces the same result
regardless of how many times it runs.

```python
MAX_RETRIES = 3


@domain.application_service(part_of=UserPreferences)
class PreferencesService(BaseApplicationService):

    @use_case
    def update_theme(self, user_id: str, theme: str) -> UserPreferences:
        for attempt in range(MAX_RETRIES):
            try:
                repo = current_domain.repository_for(UserPreferences)
                prefs = repo.get(user_id)
                prefs.update_theme(theme)
                repo.add(prefs)
                return prefs
            except ExpectedVersionError:
                if attempt == MAX_RETRIES - 1:
                    raise
                continue
```

!!! note "Why not retry everything?"
    A retry loop is appropriate here because `update_theme` is a **set-based
    operation** -- the result depends only on the input, not on the previous
    state. For additive operations (incrementing a counter, appending to a
    list), blind retries can produce incorrect results. Always verify that
    the operation is safe to repeat before adding a retry loop.

### Category 2: Conflict means a real problem -- business exception

When a version conflict means the operation is no longer valid, catch the
error and translate it into a domain-specific exception. The caller gets a
clear, actionable message instead of a generic "try again."

```python
@domain.aggregate
class SeatReservation(BaseAggregate):
    reservation_id: Auto(identifier=True)
    event_id: Identifier(required=True)
    seat_number: String(required=True)
    status: String(default="available")
    reserved_by: Identifier()
    reserved_at: DateTime()

    def reserve(self, customer_id: str) -> None:
        """Reserve this seat for a customer."""
        if self.status != "available":
            raise ValidationError(
                {"seat": [f"Seat {self.seat_number} is already taken"]}
            )

        self.status = "reserved"
        self.reserved_by = customer_id
        self.reserved_at = datetime.now(timezone.utc)

        self.raise_(SeatReserved(
            reservation_id=self.reservation_id,
            event_id=self.event_id,
            seat_number=self.seat_number,
            customer_id=customer_id,
        ))
```

The command handler translates the version conflict into a business-level
exception. If two customers try to reserve the same seat simultaneously,
one succeeds and the other learns that the seat is taken -- not that a
vague "conflict" occurred.

```python
class SeatAlreadyTaken(Exception):
    """Raised when a seat reservation fails because
    another customer reserved the seat first."""

    def __init__(self, seat_number: str):
        self.seat_number = seat_number
        super().__init__(
            f"Seat {seat_number} was just reserved by another customer"
        )


@domain.command_handler(part_of=SeatReservation)
class ReservationCommandHandler(BaseCommandHandler):

    @handle(ReserveSeat)
    def reserve_seat(self, command: ReserveSeat):
        repo = current_domain.repository_for(SeatReservation)
        reservation = repo.get(command.reservation_id)

        try:
            reservation.reserve(command.customer_id)
            repo.add(reservation)
        except ExpectedVersionError:
            # Another customer reserved this seat between our
            # load and commit. This is not a transient failure --
            # it means the seat is genuinely taken.
            raise SeatAlreadyTaken(reservation.seat_number)
```

The API layer can now give the customer a meaningful response:

```python
@app.post("/events/{event_id}/seats/{seat_number}/reserve")
async def reserve_seat(event_id: str, seat_number: str, customer_id: str):
    try:
        domain.process(ReserveSeat(
            reservation_id=f"{event_id}-{seat_number}",
            customer_id=customer_id,
        ))
        return {"status": "reserved"}
    except SeatAlreadyTaken as exc:
        return {
            "error": str(exc),
            "suggestion": "Please choose a different seat.",
        }, 409
```

!!! warning "Do not retry category 2 conflicts"
    Retrying a seat reservation after an `ExpectedVersionError` will either
    fail again (because the seat is now marked as reserved and the aggregate's
    precondition check will reject it) or, worse, succeed and double-book the
    seat if the precondition logic has a gap. The conflict *is* the answer:
    someone else got there first.

### Category 3: Merge if possible -- conditional retry

When the operation might still be valid despite the conflict, reload the
aggregate, check whether the specific change is still applicable, and
either apply it or reject it with a clear explanation.

```python
@domain.aggregate
class SharedCart(BaseAggregate):
    cart_id: Auto(identifier=True)
    team_id: Identifier(required=True)
    items = HasMany(CartItem)
    max_items: Integer(default=50)

    def add_item(self, product_id: str, quantity: int) -> None:
        """Add an item to the shared cart."""
        if len(self.items) >= self.max_items:
            raise ValidationError(
                {"items": [f"Cart cannot exceed {self.max_items} items"]}
            )

        # Check if item already exists and update quantity
        for item in self.items:
            if item.product_id == product_id:
                item.quantity += quantity
                self.raise_(CartItemUpdated(
                    cart_id=self.cart_id,
                    product_id=product_id,
                    new_quantity=item.quantity,
                ))
                return

        self.items.add(CartItem(
            product_id=product_id,
            quantity=quantity,
        ))
        self.raise_(CartItemAdded(
            cart_id=self.cart_id,
            product_id=product_id,
            quantity=quantity,
        ))
```

The application service reloads and checks whether the add-item operation
is still valid on the latest version. Two team members adding different
items simultaneously should both succeed. Two members adding the same item
need the quantities merged correctly.

```python
@domain.application_service(part_of=SharedCart)
class SharedCartService(BaseApplicationService):

    @use_case
    def add_item(
        self, cart_id: str, product_id: str, quantity: int
    ) -> SharedCart:
        for attempt in range(MAX_RETRIES):
            try:
                repo = current_domain.repository_for(SharedCart)
                cart = repo.get(cart_id)

                # Check if the operation still makes sense
                # on the latest version
                if len(cart.items) >= cart.max_items:
                    raise ValidationError(
                        {"items": ["Cart is full. Remove items first."]}
                    )

                cart.add_item(product_id, quantity)
                repo.add(cart)
                return cart
            except ExpectedVersionError:
                if attempt == MAX_RETRIES - 1:
                    raise
                # Reload and re-evaluate on next iteration
                continue
```

The difference from a simple retry loop (category 1) is the
**re-evaluation**. On each attempt, the latest version is loaded and the
preconditions are checked again. If another team member's concurrent change
pushed the cart past `max_items`, the operation is rejected with a clear
reason instead of blindly retried.

---

## Framework auto-retry and when it is not enough

Protean automatically retries `ExpectedVersionError` at the `@handle`
wrapper level. When a handler raises a version conflict, the framework
catches it, waits with exponential backoff, and re-executes the handler
in a **fresh `UnitOfWork`** -- so the aggregate is re-read at the latest
version. This happens transparently, before the error reaches the
subscription retry pipeline. By default, the framework retries up to 3
times with 50 ms initial backoff (350 ms worst case).

This auto-retry is the right behavior for **category 1** (last writer
wins) conflicts. The handler re-reads the aggregate and reapplies the
change -- which is safe because either value is acceptable. In many
cases, you do not need to write manual retry loops for category 1
scenarios because the framework handles it.

However, auto-retry alone is **not sufficient** for categories 2 and 3:

- **Category 2** (conflict means a real problem): The handler should
  catch `ExpectedVersionError` *inside* the handler method and translate
  it into a domain-specific exception (e.g., `SeatAlreadyTaken`). The
  framework's auto-retry will re-execute the handler, but the handler
  itself must recognize that the operation is no longer valid and raise
  accordingly. If the handler does not catch the error, the framework
  retries blindly -- which is exactly what category 2 conflicts should
  avoid.

- **Category 3** (merge if possible): The handler must reload the
  aggregate and re-evaluate preconditions. The framework's fresh
  `UnitOfWork` gives you the latest aggregate state, but your handler
  code must implement the merge logic. Simple re-execution works only
  when the operation is idempotent.

!!! note "When to catch `ExpectedVersionError` inside your handler"
    If your handler deals with category 2 or 3 conflicts, catch
    `ExpectedVersionError` inside the handler method and handle it
    explicitly. When you catch it inside the handler, the framework's
    auto-retry does not trigger (because no exception propagates out of
    the handler).

    If you do **not** catch it, the framework retries the entire handler
    automatically. This is safe for category 1 conflicts but may produce
    incorrect results for categories 2 and 3.

For auto-retry configuration, see
[Version conflict auto-retry](../guides/server/error-handling.md#version-conflict-auto-retry).
To disable auto-retry entirely, set `enabled = false` in
`[server.version_retry]`.

---

## Anti-Patterns

### Generic catch-all handler

The most common anti-pattern: catching `ExpectedVersionError` at the API
boundary and returning a generic message for all conflict types.

```python
# Anti-pattern: one handler for all conflicts
@app.exception_handler(ExpectedVersionError)
async def handle_version_conflict(request, exc):
    return JSONResponse(
        status_code=409,
        content={"error": "Conflict detected. Please try again."},
    )
```

This tells the user nothing useful. Was their seat taken? Did their cart
change? Is their data lost? The caller cannot distinguish between a harmless
race condition and a fundamental problem.

### Blind retry on all conflicts

Wrapping every operation in a retry loop without considering the semantics.

```python
# Anti-pattern: retry without considering the operation type
def with_retry(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return func()
        except ExpectedVersionError:
            if attempt == max_retries - 1:
                raise
```

This is dangerous for category 2 conflicts (seat booking, inventory
reservation). Retrying a failed reservation might succeed on a different
version of the aggregate, producing a double booking. It is also wrong for
additive operations unless the handler explicitly re-evaluates preconditions
on the reloaded aggregate.

!!! note "How this differs from framework auto-retry"
    Protean's built-in auto-retry at the `@handle` level **also** retries
    blindly -- which is correct for category 1 conflicts (the vast
    majority). For categories 2 and 3, your handler must catch
    `ExpectedVersionError` inside the handler method and apply the
    appropriate strategy. When you catch it inside the handler, the
    framework's retry does not trigger.

### Ignoring version conflicts entirely

Suppressing the error and returning success.

```python
# Anti-pattern: swallowing the error
@handle(UpdateInventory)
def update_inventory(self, command):
    try:
        repo = current_domain.repository_for(Inventory)
        inv = repo.get(command.product_id)
        inv.adjust_quantity(command.delta)
        repo.add(inv)
    except ExpectedVersionError:
        pass  # "It'll sort itself out"
```

It will not sort itself out. The caller believes the operation succeeded.
Downstream systems may act on that assumption. Inventory counts will drift
from reality.

### Oversized aggregates that amplify contention

When an aggregate is too large, unrelated changes cause spurious version
conflicts. If `Order` contains the customer profile, shipping address,
payment details, and line items in a single aggregate, then updating the
shipping address and adding a line item will conflict even though they have
nothing to do with each other.

```python
# Anti-pattern: large aggregate creates false conflicts
@domain.aggregate
class Order(BaseAggregate):
    order_id: Auto(identifier=True)
    customer_name: String()          # Changes independently
    customer_email: String()         # Changes independently
    shipping_address: Text()         # Changes independently
    items = HasMany(OrderItem)       # Changes independently
    payment_status: String()         # Changes independently
    notes: Text()                    # Changes independently
```

Every field shares the same `_version`. Any change to any field increments
the version and conflicts with any concurrent change to any other field.
The solution is to design smaller aggregates -- see
[Design Small Aggregates](design-small-aggregates.md) -- so that each
aggregate's version protects only the data that genuinely must be consistent.

---

## Summary

| Conflict category | Business meaning | Response | Example |
|-------------------|-----------------|----------|---------|
| **Last writer wins** | Either value is fine | Reload, reapply, commit | User preferences, display settings |
| **Real problem** | Operation is no longer valid | Raise a domain-specific exception | Seat reservation, inventory allocation |
| **Merge if possible** | Operation may still be valid | Reload, re-evaluate preconditions, retry or reject | Shared cart, collaborative tagging |

| Principle | Practice |
|-----------|----------|
| Version conflicts are signals, not errors | Classify each conflict by business meaning |
| Small aggregates reduce contention | Fewer fields per aggregate means fewer false conflicts |
| One aggregate per transaction | Do not expand the conflict surface across aggregates |
| Event-sourced versions prevent contradictions | Never silently swallow `ExpectedVersionError` on event streams |
| Handlers own the conflict strategy | The handler (or application service) decides: retry, reject, or merge |

---

!!! tip "Related reading"
    **Patterns:**

    - [Design Small Aggregates](design-small-aggregates.md) -- Smaller aggregates mean fewer version conflicts.
    - [One Aggregate Per Transaction](one-aggregate-per-transaction.md) -- Single aggregate per handler reduces contention.
    - [Command Idempotency](command-idempotency.md) -- Idempotency keys prevent duplicate operations.

    **Guides:**

    - [Unit of Work](../guides/change-state/unit-of-work.md) -- Transaction management and version tracking.
    - [Persist Aggregates](../guides/change-state/persist-aggregates.md) -- Repository persistence patterns.
    - [Error Handling](../guides/server/error-handling.md#version-conflict-auto-retry) -- Framework auto-retry configuration for version conflicts.
