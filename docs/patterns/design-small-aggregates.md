# Design Small Aggregates

## The Problem

The most common structural mistake in Domain-Driven Design is making aggregates
too large. Developers naturally want to group related concepts together --
placing `Customer`, `Order`, `OrderItem`, `ShippingAddress`, `PaymentMethod`,
and `LoyaltyPoints` into a single massive `Customer` aggregate feels intuitive
because these concepts are related in the real world.

This instinct produces aggregates that work in demos but fail in production:

- **Contention and locking.** When an aggregate is persisted, the entire object
  graph is written as a unit. A large aggregate means that any change -- updating
  a shipping address, adding a loyalty point, placing an order -- locks the same
  row or document. Two users acting on unrelated aspects of the same customer
  will contend for the same lock, serializing operations that should be
  independent.

- **Performance degradation.** Loading a large aggregate means hydrating its
  entire object graph. To update a customer's email, the system loads all of
  their orders, addresses, payment methods, and loyalty history. The data
  transfer, deserialization, and memory overhead scale with the aggregate's
  total size, not with the operation being performed.

- **Transaction scope creep.** A large aggregate implies a large transaction.
  The more data in a transaction, the higher the chance of conflict, the longer
  the lock is held, and the more work is lost on rollback. In event-sourced
  systems, large aggregates produce long event streams that are slow to replay.

- **False invariants.** The justification for including data in an aggregate is
  that it must be consistent with other data in the same aggregate. But many
  relationships don't require transactional consistency. Does changing a
  customer's email need to be atomically consistent with their order history?
  Almost never. Large aggregates enforce consistency guarantees that the business
  doesn't actually need.

- **Rigid boundaries.** Once an aggregate grows large and other code depends on
  its structure, splitting it becomes a significant refactoring effort. The
  aggregate's internal structure leaks into commands, events, handlers, and
  projections. What should have been a simple boundary adjustment becomes a
  cross-cutting migration.

These problems share a root cause: **the aggregate boundary was drawn around
data relationships rather than consistency requirements**.

---

## The Pattern

Design aggregates around **consistency boundaries**, not data relationships.

An aggregate should contain only the data that must change together atomically
to enforce a business invariant. Everything else should live in its own
aggregate, referenced by identity.

```
Wrong mental model:
  "These things are related, so they belong in the same aggregate."

Right mental model:
  "These things must be consistent with each other in the same transaction,
   so they belong in the same aggregate."
```

### The Consistency Boundary Test

For every piece of data you're considering adding to an aggregate, ask:

> "If this data changes, must it be atomically consistent with the rest of the
> aggregate in the same transaction?"

If the answer is no, it belongs in a separate aggregate.

Consider an e-commerce system:

| Concept | Must be consistent with Order in same transaction? | Belongs in Order aggregate? |
|---------|----------------------------------------------------|-----------------------------|
| Order line items | Yes -- adding an item must update the total | **Yes** |
| Order status | Yes -- status transitions have invariants | **Yes** |
| Customer profile | No -- customer name can change independently | **No** |
| Shipping address | Depends -- immutable snapshot at order time? | Maybe (as a value object) |
| Inventory count | No -- inventory is a separate concern | **No** |
| Payment record | No -- payment is processed asynchronously | **No** |
| Product catalog | No -- product details are reference data | **No** |

The Order aggregate shrinks to: order ID, line items, status, total, and perhaps
a snapshot of the shipping address at order time. Everything else is a separate
aggregate, referenced by identity.

---

## Reference by Identity

When one aggregate needs to know about another, store the **identity** of the
referenced aggregate -- not the aggregate itself. This is the fundamental
mechanism for keeping aggregates small while maintaining relationships.

### The Anti-Pattern: Embedding Aggregates

```python
# Anti-pattern: Customer embedded inside Order
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer = HasOne(Customer)        # Embeds the entire Customer aggregate
    items = HasMany(OrderItem)
    status: String(default="pending")
    total: Float(default=0.0)
```

This design means:
- Loading an Order loads the entire Customer (and all of the Customer's data)
- Changing the Customer's email requires loading the Order
- The Order and Customer are in the same transaction boundary
- You cannot scale Order and Customer persistence independently

### The Pattern: Reference by Identity

```python
# Pattern: Order references Customer by identity
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)  # Just the identity
    items = HasMany(OrderItem)
    status: String(default="pending")
    total: Float(default=0.0)
```

Now the Order knows *which* customer placed it, but doesn't own or embed the
Customer. The `Identifier` field stores the customer's identity -- a lightweight
string, integer, or UUID -- not the customer object.

### When You Need Data, Not the Aggregate

Sometimes a command handler needs data from another aggregate to make a decision.
The instinct is to embed that aggregate, but there are better options:

**Option 1: Include the data in the command.**

The caller already has the data and passes it to the command:

```python
@domain.command(part_of=Order)
class PlaceOrder(BaseCommand):
    order_id: Identifier(identifier=True)
    customer_id: Identifier(required=True)
    customer_name: String(required=True)    # Included by the caller
    customer_email: String(required=True)   # Included by the caller
    items: List(required=True)
```

The command handler doesn't need to load the Customer aggregate. The command
carries everything needed to create the Order.

**Option 2: Store a snapshot as a value object.**

When you need a frozen-in-time copy of another aggregate's data:

```python
@domain.value_object
class CustomerSnapshot:
    customer_id: String(required=True)
    name: String(required=True)
    email: String(required=True)


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer = ValueObject(CustomerSnapshot)  # Snapshot, not the live aggregate
    items = HasMany(OrderItem)
    status: String(default="pending")
    total: Float(default=0.0)
```

The `CustomerSnapshot` is a value object -- immutable, embedded, and
representing the customer's details at the time the order was placed. It doesn't
change when the customer updates their profile later.

**Option 3: Look up in a read model.**

For decisions that need current data from another aggregate, query a projection:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        # Check customer's credit status via a read model
        customer_view = current_domain.repository_for(CustomerCreditView).get(
            command.customer_id
        )

        if customer_view.credit_status == "suspended":
            raise BusinessRuleViolation("Customer credit is suspended")

        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
            items=command.items,
        )
        current_domain.repository_for(Order).add(order)
```

This approach reads from a projection without creating a dependency between the
Order and Customer aggregates.

---

## How Protean Supports This

Protean provides the building blocks for small, well-bounded aggregates:

### The `Identifier` Field

The `Identifier` field is purpose-built for cross-aggregate references. It
stores the identity of another aggregate without embedding it:

```python
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)  # References Customer aggregate
    product_id: Identifier(required=True)   # References Product aggregate

@domain.aggregate
class Shipment:
    shipment_id: Auto(identifier=True)
    order_id: Identifier(required=True)     # References Order aggregate
    carrier_id: Identifier(required=True)   # References Carrier aggregate
```

Each aggregate stands alone. Relationships are expressed as identities, not
object references.

### Entities for True Composition

When data genuinely belongs inside an aggregate -- because it must be consistent
in the same transaction -- use entities:

```python
@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    product_name: String(required=True)
    quantity: Integer(min_value=1, required=True)
    unit_price: Float(required=True)


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    status: String(default="pending")

    def add_item(self, product_id, product_name, quantity, unit_price):
        item = OrderItem(
            product_id=product_id,
            product_name=product_name,
            quantity=quantity,
            unit_price=unit_price,
        )
        self.items.add(item)

    @invariant.post
    def order_must_have_items(self):
        if self.status != "draft" and not self.items:
            raise ValidationError({"items": ["Order must have at least one item"]})
```

`OrderItem` is an entity inside the `Order` aggregate because:
- Adding or removing items must atomically update the order's total
- The order has invariants about its items (must have at least one)
- Items don't exist independently of the order

### Value Objects for Embedded Data

When data describes an aspect of the aggregate but doesn't have identity:

```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, required=True)


@domain.value_object
class ShippingAddress:
    street: String(required=True)
    city: String(required=True)
    state: String(required=True)
    postal_code: String(required=True)
    country: String(required=True)


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    total = ValueObject(Money)
    shipping_address = ValueObject(ShippingAddress)  # Snapshot at order time
```

The `ShippingAddress` is embedded as a value object -- a frozen snapshot of
where to ship. It doesn't reference an `Address` aggregate because the order
needs the address *at the time of order*, not the customer's current address.

### Domain Events for Cross-Aggregate Communication

When an operation on one aggregate needs to trigger a change in another, use
domain events:

```python
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total_amount: Float(required=True)


@domain.aggregate
class Order:
    # ... fields ...

    def place(self):
        if self.status != "draft":
            raise ValidationError({"status": ["Only draft orders can be placed"]})

        self.status = "placed"
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            total_amount=self.total.amount,
        ))


# In a separate aggregate's event handler
@domain.event_handler(part_of=CustomerLoyalty)
class CustomerLoyaltyEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(CustomerLoyalty)
        loyalty = repo.get(event.customer_id)
        loyalty.add_points(int(event.total_amount))
        repo.add(loyalty)
```

The `Order` aggregate doesn't know about `CustomerLoyalty`. It raises an event.
A separate event handler reacts to update the loyalty points. The two aggregates
are independently deployable, independently scalable, and independently
testable.

---

## The "Two Aggregate Rule"

A useful heuristic: **if a business operation seems to require modifying two
aggregates, it probably needs an event**.

When you find yourself writing a command handler that loads and modifies two
aggregates:

```python
# Anti-pattern: modifying two aggregates in one handler
@handle(PlaceOrder)
def place_order(self, command: PlaceOrder):
    order_repo = current_domain.repository_for(Order)
    order = Order(order_id=command.order_id, items=command.items)
    order.place()
    order_repo.add(order)

    # This should NOT be here
    inventory_repo = current_domain.repository_for(Inventory)
    for item in command.items:
        inventory = inventory_repo.get(item.product_id)
        inventory.reserve(item.quantity)
        inventory_repo.add(inventory)
```

Split it: the command handler modifies only the Order. An event handler reacts
to `OrderPlaced` and reserves inventory:

```python
# Pattern: one aggregate per handler, events for the rest
@handle(PlaceOrder)
def place_order(self, command: PlaceOrder):
    order_repo = current_domain.repository_for(Order)
    order = Order(
        order_id=command.order_id,
        items=command.items,
    )
    order.place()  # Raises OrderPlaced event
    order_repo.add(order)


@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        inventory_repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = inventory_repo.get(item["product_id"])
            inventory.reserve(item["quantity"])
            inventory_repo.add(inventory)
```

This is the natural architecture of a well-designed DDD system: small aggregates
connected by events.

---

## Applying the Pattern: A Worked Example

Consider a project management system with these requirements:

- A **Project** has a name, description, and status
- A **Team** is assigned to a project and has members
- **Tasks** belong to a project and are assigned to team members
- **Comments** are posted on tasks
- **Time entries** are logged against tasks
- When a task is completed, the project's progress percentage updates

### The Naive Design (Too Large)

```python
# Anti-pattern: everything in one aggregate
@domain.aggregate
class Project:
    name: String(required=True)
    description: Text()
    status: String(default="active")
    team = HasOne(Team)
    tasks = HasMany(Task)              # Could be hundreds
    time_entries = HasMany(TimeEntry)   # Could be thousands
    progress: Float(default=0.0)
```

Every time someone logs a time entry, the entire Project -- with all its tasks,
team members, comments, and time entries -- is loaded and saved. For a project
with 500 tasks and 2000 time entries, this is catastrophic for performance.

### The Refactored Design (Small Aggregates)

Apply the consistency boundary test to each relationship:

| Concept | Must be atomically consistent with Project? | Decision |
|---------|----------------------------------------------|----------|
| Project name/status | Yes (it IS the project) | Inside Project |
| Team | No -- team changes are independent | Separate aggregate |
| Task | No -- tasks change independently | Separate aggregate |
| Task comments | No -- comments are independent | Inside Task (entity) |
| Time entries | No -- logging time is independent | Separate aggregate |
| Progress | Derived -- can be eventually consistent | Updated via events |

```python
@domain.aggregate
class Project:
    project_id: Auto(identifier=True)
    name: String(required=True)
    description: Text()
    status: String(default="active")
    progress: Float(default=0.0)

    def update_progress(self, completed_count, total_count):
        if total_count > 0:
            self.progress = (completed_count / total_count) * 100


@domain.aggregate
class Team:
    team_id: Auto(identifier=True)
    project_id: Identifier(required=True)  # References Project
    members = HasMany(TeamMember)


@domain.entity(part_of=Team)
class TeamMember:
    user_id: Identifier(required=True)
    role: String(default="member")


@domain.aggregate
class Task:
    task_id: Auto(identifier=True)
    project_id: Identifier(required=True)  # References Project
    assignee_id: Identifier()               # References a User
    title: String(required=True)
    status: String(default="open")
    comments = HasMany(Comment)

    def complete(self):
        if self.status == "completed":
            return
        self.status = "completed"
        self.raise_(TaskCompleted(
            task_id=self.task_id,
            project_id=self.project_id,
        ))


@domain.entity(part_of=Task)
class Comment:
    author_id: Identifier(required=True)
    content: Text(required=True)
    posted_at: DateTime()


@domain.aggregate
class TimeEntry:
    entry_id: Auto(identifier=True)
    task_id: Identifier(required=True)    # References Task
    user_id: Identifier(required=True)    # References User
    hours: Float(required=True)
    description: Text()
```

Now each aggregate is small and focused:

- **Project**: just name, status, progress (updated eventually via events)
- **Team**: members for a project (changes independently of project)
- **Task**: title, status, comments (comments are entities because they belong
  to the task's consistency boundary)
- **TimeEntry**: standalone records (no invariant ties them to the task's state)

When a task is completed, an event updates the project's progress:

```python
@domain.event_handler(part_of=Project)
class ProjectEventHandler(BaseEventHandler):

    @handle(TaskCompleted)
    def on_task_completed(self, event: TaskCompleted):
        # Query a read model for task counts rather than loading all tasks
        task_stats = current_domain.repository_for(ProjectTaskStats).get(
            event.project_id
        )
        repo = current_domain.repository_for(Project)
        project = repo.get(event.project_id)
        project.update_progress(
            task_stats.completed_count + 1,
            task_stats.total_count,
        )
        repo.add(project)
```

---

## When Not to Use This Pattern

### Data That Genuinely Must Be Consistent

Sometimes data really does need to be in the same aggregate. An invoice and its
line items must always be consistent -- the total must match the sum of the
lines. A bank transfer's debit and credit within the same account must be
atomic. Don't split these apart.

The test remains: "must these change together in the same transaction?" If yes,
they belong together.

### Very Small Domains

In a small application with a handful of entities and low concurrency, the
overhead of splitting into many small aggregates may not be worth it. If you
have one user at a time and a few hundred records total, a larger aggregate
that simplifies the code is a reasonable trade-off.

Start simple. Split when you feel the pain of contention, performance, or
complexity.

### Event Sourced Aggregates

Event-sourced aggregates have an additional consideration: the event stream
length. A long-lived aggregate with many events takes longer to replay. This
is another argument for small aggregates -- but also consider using snapshots
(Protean supports `_version` tracking) to mitigate replay cost rather than
splitting an aggregate that genuinely needs to be a single consistency boundary.

---

## Common Mistakes

### Mistake 1: Splitting Based on UI Screens

"The order details page shows orders, and the customer page shows customer
info, so they should be separate aggregates." This reasoning happens to produce
the right result for the wrong reason. Aggregate boundaries come from
**business invariants**, not UI layout. If tomorrow the UI changes to show
orders and customers on the same page, the aggregate boundaries shouldn't
change.

### Mistake 2: Using HasOne/HasMany for Cross-Aggregate References

```python
# Mistake: using association fields for separate aggregates
@domain.aggregate
class Order:
    customer = HasOne(Customer)  # This embeds Customer inside Order
```

`HasOne` and `HasMany` are for entities **within** the aggregate. For references
to other aggregates, use `Identifier`:

```python
# Correct: identity reference to another aggregate
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)  # References Customer
```

### Mistake 3: Premature Splitting

Don't split an aggregate just because it has many fields. A `User` aggregate
with 15 fields (name, email, phone, preferences, settings) is fine if those
fields must be consistent with each other. The number of fields is not the
criterion -- the consistency requirement is.

---

## Summary

| Aspect | Large Aggregates | Small Aggregates |
|--------|-----------------|-----------------|
| Boundary criterion | Data relationships | Consistency requirements |
| Cross-aggregate reference | Embed (HasOne/HasMany) | Identity (Identifier) |
| Cross-aggregate changes | Same transaction | Domain events |
| Loading cost | Entire object graph | Only what's needed |
| Concurrency | High contention | Low contention |
| Transaction scope | Large (risky) | Small (safe) |
| Scalability | Limited | Independent per aggregate |
| Testability | Requires full graph | Isolated units |

The principle: **draw aggregate boundaries around consistency requirements, not
data relationships. Reference other aggregates by identity. Use domain events
for cross-aggregate communication.**
