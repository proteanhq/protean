# Factory Methods for Aggregate Creation

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
command carried, calls a domain method, and saves. Then the system grows and you
find yourself creating orders four more ways:

- **Subscription renewal** creates an Order by copying line items from the
  previous cycle's order and applying the current pricing.
- **Admin override** creates an Order with a manually specified discount and a
  different validation path (no credit check).
- **Bulk import** creates Orders from CSV rows with a completely different data
  shape.
- **Return replacement** creates a new Order pre-populated from the original
  order, with only the returned items, flagged as a replacement.

Each one gets its own handler, and each handler assembles the Order itself.
Which items to include, how to total them, which rules to apply, which events to
raise: all of it now exists five times, once per handler. Each copy is slightly
different, and they drift further apart over time.

That costs you in four ways:

- **Five handlers know how to build an Order.** Add a required field to the
  aggregate and you update all five. Change a rule, say every order now needs a
  tax calculation, and you have to find and edit each one.

- **Every copy is a fresh chance to get it wrong.** The renewal handler forgets
  to raise `OrderPlaced`. The bulk import skips the minimum-order-value check.
  The return replacement sets the wrong status.

- **You cannot test the creation on its own.** Checking that a renewal copies
  line items and prices them correctly means building a command, setting up a
  repository, and running the handler inside a unit of work.

- **Handlers get fat.** What should be three lines, load, call, save, becomes 20
  or 40, because the handler is doing assembly work that is not its job.

All four come from the same thing: the knowledge of how to build a valid Order
sits in the handlers, where the domain model should be holding it.

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

Each classmethod is one testable place that holds everything needed to build a
valid aggregate from one set of inputs. The handler calls it and saves what comes
back.

This is Eric Evans' Factory Method pattern from the Blue Book. Evans described
two forms:

| Form | What it is | When to use |
|------|-----------|-------------|
| **Factory Method** | A classmethod on the aggregate | Construction belongs conceptually to the aggregate |
| **Standalone Factory** | A separate class dedicated to creation | Construction needs external data or doesn't belong to the aggregate |

**Start with classmethods on the aggregate.** They are simpler, easier to find,
and they keep the knowledge next to the thing it builds. Move to a standalone
factory class only when a classmethod stops being enough, which the section
below covers.

---

## Applying the pattern

### Before: construction in handlers

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
reuses the previous order's prices when it should look up current ones. Spread
the assembly across handlers and a bug like this has somewhere to hide.

### After: factory classmethods on the aggregate

```python
--8<-- "patterns/factory-methods-for-aggregate-creation/001.py:elements"
--8<-- "patterns/factory-methods-for-aggregate-creation/001.py:aggregate"
```

Each handler is now 4-5 lines: load inputs, call a factory classmethod, persist.
The construction knowledge lives in the aggregate, where it can be tested
directly, reused across handlers, and maintained in one place.

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

Check what this particular creation path requires. These are not the aggregate's
post-invariants, which run after any change and check the state it ends up in.
A precondition asks whether you should be creating the thing *at all*:

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

Name a factory classmethod for **where the aggregate comes from**, or for **what
kind of creation this is**, in the domain's own language:

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

### Signs you need one

1. **It needs a repository.** An aggregate should know nothing about
   repositories. When building one means loading others first, say an Invoice
   that needs the Order, the Customer, and the TaxPolicy, put it in a standalone
   class.

2. **It is large.** A classmethod running to 40 lines or more dominates the
   aggregate class, and the aggregate reads better without it.

3. **It translates outside data.** Building an aggregate from a Stripe webhook,
   an ERP sync, or a CSV row means knowing that system's shape, which the
   aggregate should never carry. A standalone factory is the anti-corruption
   layer.

### A standalone factory as a plain class

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

The progression is **inline, then classmethod, then standalone class**. Start at
the simplest one and move along it only when the work makes you.

---

## What this does for tests

You can test a factory classmethod on its own, with no infrastructure:

```python
--8<-- "patterns/factory-methods-for-aggregate-creation/001.py:tests"
```

No repository, no command, no handler, no unit of work: call the classmethod and
assert on what it returns. A standalone factory is a plain class and tests the
same way, except where it loads aggregates of its own, as
`OrderFactory.from_cart_checkout` loads the Cart and the Customer. Those tests
have to persist that data first.

---

## Factories and domain services

Factories and domain services do different jobs:

| Aspect | Factory | Domain Service |
|--------|---------|---------------|
| **Purpose** | Create a new aggregate | Coordinate logic across existing aggregates |
| **Input** | Raw data or other aggregates | Live aggregate instances |
| **Output** | A new aggregate instance | Side effects on existing aggregates |
| **When** | Object comes into existence | Object already exists and needs cross-aggregate logic |
| **Example** | `Order.from_cart(items, customer_id)` | `TransferService.validate_and_debit(source, policy, amount)` |

A factory answers "how do I bring this thing into existence?" A domain service
answers "how do I apply a rule that spans several things which already exist?"

---

## Why this is not a framework element

Evans listed Factories next to Aggregates and Repositories as DDD lifecycle
patterns, which raises a fair question: should Protean ship a `@domain.factory`
decorator and a `BaseFactory`, making factories registered elements the way
command handlers and repositories are?

It deliberately does not, for three reasons:

- **A factory has no lifecycle to manage.** Repositories need database adapters,
  event handlers need message routing, command handlers need dispatch and a unit
  of work. A factory builds an object, and when it needs a repository it reaches
  for the same `current_domain.repository_for()` any code can call. Registering
  it would buy nothing.

- **Factories take too many shapes.** A constructor, a classmethod, a method on
  another aggregate, a standalone class. One `BaseFactory` would be either too
  thin to earn its place or too narrow to fit them all.

- **Python already has the tools.** A classmethod is the natural form of a
  factory method, and a standalone factory is a class. Neither needs registering
  to be findable, testable, or maintainable.

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
classmethods on the aggregate, and move to a standalone factory class when the
classmethod needs a repository, has to translate outside data, or grows too big.

---

!!! tip "Related reading"
    **Patterns:**

    - [Encapsulate State Changes](encapsulate-state-changes.md): Named methods for state changes complement factory methods for creation.
    - [Thin Handlers, Rich Domain](thin-handlers-rich-domain.md): Factories are one way handlers shed construction weight.
    - [Consuming Events from Other Domains](consuming-events-from-other-domains.md): Standalone factories serve as anti-corruption layers for external data.

    **Concepts:**

    - [Aggregates](../concepts/building-blocks/aggregates.md): Aggregate lifecycle and creation.
    - [Command Handlers](../concepts/building-blocks/command-handlers.md): Where factories are called from.

    **Guides:**

    - [Aggregate Mutation](../guides/domain-behavior/aggregate-mutation.md): Pushing behavior into aggregates.
    - [Command Handlers](../guides/change-state/command-handlers.md): Keeping handlers thin.
