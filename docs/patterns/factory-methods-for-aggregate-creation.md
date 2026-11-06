# Create aggregates through factory methods

## The problem

You write a command handler to place an order from a shopping cart:

```python
# fragment
@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        repo = current_domain.repository_for(Order)

        order = Order(
            customer_id=command.customer_id,
            shipping_address=command.shipping_address,
        )

        for item in command.items:
            order.add_item(
                product_id=item["product_id"],
                name=item["name"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
            )

        order.place()
        repo.add(order)
```

Nothing is wrong with it. The handler creates an Order, adds the items the
command carried, calls a domain method, and saves. Then the system grows and
you need four more ways to create an order:

- **Subscription renewal** creates an Order by copying line items from the
  previous cycle's order and applying the current pricing.
- **Admin override** creates an Order with a manually specified discount and a
  different validation path (no credit check).
- **Bulk import** creates Orders from CSV rows with a completely different data
  shape.
- **Return replacement** creates a new Order pre-populated from the original
  order, with only the returned items, flagged as a replacement.

Each one gets its own handler, and each handler assembles the Order itself.
Which items to include, how to total them, which rules to apply, which events
to raise: all of it now exists five times, once per handler. Each copy differs
slightly from the others. Over time, the copies differ more.

That costs you in four ways:

- **Five handlers know how to build an Order.** Add a required field to the
  aggregate and you update all five. Change a rule, say every order now needs a
  tax calculation, and you have to find and edit each one.

- **Every copy is a fresh chance to get it wrong.** The renewal handler forgets
  to raise `OrderPlaced`. The bulk import skips the minimum-order-value check.
  The return replacement sets the wrong status.

- **You cannot test the creation on its own.** To check that a renewal copies
  line items and prices them correctly, you have to build a command, set up a
  repository, and run the handler inside a unit of work.

- **Handlers grow long.** A handler should take three lines: load, call, save.
  It grows to 20 or 40 lines because it also assembles the Order, and assembly
  is not the handler's job.

All four costs have one cause: the handlers contain the code that builds a
valid Order. The domain model should contain that code.

---

## The pattern

Put creation in **factory classmethods** on the aggregate. Each one is a named
way to bring the aggregate into existence, with its own inputs, its own rules,
and its own events.

```
Scattered construction (in handlers):
  Handler A:  order = Order(...)  + 15 lines of assembly
  Handler B:  order = Order(...)  + 20 lines of different assembly
  Handler C:  order = Order(...)  + 12 lines of yet another assembly

Factory classmethods (on the aggregate):
  Handler A:  order = Order.from_cart(command.cart_items, command.customer_id)
  Handler B:  order = Order.from_subscription_renewal(command.subscription_id, ...)
  Handler C:  order = Order.from_return(command.original_order_id, ...)
```

Each classmethod contains all the code that builds a valid aggregate from one
set of inputs. You can test each classmethod on its own. The handler calls the
classmethod and saves the aggregate it returns.

This is the Factory Method pattern from Eric Evans' book *Domain-Driven
Design*, known as the Blue Book. Evans described two forms:

| Form | What it is | When to use |
|------|-----------|-------------|
| **Factory Method** | A classmethod on the aggregate | Construction belongs conceptually to the aggregate |
| **Standalone Factory** | A separate class dedicated to creation | Construction needs external data or doesn't belong to the aggregate |

**Start with classmethods on the aggregate.** They are simpler and easier to
find, and they keep the creation code in the aggregate class it builds. When a
classmethod stops being enough, move to a standalone factory class. A later
section on this page says when that happens.

---

## Applying the pattern

### Before: each handler constructs the Order

```python
# fragment
@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        repo = current_domain.repository_for(Order)

        order = Order(
            customer_id=command.customer_id,
            shipping_address=command.shipping_address,
        )

        for item in command.items:
            order.add_item(
                product_id=item["product_id"],
                name=item["name"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
            )

        order.place()
        repo.add(order)

    @handle(RenewSubscriptionOrder)
    def renew_subscription(self, command: RenewSubscriptionOrder):
        repo = current_domain.repository_for(Order)
        prev_order_repo = current_domain.repository_for(Order)
        previous = prev_order_repo.get(command.previous_order_id)

        # Duplicate construction logic with subtle differences
        order = Order(
            customer_id=previous.customer_id,
            shipping_address=previous.shipping_address,
            is_renewal=True,
        )

        for item in previous.items:
            order.add_item(
                product_id=item.product_id,
                name=item.name,
                quantity=item.quantity,
                unit_price=item.unit_price,  # Bug: should use current pricing
            )

        order.place()
        repo.add(order)
```

The renewal handler copies the placement handler and gets pricing wrong: it
reuses the previous order's prices when it should look up current ones. When
each handler does its own assembly, you have to read every handler to find a
bug like this.

### After: factory classmethods on the aggregate build the Order

```python
--8<-- "patterns/factory-methods-for-aggregate-creation/001.py:elements"
--8<-- "patterns/factory-methods-for-aggregate-creation/001.py:aggregate"
```

Each handler is now 4-5 lines: load inputs, call a factory classmethod,
persist. The aggregate class now contains the construction code, so you can
test it directly, reuse it across handlers, and maintain it in one place.

---

## What a factory classmethod does

A factory classmethod does three things:

### 1. Assemble the aggregate

Build the aggregate and its children from the inputs:

```python
# fragment
@classmethod
def from_cart(cls, customer_id, cart_items, shipping_address):
    order = cls(
        customer_id=customer_id,
        shipping_address=shipping_address,
    )
    for item in cart_items:
        order.add_item(**item)
    return order
```

### 2. Check the preconditions

Check what this particular creation path requires. These are not the
aggregate's post-invariants. Post-invariants run after any change and check the
state the aggregate ends up in. With a precondition, you check whether you
should create the thing *at all*:

```python
# fragment
@classmethod
def from_subscription_renewal(cls, previous_order, current_prices):
    if previous_order.status != "delivered":
        raise ValidationError(
            {"previous_order": ["Can only renew from a delivered order"]}
        )

    # Proceed with construction...
```

### 3. Raise the creation events

When the creation is itself a domain event, raise it inside the factory:

```python
# fragment
@classmethod
def from_cart(cls, customer_id, cart_items, shipping_address):
    order = cls(...)
    for item in cart_items:
        order.add_item(**item)

    order.place()  # This raises OrderPlaced internally
    return order
```

Raise events through aggregate methods such as `place()`, never directly in the
factory. The factory calls the method and the method owns the event, which keeps
[Encapsulate State Changes](encapsulate-state-changes.md) intact.

---

## Naming factory methods

Name a factory classmethod in the domain's own language. Use the name to say
**where the aggregate comes from**, or **what kind of creation this is**:

| Good Name | What It Expresses |
|-----------|------------------|
| `Order.from_cart(...)` | Created from a shopping cart |
| `Order.from_subscription_renewal(...)` | Created as a subscription renewal |
| `Order.as_replacement(...)` | Created as a replacement for a return |
| `Account.open_personal(...)` | A personal account opening |
| `Account.open_business(...)` | A business account opening |
| `Invoice.from_order(...)` | Created from a completed order |
| `User.register(...)` | Created through registration |
| `Tenant.onboard(...)` | Created through onboarding |
| `Payment.record_from_gateway(...)` | Created from a payment gateway callback |

Avoid `create()`, `build()`, and `make()`. They say nothing about which
creation this is.

---

## When to use a standalone factory class

Classmethods on the aggregate cover most cases. Sometimes the assembly work does
not belong on the aggregate at all.

### When do you need a standalone factory?

1. **It needs a repository.** An aggregate should know nothing about
   repositories. When building one means loading others first, say an Invoice
   that needs the Order, the Customer, and the TaxPolicy, put it in a standalone
   class.

2. **It is large.** When a classmethod runs to 40 lines or more, it takes up
   much of the aggregate class. The aggregate is easier to read without it.

3. **It translates outside data.** To build an aggregate from a Stripe webhook,
   an ERP sync, or a CSV row, the code must know that system's data format. The
   aggregate should never contain that knowledge. A standalone factory is the
   anti-corruption layer.

### Write a standalone factory as a plain class

A standalone factory is just a class in the domain layer. It needs no framework
registration; it is plain Python:

```python
--8<-- "patterns/factory-methods-for-aggregate-creation/001.py:standalone_factory"
```

The handler stays thin:

```python
# fragment
@handle(PlaceOrder)
def place_order(self, command: PlaceOrder):
    order = OrderFactory.from_cart_checkout(
        cart_id=command.cart_id,
        customer_id=command.customer_id,
    )
    current_domain.repository_for(Order).add(order)
```

### Translating external data (anti-corruption layer)

Subscribers receive raw dicts from outside systems. A standalone factory turns
that payload into a domain aggregate:

```python
--8<-- "patterns/factory-methods-for-aggregate-creation/002.py:factory"
```

The aggregate never sees the outside format. When Stripe changes its webhook
schema you edit the factory, and `Payment` and its invariants stay as they are.

---

## Choosing between the two

| Scenario | Recommended Approach |
|----------|---------------------|
| Simple construction, few fields | Direct instantiation: `User(name="Alice", email=email)` |
| Multiple creation paths for the same aggregate | Factory classmethods on the aggregate |
| Construction with validation specific to a creation path | Factory classmethods on the aggregate |
| Construction needs to load other aggregates | Standalone factory class |
| Construction translates external data formats | Standalone factory class (ACL) |
| Construction logic is 40+ lines and dominates the aggregate | Standalone factory class |
| Single simple creation path | No factory needed, inline in handler |

The progression is **inline, then classmethod, then standalone class**. Start
with the simplest form, inline construction. When that form no longer fits the
creation code, move to the next form.

---

## What this does for tests

You can test a factory classmethod on its own, with no infrastructure:

```python
--8<-- "patterns/factory-methods-for-aggregate-creation/001.py:tests"
```

No repository, no command, no handler, no unit of work: call the classmethod
and assert on what it returns. A standalone factory is a plain class, and you
test it the same way. The exception is a factory that loads aggregates of its
own. For example, `OrderFactory.from_cart_checkout` loads the Cart and the
Customer. Those tests have to persist that data first.

---

## How do factories differ from domain services?

Factories and domain services do different jobs:

| Aspect | Factory | Domain Service |
|--------|---------|---------------|
| **Purpose** | Create a new aggregate | Coordinate logic across existing aggregates |
| **Input** | Raw data or other aggregates | Live aggregate instances |
| **Output** | A new aggregate instance | Side effects on existing aggregates |
| **When** | Object comes into existence | Object already exists and needs cross-aggregate logic |
| **Example** | `Order.from_cart(items, customer_id)` | `TransferService(source, policy).validate_and_debit(amount, ...)` |

A factory answers "how do I bring this thing into existence?" A domain service
answers "how do I apply a rule across several existing things?"

---

## Why this is not a framework element

Evans listed Factories next to Aggregates and Repositories as DDD lifecycle
patterns. So should Protean ship a `@domain.factory` decorator and a
`BaseFactory`, and make factories registered elements like command handlers and
repositories?

It deliberately does not, for three reasons:

- **A factory has no lifecycle for Protean to manage.** Repositories need
  database adapters. Event handlers need message routing. Command handlers need
  dispatch and a unit of work. A factory builds an object. When it needs a
  repository, it calls the same `current_domain.repository_for()` that any code
  can call. Registering a factory with the domain would add nothing.

- **Factories have too many forms.** A factory can be a constructor, a
  classmethod, a method on another aggregate, or a standalone class. One
  `BaseFactory` would either add too little to be worth having or be too narrow
  to cover all these forms.

- **Python already provides what a factory needs.** A classmethod is the usual
  form of a factory method. A standalone factory is a plain class. Neither
  needs registering to be findable, testable, or maintainable.

The Factory pattern is a design pattern. Protean supports it by leaving
aggregates free to carry classmethods, and by keeping handlers thin enough that
the factory becomes the obvious place for the assembly work.

---

## Summary

| Aspect | Construction in Handlers | Factory Classmethods | Standalone Factory |
|--------|-------------------------|---------------------|-------------------|
| Construction knowledge | Scattered across handlers | Centralized on aggregate | Centralized in factory class |
| Handler size | 15-40 lines | 3-5 lines | 3-5 lines |
| Testability | Requires handler + infra | Direct classmethod calls | Direct classmethod calls |
| Reusability | None (copy-paste between handlers) | Any handler can call | Any handler can call |
| Repository access | In the handler | Not needed (inputs are passed in) | Factory loads from repos |
| External data knowledge | In the handler or subscriber | Not applicable | Factory translates (ACL) |
| When to use | Single, simple creation | Multiple creation paths, moderate complexity | Repository access needed, external data, large logic |

Keep the knowledge of how to build an aggregate in the domain model. Start with
classmethods on the aggregate. When the classmethod needs a repository, has to
translate outside data, or grows too big, move to a standalone factory class.

---

!!! tip "Related reading"
    **Patterns:**

    - [Encapsulate State Changes](encapsulate-state-changes.md): Named methods for state changes complement factory methods for creation.
    - [Thin Handlers, Rich Domain](thin-handlers-rich-domain.md): Factories are
      one way to move construction code out of handlers.
    - [Consuming Events from Other Domains](consuming-events-from-other-domains.md): Standalone factories serve as anti-corruption layers for external data.

    **Concepts:**

    - [Aggregates](../concepts/building-blocks/aggregates.md): Aggregate lifecycle and creation.
    - [Command Handlers](../concepts/building-blocks/command-handlers.md): Where factories are called from.

    **Guides:**

    - [Aggregate Mutation](../guides/domain-behavior/aggregate-mutation.md):
      Moving behavior into aggregates.
    - [Command Handlers](../guides/change-state/command-handlers.md): Keeping handlers thin.
