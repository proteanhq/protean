# Factory Methods for Aggregate Creation

## The problem

You write a command handler to place an order from a shopping cart:

```python
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
raise: all of it now exists four times. Each copy is slightly different, and they
drift further apart over time.

That costs you in four ways:

- **Four handlers know how to build an Order.** Add a required field to the
  aggregate and you update all four. Change a rule, say every order now needs a
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
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    shipping_address = ValueObject(Address)
    status: String(default="draft")
    total: Float(default=0.0)
    is_renewal: Boolean(default=False)

    @classmethod
    def from_cart(
        cls,
        customer_id: str,
        cart_items: list[dict],
        shipping_address: Address,
    ) -> "Order":
        """Create an Order from cart checkout."""
        order = cls(
            customer_id=customer_id,
            shipping_address=shipping_address,
        )

        for item in cart_items:
            order.add_item(
                product_id=item["product_id"],
                name=item["name"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
            )

        order.place()
        return order

    @classmethod
    def from_subscription_renewal(
        cls,
        previous_order: "Order",
        current_prices: dict[str, float],
    ) -> "Order":
        """Create a renewal Order from a previous subscription order."""
        order = cls(
            customer_id=previous_order.customer_id,
            shipping_address=previous_order.shipping_address,
            is_renewal=True,
        )

        for item in previous_order.items:
            order.add_item(
                product_id=item.product_id,
                name=item.name,
                quantity=item.quantity,
                unit_price=current_prices[item.product_id],
            )

        order.place()
        return order

    @classmethod
    def as_replacement(
        cls,
        original_order: "Order",
        returned_item_ids: list[str],
    ) -> "Order":
        """Create a replacement Order for returned items."""
        order = cls(
            customer_id=original_order.customer_id,
            shipping_address=original_order.shipping_address,
        )

        for item in original_order.items:
            if item.product_id in returned_item_ids:
                order.add_item(
                    product_id=item.product_id,
                    name=item.name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                )

        order.place()
        return order

    def add_item(self, product_id, name, quantity, unit_price):
        self.items.add(OrderItem(
            product_id=product_id,
            name=name,
            quantity=quantity,
            unit_price=unit_price,
        ))
        self._recalculate_total()

    def place(self):
        if not self.items:
            raise ValidationError({"items": ["Order must have at least one item"]})
        self.status = "placed"
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            total=self.total,
        ))

    def _recalculate_total(self):
        self.total = sum(
            item.quantity * item.unit_price for item in self.items
        )


# --- Handlers become thin ---

@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        repo = current_domain.repository_for(Order)
        order = Order.from_cart(
            customer_id=command.customer_id,
            cart_items=command.items,
            shipping_address=Address(**command.shipping_address),
        )
        repo.add(order)

    @handle(RenewSubscriptionOrder)
    def renew_subscription(self, command: RenewSubscriptionOrder):
        repo = current_domain.repository_for(Order)
        previous = repo.get(command.previous_order_id)
        order = Order.from_subscription_renewal(
            previous_order=previous,
            current_prices=command.current_prices,
        )
        repo.add(order)

    @handle(CreateReplacementOrder)
    def create_replacement(self, command: CreateReplacementOrder):
        repo = current_domain.repository_for(Order)
        original = repo.get(command.original_order_id)
        order = Order.as_replacement(
            original_order=original,
            returned_item_ids=command.returned_item_ids,
        )
        repo.add(order)
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
@classmethod
def from_subscription_renewal(cls, previous_order, current_prices):
    if previous_order.status != "delivered":
        raise ValidationError(
            {"previous_order": ["Can only renew from a delivered order"]}
        )

    if not previous_order.is_renewal_eligible:
        raise ValidationError(
            {"previous_order": ["Order is not eligible for renewal"]}
        )

    # Proceed with construction...
```

### 3. Raise the creation events

When the creation is itself a domain event, raise it inside the factory:

```python
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
# domain/order/factories.py

class OrderFactory:
    """Encapsulates complex Order creation that requires
    loading data from multiple sources."""

    @classmethod
    def from_cart_checkout(
        cls,
        cart_id: str,
        customer_id: str,
    ) -> Order:
        """Create an Order by loading a Cart and Customer."""
        cart = current_domain.repository_for(Cart).get(cart_id)
        customer = current_domain.repository_for(Customer).get(customer_id)

        if customer.is_suspended:
            raise ValidationError(
                {"customer": ["Suspended customers cannot place orders"]}
            )

        if not cart.items:
            raise ValidationError(
                {"cart": ["Cannot create order from empty cart"]}
            )

        order = Order(
            customer_id=customer.id,
            shipping_address=customer.default_address,
        )

        for item in cart.items:
            order.add_item(
                product_id=item.product_id,
                name=item.product_name,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )

        order.place()
        return order
```

The handler stays thin:

```python
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
# domain/payment/factories.py

class PaymentFactory:
    """Anti-corruption layer for external payment system data."""

    STRIPE_STATUS_MAP = {
        "succeeded": "completed",
        "requires_payment_method": "failed",
        "canceled": "cancelled",
    }

    @classmethod
    def from_stripe_webhook(cls, payload: dict) -> Payment:
        """Translate a Stripe webhook payload into a Payment aggregate."""
        data = payload["data"]["object"]
        return Payment(
            external_id=data["id"],
            amount=Money(
                cents=data["amount"],
                currency=data["currency"].upper(),
            ),
            status=cls.STRIPE_STATUS_MAP.get(data["status"], "pending"),
            customer_email=data.get("receipt_email", ""),
            paid_at=datetime.fromtimestamp(data["created"], tz=timezone.utc),
        )


# The subscriber stays thin
@domain.subscriber(channel="stripe-webhooks")
class StripeWebhookSubscriber:

    @handle("payment_intent.succeeded")
    def handle_payment_success(self, payload: dict):
        payment = PaymentFactory.from_stripe_webhook(payload)
        current_domain.repository_for(Payment).add(payment)
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
class TestOrderCreation:

    def test_from_cart_creates_order_with_items(self, test_domain):
        order = Order.from_cart(
            customer_id="cust-1",
            cart_items=[
                {"product_id": "p1", "name": "Widget", "quantity": 2, "unit_price": 10.0},
                {"product_id": "p2", "name": "Gadget", "quantity": 1, "unit_price": 25.0},
            ],
            shipping_address=Address(
                street="123 Main St",
                city="Springfield",
                state="IL",
                postal_code="62701",
                country="US",
            ),
        )

        assert order.customer_id == "cust-1"
        assert len(order.items) == 2
        assert order.total == 45.0
        assert order.status == "placed"
        assert len(order._events) == 1
        assert isinstance(order._events[0], OrderPlaced)

    def test_renewal_uses_current_prices(self, test_domain):
        previous = Order(
            customer_id="cust-1",
            shipping_address=Address(...),
        )
        previous.add_item(product_id="p1", name="Widget", quantity=2, unit_price=10.0)

        renewed = Order.from_subscription_renewal(
            previous_order=previous,
            current_prices={"p1": 12.0},  # Price increased
        )

        assert renewed.items[0].unit_price == 12.0  # Uses current price
        assert renewed.total == 24.0
        assert renewed.is_renewal is True

    def test_replacement_includes_only_returned_items(self, test_domain):
        original = Order(
            customer_id="cust-1",
            shipping_address=Address(...),
        )
        original.add_item(product_id="p1", name="Widget", quantity=1, unit_price=10.0)
        original.add_item(product_id="p2", name="Gadget", quantity=1, unit_price=25.0)

        replacement = Order.as_replacement(
            original_order=original,
            returned_item_ids=["p1"],
        )

        assert len(replacement.items) == 1
        assert replacement.items[0].product_id == "p1"

    def test_renewal_rejects_undelivered_order(self, test_domain):
        previous = Order(customer_id="cust-1", status="draft")

        with pytest.raises(ValidationError) as exc:
            Order.from_subscription_renewal(
                previous_order=previous,
                current_prices={},
            )

        assert "delivered" in str(exc.value)
```

No repository, no command, no handler, no unit of work: call the classmethod and
assert on what it returns. Standalone factories test the same way, being plain
classes.

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

- **A factory touches no infrastructure.** Repositories need database adapters,
  event handlers need message routing, command handlers need dispatch and a unit
  of work. A factory builds an object. There is nothing for the framework to
  manage.

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
