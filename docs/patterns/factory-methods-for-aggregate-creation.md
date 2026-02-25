# Factory Methods for Aggregate Creation

## The Problem

A developer writes a command handler to place an order from a shopping cart:

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

This is reasonable. The handler creates an Order, adds items from the command
data, calls a domain method, and persists. But as the system matures, creation
scenarios multiply:

- **Subscription renewal** creates an Order by copying line items from the
  previous cycle's order and applying the current pricing.
- **Admin override** creates an Order with a manually specified discount and a
  different validation path (no credit check).
- **Bulk import** creates Orders from CSV rows with a completely different data
  shape.
- **Return replacement** creates a new Order pre-populated from the original
  order, with only the returned items, flagged as a replacement.

Each scenario has its own handler, and each handler independently assembles the
Order aggregate. The construction logic -- which items to include, how to
calculate the total, which validations to apply, which events to raise -- is
duplicated across handlers, subtly different in each, and drifts apart over
time.

The consequences:

- **Duplicated construction knowledge.** Four handlers each know how to build a
  valid Order. When the Order aggregate gains a new required field, all four must
  be updated. When a business rule changes (e.g., "all orders must now include a
  tax calculation"), each handler must be found and modified independently.

- **Construction bugs.** The subscription renewal handler forgets to raise
  `OrderPlaced`. The bulk import handler doesn't apply the minimum-order-value
  check. The return replacement handler sets the wrong status. Each handler is a
  fresh opportunity to make a construction mistake.

- **Untestable creation logic.** To test that a subscription renewal correctly
  copies line items and applies current pricing, you must construct a command,
  set up a repository, and run the handler inside a UoW. The construction logic
  itself can't be tested in isolation.

- **Thick handlers.** Handlers that should be three lines (load, call, save)
  balloon to 20-40 lines because they're doing construction work that doesn't
  belong to them.

The root cause: **complex construction knowledge is scattered across handlers
instead of being encapsulated in the domain model**.

---

## The Pattern

Encapsulate aggregate creation in **factory classmethods** on the aggregate
itself. Each classmethod represents a named construction path -- a specific way
to bring an aggregate into existence, with its own inputs, validations, and
events.

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

Each classmethod is a **named factory** -- a single, testable method that
encapsulates the complete knowledge of how to create a valid aggregate from a
specific set of inputs. The handler calls the factory and persists the result.

This is Eric Evans' Factory Method pattern from the Blue Book. Evans
distinguished two forms of factories:

| Form | What it is | When to use |
|------|-----------|-------------|
| **Factory Method** | A classmethod on the aggregate | Construction belongs conceptually to the aggregate |
| **Standalone Factory** | A separate class dedicated to creation | Construction needs external data or doesn't belong to the aggregate |

Protean's recommendation: **start with classmethods on the aggregate.** They're
simpler, more discoverable, and keep the construction knowledge close to the
thing being constructed. Use standalone factory classes only when the classmethod
approach proves insufficient (we cover when and how below).

---

## Applying the Pattern

### Before: Construction in Handlers

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

The renewal handler copies construction logic from the placement handler but
gets pricing wrong -- it uses the previous order's prices instead of current
ones. This bug hides because the construction knowledge is spread across
handlers, not centralized.

### After: Factory Classmethods on the Aggregate

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

## The Three Responsibilities of a Factory Classmethod

Every factory classmethod should handle three things:

### 1. Assemble the Aggregate

Build the aggregate and its child entities from the inputs:

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

### 2. Validate Construction Preconditions

Check conditions specific to this creation path. These are different from the
aggregate's post-invariants, which check the aggregate's state after any
mutation. Construction preconditions check whether the creation *should happen
at all*:

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

### 3. Raise Creation Events

If the creation itself is a meaningful domain event, raise it inside the factory:

```python
@classmethod
def from_cart(cls, customer_id, cart_items, shipping_address):
    order = cls(...)
    for item in cart_items:
        order.add_item(**item)

    order.place()  # This raises OrderPlaced internally
    return order
```

Events are raised through aggregate methods (like `place()`), not directly in
the factory. The factory calls the method; the method owns the event. This
keeps the [Encapsulate State Changes](encapsulate-state-changes.md) pattern
intact.

---

## Naming Factory Methods

Factory classmethod names should express **where the aggregate comes from** or
**what kind of creation this is**, using the domain's ubiquitous language:

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

Avoid generic names like `create()`, `build()`, or `make()` -- they don't
express the business context of the creation.

---

## When to Use a Standalone Factory Class

Factory classmethods on the aggregate cover the majority of creation scenarios.
But sometimes the construction logic doesn't belong on the aggregate itself.

### Signs You Need a Standalone Factory

1. **The factory needs repository access.** The aggregate shouldn't know about
   repositories. If construction requires loading other aggregates (e.g.,
   creating an Invoice requires loading the Order AND the Customer AND the
   TaxPolicy), a standalone class is cleaner.

2. **The construction logic is large.** If a factory classmethod would be 40+
   lines and dominate the aggregate class, extracting it improves readability.

3. **External data translation.** When creating an aggregate from an external
   system's data format (Stripe webhook, ERP sync, CSV import), the aggregate
   shouldn't know about external data shapes. A standalone factory acts as an
   anti-corruption layer.

### Standalone Factory as a Plain Class

A standalone factory in Protean is simply a class in the domain layer. It
doesn't need framework registration -- it's plain Python:

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

### External Data Translation (Anti-Corruption Layer)

When integrating with external systems, subscribers receive raw dict payloads.
A standalone factory translates the external format into domain aggregates:

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

The factory isolates the aggregate from external data formats. When Stripe
changes their webhook schema, only the factory changes -- the `Payment`
aggregate and its invariants remain untouched.

---

## Choosing Between Factory Patterns

| Scenario | Recommended Approach |
|----------|---------------------|
| Simple construction, few fields | Direct instantiation: `User(name="Alice", email=email)` |
| Multiple creation paths for the same aggregate | Factory classmethods on the aggregate |
| Construction with validation specific to a creation path | Factory classmethods on the aggregate |
| Construction needs to load other aggregates | Standalone factory class |
| Construction translates external data formats | Standalone factory class (ACL) |
| Construction logic is 40+ lines and dominates the aggregate | Standalone factory class |
| Single straightforward creation path | No factory needed -- inline in handler |

The progression is: **inline < classmethod < standalone class**. Start simple,
extract when complexity justifies it.

---

## Testing Benefits

Factory classmethods are directly testable without infrastructure:

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

No repository, no command, no handler, no UoW. Just call the classmethod,
assert the result. Standalone factories are equally testable -- they're plain
classes with classmethods.

---

## Factories and Domain Services

Factories and domain services serve different purposes and should not be
confused:

| Aspect | Factory | Domain Service |
|--------|---------|---------------|
| **Purpose** | Create a new aggregate | Coordinate logic across existing aggregates |
| **Input** | Raw data or other aggregates | Live aggregate instances |
| **Output** | A new aggregate instance | Side effects on existing aggregates |
| **When** | Object comes into existence | Object already exists and needs cross-aggregate logic |
| **Example** | `Order.from_cart(items, customer_id)` | `TransferService.validate_and_debit(source, policy, amount)` |

A factory answers "how do I bring this thing into existence?" A domain service
answers "how do I coordinate a business rule that spans multiple things that
already exist?"

---

## Why Not a Framework Element?

Evans listed Factories alongside Aggregates and Repositories as DDD lifecycle
patterns. Some developers wonder whether Protean should provide a
`@domain.factory` decorator and a `BaseFactory` class, making factories
first-class domain elements like command handlers or repositories.

Protean deliberately does not do this, for good reasons:

- **Factories have no infrastructure concern.** Repositories need database
  adapters. Event handlers need message routing. Command handlers need dispatch
  and UoW wrapping. Factories just construct objects -- pure domain logic with
  no framework plumbing to manage.

- **Factory shapes vary too widely.** Sometimes it's a constructor. Sometimes a
  classmethod. Sometimes a method on another aggregate. Sometimes a standalone
  class. A single `BaseFactory` abstraction would either be too thin to add
  value or too prescriptive to accommodate this variety.

- **Classmethods and plain classes are sufficient.** Python's classmethods are
  the natural expression of factory methods. Standalone factory classes are just
  classes. Neither needs framework registration to be discoverable, testable,
  or maintainable.

The Factory pattern is a **design pattern**, not a **framework element**. The
framework supports it by keeping aggregates flexible enough to have
classmethods, and by keeping handlers thin enough that factories naturally
emerge as the place for construction logic.

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

The principle: **construction knowledge belongs in the domain model, not in
handlers. Start with classmethods on the aggregate. Extract to a standalone
factory class when the classmethod needs repository access, external data
translation, or grows too large.**

---

!!! tip "Related reading"
    **Patterns:**

    - [Encapsulate State Changes](encapsulate-state-changes.md) -- Named methods for state changes complement factory methods for creation.
    - [Thin Handlers, Rich Domain](thin-handlers-rich-domain.md) -- Factories are one way handlers shed construction weight.
    - [Consuming Events from Other Domains](consuming-events-from-other-domains.md) -- Standalone factories serve as anti-corruption layers for external data.

    **Concepts:**

    - [Aggregates](../concepts/building-blocks/aggregates.md) -- Aggregate lifecycle and creation.
    - [Command Handlers](../concepts/building-blocks/command-handlers.md) -- Where factories are called from.

    **Guides:**

    - [Aggregate Mutation](../guides/domain-behavior/aggregate-mutation.md) -- Pushing behavior into aggregates.
    - [Command Handlers](../guides/change-state/command-handlers.md) -- Keeping handlers thin.
