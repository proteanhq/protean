# Invariants

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Invariants are business rules or constraints that always need to be true within
a specific domain concept. They define the fundamental and consistent state of
the concept, ensuring it remains unchanged even as other aspects evolve play a
crucial role in ensuring business validations within a domain.

Protean treats invariants as first-class citizens, to make them explicit and
visible, making it easier to maintain the integrity of the domain model. You
can define invariants on Aggregates, Entities, and Value Objects.

For background on why invariants are fundamental to DDD and how they keep
your domain always valid, see
[Invariants concept](../../concepts/foundations/invariants.md).

## `@invariant` decorator

Invariants are defined using the `@invariant` decorator in Aggregates,
Entities, and Value Objects (plus in Domain Services, as we will soon see):

```python hl_lines="9-10 14-15"
--8<-- "guides/domain-behavior/001.py:17:41"
```

In the above example, `Order` aggregate has two invariants (business
conditions), one that the total amount of the order must always equal the sum
of individual item subtotals, and the other that the order date must be within
30 days if status is `PENDING`.

All methods marked `@invariant` are associated with the domain element when
the element is registered with the domain.

## `pre` and `post` Invariants

The `@invariant` decorator has two flavors - **`pre`** and **`post`**.

`pre` invariants are triggered before elements are updated, while `post`
invariants are triggered after the update. `pre` invariants are used to prevent
invalid state from being introduced, while `post` invariants ensure that the
aggregate remains in a valid state after the update.

`pre` invariants are useful in certain situations where you want to check state
before the elements are mutated. For instance, you might want to check if a
user has enough balance before deducting it. Also, some invariant checks may
be easier to add *before* changing an element.

!!!note
    `pre` invariants are not applicable when aggregates and entities are being
    initialized. Their validations only kick in when an element is being
    changed or updated from an existing state.

!!!note
    `pre` invariant checks are not applicable to `ValueObject` elements because
    they are immutable - they cannot be changed once initialized.

## Validation

Invariant validations are triggered throughout the lifecycle of domain objects,
to ensure all invariants remain satisfied. Aggregates are the root of the
triggering mechanism, though. The validations are conducted recursively,
starting with the aggregate and trickling down into entities.

### Post-Initialization

Immediately after an object (aggregate or entity) is initialized, all
invariant checks are triggered to ensure the aggregate remains in a valid state.

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

Every attribute change in an aggregate or its enclosing entities triggers
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

### Adding and Removing Entities

`add_*` and `remove_*` methods on `HasMany` associations also trigger
invariants. Both pre-invariants and post-invariants fire, just as they do
for direct attribute assignments.

```shell hl_lines="3 5"
In [3]: order.mark_shipped()

In [4]: order.add_items(OrderItem(product_id="3", quantity=2, price=10.0, subtotal=20.0))
...
ValidationError: {'_entity': ['Order date must be in the past and status PENDING to update order']}
```

When adding or removing entities requires coordinated changes (like updating
a total), use `atomic_change` to batch the mutations.


## Atomic Changes

There may be times when multiple attributes need to be changed together, and
validations should not trigger until the entire operation is complete.
The `atomic_change` context manager can be used to achieve this.

Within the `atomic_change` context manager, validations are temporarily
disabled. Invariant validations are triggered upon exiting the context manager.

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

!!!note
    Atomic Changes context manager can only be applied when updating or
    changing an already initialized element.

---

!!! tip "See also"
    **Concept overview:** [Invariants](../../concepts/foundations/invariants.md) — Why invariants are fundamental to DDD and how they keep your domain always valid.

    **Patterns:** [Validation Layering](../../patterns/validation-layering.md) — Choosing the right layer for each kind of validation rule.