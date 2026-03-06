# Use Fact Events as Cross-Context Integration Contracts

## The Problem

A Customer domain publishes granular domain events whenever a customer's
profile changes:

```python
customers = Domain(__file__, "Customers")


@customers.event(part_of=Customer)
class CustomerAddressChanged(BaseEvent):
    customer_id: Identifier(required=True)
    new_street: String(required=True)
    new_city: String(required=True)
    new_zip: String(required=True)


@customers.event(part_of=Customer)
class CustomerPhoneUpdated(BaseEvent):
    customer_id: Identifier(required=True)
    new_phone: String(required=True)


@customers.event(part_of=Customer)
class CustomerNameCorrected(BaseEvent):
    customer_id: Identifier(required=True)
    new_first_name: String(required=True)
    new_last_name: String(required=True)


@customers.event(part_of=Customer)
class CustomerEmailVerified(BaseEvent):
    customer_id: Identifier(required=True)
    verified_email: String(required=True)


@customers.event(part_of=Customer)
class CustomerTierUpgraded(BaseEvent):
    customer_id: Identifier(required=True)
    new_tier: String(required=True)
```

The Fulfillment domain needs customer data to ship orders. It subscribes to
the Customer domain's broker stream and tries to build a local representation
of each customer:

```python
fulfillment = Domain(__file__, "Fulfillment")


@fulfillment.subscriber(stream="customer_events")
class CustomerEventSubscriber(BaseSubscriber):

    def __call__(self, payload: dict) -> None:
        event_type = payload.get("type", "")

        if "CustomerAddressChanged" in event_type:
            self._update_address(payload)
        elif "CustomerPhoneUpdated" in event_type:
            self._update_phone(payload)
        elif "CustomerNameCorrected" in event_type:
            self._update_name(payload)
        elif "CustomerEmailVerified" in event_type:
            self._update_email(payload)
        elif "CustomerTierUpgraded" in event_type:
            self._update_tier(payload)

    def _update_address(self, payload: dict) -> None:
        repo = fulfillment.repository_for(ShippingProfile)
        profile = repo.find_by(customer_id=payload["customer_id"])
        profile.update_address(
            street=payload["new_street"],
            city=payload["new_city"],
            zip_code=payload["new_zip"],
        )
        repo.add(profile)

    def _update_phone(self, payload: dict) -> None:
        repo = fulfillment.repository_for(ShippingProfile)
        profile = repo.find_by(customer_id=payload["customer_id"])
        profile.phone = payload["new_phone"]
        repo.add(profile)

    # ... and so on for every event type
```

This creates a cascade of problems:

- **Taxonomy coupling.** The Fulfillment domain must know about every granular
  event type the Customer domain publishes. When the Customer domain adds
  `CustomerPreferredLanguageSet`, the Fulfillment domain must decide whether to
  handle it -- even if it doesn't care. Miss one event and local state drifts.

- **State reconstruction from deltas.** The subscriber must process events in
  order and incrementally update its local model. If events arrive out of order,
  or if the subscriber misses one, the local representation becomes inconsistent.
  Recovering requires replaying the entire event stream from the beginning.

- **Brittle initialization.** When a new customer is created, the Fulfillment
  domain must handle the `CustomerRegistered` event and then correctly process
  every subsequent delta. If the Fulfillment domain comes online after the
  customer already exists, it must replay every event to reconstruct the current
  state.

- **Schema evolution amplified.** Every time the Customer domain adds, renames,
  or restructures a granular event, every consuming domain must update its
  subscriber. With five consuming domains and twelve event types, a single event
  rename requires coordination across five codebases.

- **Testing complexity.** Testing the subscriber requires constructing sequences
  of granular events that simulate realistic state transitions. A test for
  "customer with verified email and updated address" requires generating three
  events in the correct order.

The root cause: **consuming granular domain events forces external contexts
to reconstruct aggregate state from a stream of deltas, coupling them to the
producer's internal event taxonomy**.

---

## The Pattern

Enable `fact_events=True` on aggregates whose state is consumed by other
bounded contexts. Fact events auto-generate a **complete snapshot** of the
aggregate's state after every persistence operation.

This creates a **dual-stream architecture**:

```
                          Customer Aggregate
                          (fact_events=True)
                                │
                    ┌───────────┴───────────┐
                    │                       │
             Delta Events              Fact Events
          (what changed)           (full state snapshot)
                    │                       │
            ┌───────┴───────┐               │
            │               │               │
    Event Handlers     Projectors      Subscribers
    (internal)         (internal)      (external)
            │               │               │
    Sync billing      Build read       Fulfillment
    Send email        models           Shipping
    Update cache                       Analytics
```

**Granular delta events** flow to internal consumers -- event handlers and
projectors within the same domain -- that react to specific state transitions.

**Fact events** flow to external consumers -- subscribers in other bounded
contexts -- that need the aggregate's current state without reconstructing it
from a history of deltas.

The consuming domain receives a single event type (`CustomerFactEvent`) that
always contains the complete customer state. It replaces its local
representation wholesale, regardless of what specific change triggered the
event. No taxonomy coupling. No delta reconstruction. No ordering sensitivity.

---

## Applying the Pattern

### Step 1: Enable fact events on the producing aggregate

In the Customer domain, add `fact_events=True` to the aggregate that external
contexts consume:

```python
from protean import Domain
from protean.fields import Auto, String, ValueObject

customers = Domain(__file__, "Customers")


@customers.value_object
class Address:
    street: String(max_length=200)
    city: String(max_length=100)
    zip_code: String(max_length=20)
    country: String(max_length=50)


@customers.aggregate(fact_events=True)
class Customer:
    customer_id: Auto(identifier=True)
    first_name: String(required=True, max_length=50)
    last_name: String(required=True, max_length=50)
    email: String(required=True)
    phone: String()
    tier: String(default="STANDARD")
    shipping_address = ValueObject(Address)

    def correct_name(self, first_name: str, last_name: str):
        self.first_name = first_name
        self.last_name = last_name
        self.raise_(CustomerNameCorrected(
            customer_id=self.customer_id,
            new_first_name=first_name,
            new_last_name=last_name,
        ))

    def update_address(self, address: Address):
        self.shipping_address = address
        self.raise_(CustomerAddressChanged(
            customer_id=self.customer_id,
            new_street=address.street,
            new_city=address.city,
            new_zip=address.zip_code,
        ))

    def upgrade_tier(self, new_tier: str):
        self.tier = new_tier
        self.raise_(CustomerTierUpgraded(
            customer_id=self.customer_id,
            new_tier=new_tier,
        ))
```

With `fact_events=True`, Protean auto-generates a `CustomerFactEvent` class
mirroring every field on the aggregate. After every successful persistence
(add or update), a `CustomerFactEvent` is raised containing the full aggregate
state at that point in time.

The granular delta events (`CustomerNameCorrected`, `CustomerAddressChanged`,
`CustomerTierUpgraded`) are still raised explicitly in each method. Internal
consumers use these for precise reactions.

### Step 2: Internal consumers use delta events

Within the Customer domain, event handlers and projectors subscribe to
granular delta events. They react to **specific changes** with targeted logic:

```python
@customers.event(part_of=Customer)
class CustomerNameCorrected(BaseEvent):
    customer_id: Identifier(required=True)
    new_first_name: String(required=True)
    new_last_name: String(required=True)


@customers.event(part_of=Customer)
class CustomerAddressChanged(BaseEvent):
    customer_id: Identifier(required=True)
    new_street: String(required=True)
    new_city: String(required=True)
    new_zip: String(required=True)


@customers.event(part_of=Customer)
class CustomerTierUpgraded(BaseEvent):
    customer_id: Identifier(required=True)
    new_tier: String(required=True)


@customers.event_handler(part_of=Customer)
class CustomerNotificationHandler(BaseEventHandler):

    @handle(CustomerAddressChanged)
    def on_address_changed(self, event: CustomerAddressChanged):
        # Send address verification email -- only triggers on address changes
        send_address_verification(
            customer_id=event.customer_id,
            new_city=event.new_city,
            new_zip=event.new_zip,
        )

    @handle(CustomerTierUpgraded)
    def on_tier_upgraded(self, event: CustomerTierUpgraded):
        # Send congratulations -- only triggers on tier changes
        send_tier_upgrade_notification(
            customer_id=event.customer_id,
            new_tier=event.new_tier,
        )
```

These handlers need to know **what** changed, not the full state. Delta events
are the right tool for internal reactions to specific state transitions.

### Step 3: External consumers use fact events

The Fulfillment domain subscribes to the Customer domain's fact event stream.
It receives a complete snapshot on every change, regardless of what specific
field was modified:

```python
fulfillment = Domain(__file__, "Fulfillment")


@fulfillment.aggregate
class ShippingProfile:
    """Fulfillment domain's local model of a customer."""
    profile_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    full_name: String(required=True)
    email: String(required=True)
    phone: String()
    street: String()
    city: String()
    zip_code: String()
    tier: String(default="STANDARD")


@fulfillment.subscriber(stream="customer_fact_events")
class CustomerFactEventSubscriber(BaseSubscriber):

    def __call__(self, payload: dict) -> None:
        repo = fulfillment.repository_for(ShippingProfile)

        try:
            profile = repo.find_by(customer_id=payload["customer_id"])
        except ObjectNotFoundError:
            profile = ShippingProfile(customer_id=payload["customer_id"])

        # Overwrite everything from the latest snapshot
        profile.full_name = (
            f"{payload['first_name']} {payload['last_name']}"
        )
        profile.email = payload["email"]
        profile.phone = payload.get("phone", "")
        profile.street = payload.get("shipping_address", {}).get("street", "")
        profile.city = payload.get("shipping_address", {}).get("city", "")
        profile.zip_code = payload.get("shipping_address", {}).get("zip_code", "")
        profile.tier = payload.get("tier", "STANDARD")

        repo.add(profile)
```

The subscriber handles **one event type** -- the fact event -- and always
overwrites the entire local representation. It doesn't matter whether the
customer changed their name, address, phone, or tier. The subscriber receives
the current state and replaces its local copy.

When the Customer domain later adds `preferred_language` to the aggregate,
the fact event automatically includes it. The Fulfillment subscriber can
choose to map it to a local field or simply ignore it. No new event type
to handle. No risk of silent drift.

### Multiple external consumers

The fact event stream can serve any number of consuming domains. Each extracts
only the fields it needs:

```python
# ── Fulfillment Domain ──────────────────────────────────────────

@fulfillment.subscriber(stream="customer_fact_events")
class CustomerFactEventSubscriber(BaseSubscriber):

    def __call__(self, payload: dict) -> None:
        # Extracts name, address, tier for shipping decisions
        ...


# ── Analytics Domain ────────────────────────────────────────────

@analytics.subscriber(stream="customer_fact_events")
class CustomerAnalyticsSubscriber(BaseSubscriber):

    def __call__(self, payload: dict) -> None:
        repo = analytics.repository_for(CustomerMetrics)

        try:
            metrics = repo.find_by(customer_id=payload["customer_id"])
        except ObjectNotFoundError:
            metrics = CustomerMetrics(customer_id=payload["customer_id"])

        # Extracts only the fields Analytics cares about
        metrics.tier = payload.get("tier", "STANDARD")
        metrics.has_verified_email = bool(payload.get("email"))
        metrics.has_phone = bool(payload.get("phone"))
        metrics.has_address = bool(payload.get("shipping_address"))

        repo.add(metrics)
```

Each domain consumes the same fact event stream independently. The Customer
domain's internal handlers and projectors continue to use granular delta events
for precise, operation-specific reactions. External consumers get full state
snapshots, each mapping the payload to its own local model.

---

## Anti-Patterns

### Using granular events for cross-context integration

```python
# Anti-pattern: external domain handles every internal event type
@fulfillment.subscriber(stream="customer_events")
class CustomerEventSubscriber(BaseSubscriber):

    def __call__(self, payload: dict) -> None:
        event_type = payload.get("type", "")

        # Fulfillment must track every event type the Customer domain invents
        if "CustomerRegistered" in event_type:
            self._create_profile(payload)
        elif "CustomerAddressChanged" in event_type:
            self._update_address(payload)
        elif "CustomerPhoneUpdated" in event_type:
            self._update_phone(payload)
        elif "CustomerNameCorrected" in event_type:
            self._update_name(payload)
        elif "CustomerEmailVerified" in event_type:
            self._update_email(payload)
        elif "CustomerTierUpgraded" in event_type:
            self._update_tier(payload)
        # Forgot CustomerPreferredLanguageSet -- local state drifts silently
```

This couples the consuming domain to the producer's event taxonomy. Every new
event type in the Customer domain creates work (or risk) in every consuming
domain.

**Fix:** Subscribe to the fact event stream instead. One event type, one
handler, full state on every change.

### Using fact events for internal reactions

```python
# Anti-pattern: internal handler reacting to fact events
@customers.event_handler(part_of=Customer)
class CustomerInternalHandler(BaseEventHandler):

    @handle("Customers.CustomerFact.v1")
    def on_customer_changed(self, message: Message):
        # What changed? We don't know. Was it a name correction?
        # A tier upgrade? An address change?
        # The fact event doesn't tell us WHAT happened,
        # only the current state.
        #
        # We have to diff against previous state to figure out
        # what action to take.
        previous = load_previous_state(message.payload["customer_id"])
        current = message.payload

        if previous["tier"] != current["tier"]:
            recalculate_loyalty_benefits(current["customer_id"])
        if previous["email"] != current["email"]:
            send_email_verification(current["customer_id"])
        # Fragile, error-prone, and defeats the purpose of events
```

Fact events carry **what the state is**, not **what happened**. Internal
consumers that need to react to specific operations should use delta events
that carry semantic meaning: `CustomerTierUpgraded` tells the handler exactly
what happened; a fact event requires the handler to diff state.

**Fix:** Use delta events for internal reactions. Use fact events for
external state transfer.

### Publishing only fact events with no delta events

```python
# Anti-pattern: fact_events=True but no delta events raised
@customers.aggregate(fact_events=True)
class Customer:
    customer_id: Auto(identifier=True)
    first_name: String(required=True)
    last_name: String(required=True)
    email: String(required=True)
    tier: String(default="STANDARD")

    def correct_name(self, first_name: str, last_name: str):
        # Just mutate -- no delta event
        self.first_name = first_name
        self.last_name = last_name

    def upgrade_tier(self, new_tier: str):
        # Just mutate -- no delta event
        self.tier = new_tier
```

Without delta events, internal consumers lose the ability to react to specific
state transitions. The compliance handler cannot distinguish a name correction
from a tier upgrade. The notification handler cannot send a targeted email.
Every internal consumer must diff state, just like the anti-pattern above.

**Fix:** Raise delta events for meaningful operations alongside fact events.
The two mechanisms serve different audiences.

---

## Summary

| Aspect | Granular Delta Events | Fact Events |
|--------|----------------------|-------------|
| Payload | Only what changed | Full aggregate state snapshot |
| Semantic meaning | High (named operation) | Low (generic "state changed") |
| Best audience | Internal handlers, projectors | External subscribers, other bounded contexts |
| Consumer complexity | Must handle each event type | One handler, replace entire local state |
| Ordering sensitivity | Must process in order | Idempotent -- latest snapshot wins |
| New field in producer | May require new event type | Automatically included in snapshot |
| Taxonomy coupling | High (consumer tracks every event type) | None (one event type) |
| Initialization | Must handle creation event + all deltas | First fact event bootstraps full state |
| Protean mechanism | `self.raise_(...)` in aggregate methods | `fact_events=True` on aggregate decorator |
| Stream separation | Aggregate's primary event stream | Separate fact event stream (`-fact-`) |

The principle: **use fact events as the integration contract between bounded
contexts. External consumers receive complete state snapshots, freeing them
from reconstructing state from a stream of deltas. Reserve granular delta
events for internal reactions where semantic meaning -- knowing what specific
operation occurred -- is essential.**

---

!!! tip "Related reading"
    **Patterns:**

    - [Design Events for Consumers](design-events-for-consumers.md) -- Events carry enough context for consumers.
    - [Consuming Events from Other Domains](consuming-events-from-other-domains.md) -- Subscribers as anti-corruption layers.
    - [Sharing Event Classes Across Domains](sharing-event-classes-across-domains.md) -- Share schemas, not code.
    - [Connecting Concepts Across Bounded Contexts](connect-concepts-across-domains.md) -- Cross-context synchronization.

    **Guides:**

    - [Raising Events](../guides/domain-behavior/raising-events.md) -- How events are raised and enriched.
    - [Subscribers](../guides/consume-state/subscribers.md) -- Consuming messages from external brokers.
    - [Publishing Events to External Brokers](publishing-events-to-external-brokers.md) -- Delivering published events to external brokers via the outbox.
    - [External Event Dispatch](../guides/server/external-event-dispatch.md) -- Step-by-step setup for external broker dispatch.
