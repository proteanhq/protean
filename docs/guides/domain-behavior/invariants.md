# Invariants

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

[Field-level validations](validations.md) catch type errors, missing values,
and range violations — but they cannot express rules that span multiple fields
or depend on the aggregate's overall state. For example, "an order's total must
equal the sum of its items" or "a shipment can only be dispatched if the order
is confirmed" are business rules that no single field constraint can enforce.

Invariants fill this gap. They are business rules or constraints that must
**always** be true within a domain concept. Protean treats invariants as
first-class citizens, making them explicit and visible with the `@invariant`
decorator. You can define invariants on Aggregates, Entities, Value Objects,
and [Domain Services](domain-services.md).

For background on why invariants are fundamental to DDD and how they keep
your domain always valid, see
[Invariants concept](../../concepts/foundations/invariants.md).

## `@invariant` decorator

Invariants are defined using the `@invariant` decorator with either a `.pre`
or `.post` qualifier. You must always use `@invariant.pre` or
`@invariant.post` — plain `@invariant` without a qualifier is not valid.

```python hl_lines="9-10 14-15"
--8<-- "guides/domain-behavior/001.py:17:41"
```

In the above example, `Order` aggregate has two invariants (business
conditions), one that the total amount of the order must always equal the sum
of individual item subtotals, and the other that the order date must be within
30 days if status is `PENDING`.

All methods marked `@invariant` are associated with the domain element when
the element is registered with the domain.

Invariant methods **must** raise `ValidationError` (from
`protean.exceptions`) when the rule is violated. This is the exception type
the framework catches and aggregates. If an invariant raises a different
exception type, it will propagate directly to the caller instead of being
collected with other invariant violations.

## `pre` and `post` Invariants

The `@invariant` decorator has two flavors — **`pre`** and **`post`**.

**`post` invariants** are triggered after elements are constructed or updated.
They ensure that the aggregate is in a valid state after the change.

**`pre` invariants** are triggered before elements are updated. They are used
to check whether a proposed change is allowed given the current state.

### Pre-invariant example

Pre-invariants are useful when you want to guard against invalid transitions.
For example, checking that an account has sufficient balance before a
withdrawal:

```python
from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String

domain = Domain()

@domain.aggregate
class Account:
    account_number: Identifier(required=True, unique=True)
    balance: Float(default=0.0)
    status: String(choices=["ACTIVE", "FROZEN"], default="ACTIVE")

    @invariant.pre
    def account_must_be_active_to_transact(self):
        if self.status == "FROZEN":
            raise ValidationError(
                {"_entity": ["Cannot modify a frozen account"]}
            )

    @invariant.post
    def balance_must_not_be_negative(self):
        if self.balance < 0:
            raise ValidationError(
                {"_entity": ["Insufficient funds"]}
            )

    def withdraw(self, amount: float):
        self.balance -= amount
```

When `withdraw()` is called, the flow is:

1. **Pre-invariants** fire — `account_must_be_active_to_transact` checks
   the current state. If the account is frozen, `ValidationError` is raised
   and the assignment `self.balance -= amount` never happens.
2. The attribute assignment `self.balance -= amount` executes.
3. **Post-invariants** fire — `balance_must_not_be_negative` checks the
   resulting state. If the balance went negative, `ValidationError` is raised
   and the assignment is rolled back.

!!!note
    `pre` invariants are not applicable when aggregates and entities are being
    initialized. Their validations only kick in when an element is being
    changed or updated from an existing state.

!!!note
    `pre` invariant checks are not applicable to `ValueObject` elements because
    they are immutable — they cannot be changed once initialized.

## When Invariants Run

Invariant validations are triggered throughout the lifecycle of domain objects.
The aggregate is the root of the triggering mechanism — validations are
conducted recursively, starting with the aggregate and trickling down into
enclosed entities.

### Post-Initialization

Immediately after an object (aggregate or entity) is initialized, all
**post-invariant** checks are triggered to ensure the aggregate starts in a
valid state.

```shell hl_lines="11 13"
In [1]: Order(
   ...:    customer_id="1",
   ...:    order_date="2020-01-01",
   ...:    total_amount=100.0,
   ...:    status="PENDING",
   ...:    items=[
   ...:        OrderItem(product_id="1", quantity=2, price=10.0, subtotal=20.0),
   ...:        OrderItem(product_id="2", quantity=3, price=20.0, subtotal=60.0),
   ...:    ],
   ...:)
ERROR: Error during initialization: {'_entity': ['Total should be sum of item prices']}
...
ValidationError: {'_entity': ['Total should be sum of item prices']}
```

### Attribute Changes

Every attribute change in an aggregate or its enclosed entities triggers
invariant validation throughout the aggregate cluster. This ensures that any
modification maintains the consistency of the domain model.

```shell hl_lines="13 15"
In [1]: order = Order(
   ...:     customer_id="1",
   ...:     order_date="2020-01-01",
   ...:     total_amount=100.0,
   ...:     status="PENDING",
   ...:     items=[
   ...:         OrderItem(product_id="1", quantity=4, price=10.0, subtotal=40.0),
   ...:         OrderItem(product_id="2", quantity=3, price=20.0, subtotal=60.0),
   ...:     ],
   ...: )
   ...:

In [2]: order.total_amount = 140.0
...
ValidationError: {'_entity': ['Total should be sum of item prices']}
```

This happens because `__setattr__` intercepts every field assignment and runs
the full pre-check → validate → post-check cycle. See
[Aggregate Mutation](aggregate-mutation.md#how-it-works) for the complete
mechanism.

### Entity-to-Root Delegation

When a child entity's attribute is changed, invariants fire on the **root
aggregate**, not just the entity itself. This ensures that cross-entity
business rules (defined on the aggregate) are always enforced, even when the
mutation happens deep in the aggregate cluster.

### Adding and Removing Entities

`add_*` and `remove_*` methods on `HasMany` associations also trigger
invariants. Both pre-invariants and post-invariants fire, just as they do
for direct attribute assignments.

```shell hl_lines="1 3"
In [3]: order.add_items(OrderItem(product_id="3", quantity=2, price=10.0, subtotal=20.0))
...
ValidationError: {'_entity': ['Total should be sum of item prices']}
```

Adding an item changes the sum of item subtotals, which no longer matches
`total_amount`, so the post-invariant fires immediately.

When adding or removing entities requires coordinated changes (like updating
a total), use `atomic_change` to batch the mutations.


## Atomic Changes

There may be times when multiple attributes need to be changed together, and
validations should not trigger until the entire operation is complete.
The `atomic_change` context manager can be used to achieve this.

```python
from protean import atomic_change
```

Within the `atomic_change` context manager, the cycle works as follows:

1. **Pre-invariants fire on entry** — the current state is validated.
2. **Invariant checks are suspended** during the block — individual
   assignments do not trigger pre/post checks.
3. **Post-invariants fire on exit** — the final state is validated.

```shell hl_lines="14"
In [1]: from protean import atomic_change

In [2]: order = Order(
   ...:     customer_id="1",
   ...:     order_date="2020-01-01",
   ...:     total_amount=100.0,
   ...:     status="PENDING",
   ...:     items=[
   ...:         OrderItem(product_id="1", quantity=4, price=10.0, subtotal=40.0),
   ...:         OrderItem(product_id="2", quantity=3, price=20.0, subtotal=60.0),
   ...:     ],
   ...: )

In [3]: with atomic_change(order):
   ...:     order.total_amount = 120.0
   ...:     order.add_items(
   ...:         OrderItem(product_id="3", quantity=2, price=10.0, subtotal=20.0)
   ...:     )
   ...:
```

Trying to perform the attribute updates one after another would have resulted
in a `ValidationError` exception:

```shell hl_lines="3"
In [4]: order.total_amount = 120.0
...
ValidationError: {'_entity': ['Total should be sum of item prices']}
```

`atomic_change` is also used internally by `raise_()` in event-sourced
aggregates to wrap `@apply` handlers — see
[Raising Events](raising-events.md#es-raise-apply) for details.

!!!note
    `atomic_change` can only be applied when updating or changing an already
    initialized element.

## Invariant Inheritance

Invariants defined on a parent class are inherited by subclasses through
standard Python MRO resolution. A subclass inherits all `@invariant.pre` and
`@invariant.post` methods from its parents, and can add its own.

## Error Structure

When invariants raise `ValidationError`, the framework aggregates all
violations into a single `ValidationError` with a dictionary structure:

```python
ValidationError({
    '_entity': ['Total should be sum of item prices'],
    'balance': ['Insufficient funds'],
})
```

The `_entity` key is a convention for errors that apply to the entity as a
whole rather than a specific field. Multiple invariant violations are collected
and reported together.

---

!!! tip "See also"
    **Deep dive:** [The Always-Valid Domain](../../concepts/philosophy/always-valid.md) — The complete story of how Protean's four validation layers work together to guarantee your domain objects are never invalid.

    **Concept overview:** [Invariants](../../concepts/foundations/invariants.md) — Why invariants are fundamental to DDD and how they keep your domain always valid.

    **Related guides:**

    - [Validations](validations.md) — Field-level constraints (Layer 1).
    - [Status Transitions](status-transitions.md) — Enforcing state machine rules with the `Status` field.
    - [Aggregate Mutation](aggregate-mutation.md) — The `__setattr__` mechanism that triggers invariants.
    - [Domain Services](domain-services.md) — Cross-aggregate invariants in domain services.

    **Patterns:** [Validation Layering](../../patterns/validation-layering.md) — Choosing the right layer for each kind of validation rule.
