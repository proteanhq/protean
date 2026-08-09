# Design Small Aggregates

## The problem

The most common structural mistake in Domain-Driven Design is an aggregate that
is too big. Grouping related things feels right: a customer really does have
orders, addresses, payment methods, and loyalty points, so they all go into one
`Customer`.

That instinct gives you an aggregate that demos well and fails in production:

- **Everything contends for one lock.** Saving an aggregate writes the whole
  object graph as a unit, so changing a shipping address, adding a loyalty
  point, and placing an order all lock the same row. Two users touching
  unrelated parts of one customer queue behind each other for no reason.

- **Every read pays for the whole graph.** Changing a customer's email loads
  their orders, addresses, payment methods, and loyalty history first. What you
  transfer, deserialize, and hold in memory tracks the size of the aggregate,
  not the size of the job.

- **Transactions grow with it.** More data in a transaction means more chance
  of a conflict, a lock held longer, and more work thrown away on rollback. In
  an event-sourced system it also means a long stream that is slow to replay.

- **You end up enforcing invariants nobody asked for.** Data earns its place in
  an aggregate by having to stay consistent with the rest of it. Most
  relationships do not. Does an email change have to be atomic with the order
  history? Almost never. A big aggregate guarantees consistency the business
  never wanted.

- **It sets hard.** Once other code depends on the shape, splitting it is a
  large piece of work. The internal structure has by then leaked into commands,
  events, handlers, and projections, so moving one boundary turns into a
  migration across all of them.

All five come from one thing: the boundary was drawn around **what relates to
what**, when it should follow **what has to stay consistent**.

---

## The pattern

Design aggregates around **consistency boundaries**, not data relationships.

Keep in an aggregate only the data that has to change together, in one
transaction, to hold a business rule. Everything else gets its own aggregate and
is referenced by identity.

```
Wrong mental model:
  "These things are related, so they belong in the same aggregate."

Right mental model:
  "These things must be consistent with each other in the same transaction,
   so they belong in the same aggregate."
```

### The consistency boundary test

Before you add anything to an aggregate, ask:

> "If this data changes, must it be atomically consistent with the rest of the
> aggregate in the same transaction?"

If the answer is no, it belongs somewhere else.

Take an e-commerce system:

| Concept | Must be consistent with Order in same transaction? | Belongs in Order aggregate? |
|---------|----------------------------------------------------|-----------------------------|
| Order line items | Yes, adding an item must update the total | **Yes** |
| Order status | Yes, status transitions have invariants | **Yes** |
| Customer profile | No, customer name can change independently | **No** |
| Shipping address | Depends, immutable snapshot at order time? | Maybe (as a value object) |
| Inventory count | No, inventory is a separate concern | **No** |
| Payment record | No, payment is processed asynchronously | **No** |
| Product catalog | No, product details are reference data | **No** |

Order comes down to an ID, its line items, a status, a total, and perhaps a
snapshot of the shipping address as it was at the time. Everything else is its
own aggregate, referenced by identity.

---

## Reference by identity

When one aggregate needs to know about another, store its **identity**, never
the object. This is what lets you keep aggregates small and still model the
relationships between them.

### The anti-pattern: embedding aggregates

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

Which gives you:

- Loading an Order loads the whole Customer with it
- Changing the Customer's email means loading the Order
- Order and Customer share one transaction boundary
- You cannot scale their storage separately

### The pattern: reference by identity

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

Now the Order knows *which* customer placed it without owning or embedding
them. The `Identifier` field holds the identity, a string, integer, or UUID,
and nothing more.

### When you need data, not the aggregate

Sometimes a handler needs data from another aggregate to decide something. The
instinct is to embed it. You have three better options.

**Option 1: Include the data in the command.**

The caller already holds the data, so it goes in the command:

```python
@domain.command(part_of=Order)
class PlaceOrder(BaseCommand):
    order_id: Identifier(identifier=True)
    customer_id: Identifier(required=True)
    customer_name: String(required=True)    # Included by the caller
    customer_email: String(required=True)   # Included by the caller
    items: List(required=True)
```

The handler never loads the Customer. The command carries everything the Order
needs.

**Option 2: Store a snapshot as a value object.**

When you want another aggregate's data frozen as it was:

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

`CustomerSnapshot` is a value object: immutable, embedded, and holding the
customer's details as of the moment the order was placed. Later profile edits
do not touch it.

**Option 3: Look up in a read model.**

When the decision needs the other aggregate's *current* data, query a
projection:

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

You read what you need without tying Order to Customer.

---

## What Protean gives you

Protean gives you four pieces for this:

### The `Identifier` field

`Identifier` exists for exactly this. It holds another aggregate's identity
without embedding it:

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

Each aggregate stands alone, and the relationships between them are
identities.

### Entities for real composition

When data really does belong inside the aggregate, because it has to be
consistent in the same transaction, use entities:

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

`OrderItem` sits inside `Order` because:

- Adding or removing one has to update the order's total in the same breath
- The order has rules about its items, such as needing at least one
- An item does not exist without its order

### Value objects for embedded data

When data describes part of the aggregate but has no identity of its own:

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

`ShippingAddress` is embedded as a value object, a frozen record of where this
order goes. It does not point at an `Address` aggregate, because the order needs
the address *as it was when the order was placed*, not whatever the customer has
today.

### Domain events across aggregates

When something in one aggregate has to change another, raise a domain event:

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

`Order` knows nothing about `CustomerLoyalty`. It raises an event, and a
separate handler updates the points. You can deploy, scale, and test the two on
their own.

---

## The two-aggregate rule

A rule of thumb: **if an operation looks like it has to change two aggregates,
it probably wants an event instead**.

When you catch yourself loading and changing two aggregates in one handler:

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

Split it. The command handler changes only the Order, and an event handler
reacts to `OrderPlaced` by reserving the inventory:

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

That is the shape a well-designed DDD system settles into: small aggregates,
joined by events.

---

## A worked example

Take a project management system with these requirements:

- A **Project** has a name, description, and status
- A **Team** is assigned to a project and has members
- **Tasks** belong to a project and are assigned to team members
- **Comments** are posted on tasks
- **Time entries** are logged against tasks
- When a task is completed, the project's progress percentage updates

### The naive design

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

Logging a single time entry loads and saves the whole Project, with every task,
team member, comment, and time entry attached. On a project with 500 tasks and
2,000 time entries that is unusable.

### The refactored design

Put each relationship through the consistency boundary test:

| Concept | Must be atomically consistent with Project? | Decision |
|---------|----------------------------------------------|----------|
| Project name/status | Yes (it IS the project) | Inside Project |
| Team | No; team changes are independent | Separate aggregate |
| Task | No, tasks change independently | Separate aggregate |
| Task comments | No, comments are independent | Inside Task (entity) |
| Time entries | No, logging time is independent | Separate aggregate |
| Progress | Derived, can be eventually consistent | Updated via events |

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

Each aggregate is now small:

- **Project**: Just name, status, progress (updated eventually via events)
- **Team**: Members for a project (changes independently of project)
- **Task**: Title, status, comments (comments are entities because they belong
  to the task's consistency boundary)
- **TimeEntry**: Standalone records (no invariant ties them to the task's state)

Completing a task raises an event, and the project's progress follows:

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

## When to do something else

### Data that really must be consistent

Sometimes data does have to share an aggregate. An invoice and its line items
always have to agree, because the total has to match the sum of the lines. The
debit and credit of a transfer within one account have to be atomic. Leave those
alone.

The test does not change: must these move together, in one transaction? If yes,
they stay together.

### Small domains

In a small application with a handful of entities and almost no concurrency,
splitting into many aggregates may cost more than it returns. With one user at a
time and a few hundred records, a larger aggregate that keeps the code short is
a fair trade.

Start there, and split when contention, performance, or complexity starts to
hurt.

### Event-sourced aggregates

Event-sourced aggregates carry one more concern: stream length. A long-lived
aggregate with thousands of events takes longer to replay, which argues for
keeping them small. Where an aggregate genuinely needs to be one consistency
boundary, reach for snapshots (Protean tracks `_version`) before you split it.

---

## Common mistakes

### Mistake 1: splitting on UI screens

"The order page shows orders and the customer page shows customer info, so
they should be separate aggregates." That lands on the right answer for the
wrong reason. Boundaries come from **business rules**, not screen layout. Put
orders and customers on one page tomorrow and the boundaries should not move.

### Mistake 2: using HasOne/HasMany across aggregates

```python
# Mistake: using association fields for separate aggregates
@domain.aggregate
class Order:
    customer = HasOne(Customer)  # This embeds Customer inside Order
```

`HasOne` and `HasMany` are for entities **inside** the aggregate. To point at
another aggregate, use `Identifier`:

```python
# Correct: identity reference to another aggregate
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)  # References Customer
```

### Mistake 3: splitting too early

A long field list is not a reason to split. A `User` with 15 fields covering
name, email, phone, preferences, and settings is fine when those fields have to
agree with each other. Count of fields is not the test. Consistency is.

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

Draw the boundary around what has to stay consistent. Point at other aggregates
by identity, and let domain events carry the work between them.

---

!!! tip "Related reading"
    **Concepts:**

    - [Aggregates](../concepts/building-blocks/aggregates.md): What aggregates are and their core properties.
    - [Entities](../concepts/building-blocks/entities.md): Objects with identity within aggregates.

    **Guides:**

    - [Aggregates](../guides/domain-definition/aggregates.md): Defining aggregates, fields, and configuration.
    - [Relationships](../guides/domain-definition/relationships.md): Connecting entities within aggregate boundaries.
    - [Choosing Element Types](../concepts/building-blocks/choosing-element-types.md): Choosing between aggregates, entities, and value objects.
