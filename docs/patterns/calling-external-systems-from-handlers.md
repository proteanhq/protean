# Calling External Systems from Handlers

## The Problem

A handler reacts to `OrderPlaced` by confirming the order and posting to a
partner's webhook. The code reads naturally:

```python
@handle(OrderPlaced)
def confirm_and_notify(self, event):
    repo = current_domain.repository_for(Order)
    order = repo.get(event.order_id)        # transaction opens here
    order.confirm()
    repo.add(order)
    httpx.post(PARTNER_URL, json={"order_id": event.order_id})   # holds locks
```

The `@handle` decorator wraps every handler method in a Unit of Work, and since
[ADR-0027](../adr/0027-unit-of-work-is-a-real-transaction.md) that Unit of Work
is one real database transaction. The transaction opens at the first repository
access and stays open until the method returns. So the `httpx.post` runs inside
the transaction, and while it waits on the partner it holds the row locks and the
pooled connection that `repo.get` and `repo.add` acquired.

Two things go wrong from there. A slow partner holds locks for the length of the
call, and under load the connection pool drains while every handler waits on the
network. And version-conflict (OCC) retry re-runs the whole method body, so a
retry re-posts to the partner. The webhook fires twice for one order.

---

## The Pattern

A handler method either persists or talks to the outside world. Not both.

Split the work into two methods:

- **A persisting method** loads the aggregate, mutates it, persists it, and
  raises an event. It makes no external call.
- **A calling method** makes the external call and reaches no repository. With no
  repository access it runs no transaction and holds no connection, so the call
  costs only wall-clock time.

When the two reactions are independent, they can sit in one handler class as
sibling methods and run in any order:

```python
@domain.event_handler(part_of=Order)
class OrderReactions:
    @handle(OrderPlaced)
    def reserve_stock(self, event):
        repo = current_domain.repository_for(Inventory)
        stock = repo.find_by(product_id=event.product_id)
        stock.reserve(event.quantity)
        repo.add(stock)

    @handle(OrderPlaced)
    def notify_partner(self, event):
        # No repository access, so this method runs no transaction.
        httpx.post(PARTNER_URL, json={"order_id": event.order_id})
```

When the call has to follow the write, or needs a value the write produces, the
persisting method raises an event and the calling method handles that event:

```python
@domain.event_handler(part_of=Order)
class OrderConfirmation:
    @handle(OrderPlaced)
    def confirm(self, event):
        repo = current_domain.repository_for(Order)
        order = repo.get(event.order_id)
        order.confirm()                     # raises OrderConfirmed
        repo.add(order)


@domain.event_handler(part_of=Order)
class PartnerNotifier:
    @handle(OrderConfirmed)
    def notify_partner(self, event):
        httpx.post(
            PARTNER_URL,
            json={"order_id": event.order_id, "confirmed_at": event.confirmed_at},
        )
```

`OrderConfirmed` goes to the [outbox](../concepts/async-processing/outbox.md)
inside the confirming transaction and is published once that transaction commits,
so `notify_partner` runs after the write is durable. The value it needs travels
on the event.

---

## How Protean Supports This

**The Unit of Work is lazy.** A handler method that reaches no repository runs no
transaction and holds no pooled connection, so the "no persistence means no
transaction" half of the rule is a guarantee you can rely on. See [When the
transaction actually
opens](../guides/change-state/unit-of-work.md#when-the-transaction-actually-opens).

**The outbox delivers the value to the calling method.** The event the persisting
method raises is written to the [outbox](../concepts/async-processing/outbox.md)
in that transaction and published after it commits, so the call runs after the
write is durable and the outbox retries delivery on its own.

**Sibling methods are independent.** Several methods on one handler class react to
the same event, each in its own Unit of Work and in no guaranteed order, and one
that fails does not stop the others. See [Event
Handlers](../guides/consume-state/event-handlers.md#the-handle-decorator).

**A check flags the shape.** `protean check` reports
[HANDLER_PERSISTS_AND_CALLS_OUT](../reference/fitness-functions.md#handler-persists-and-calls-out)
when a method calls out after a repository access, the point at which the
transaction is already open. It is advisory, because a handler that needs the
call's result sometimes has to do both.

---

## Applying the Pattern

### Syncing many facets from one external snapshot

The costly shape is a multi-facet sync: one external fetch produces a snapshot,
several facets apply it to the same aggregate, and some facets depend on what an
earlier facet wrote. A billing provider sync is a good example. One `Subscriber`
aggregate holds contact details, a plan, and the feature flags the plan unlocks,
and all three come from the provider.

**Fetch once, persist the snapshot, raise one event.** One handler fetches the
snapshot from the provider, then persists it. The fetch comes before any
repository access, so it runs before the transaction opens.

```python
@domain.event_handler(part_of=Subscriber)
class ProfileFetch:
    @handle(SubscriberSyncRequested)
    def fetch_snapshot(self, event):
        payload = httpx.get(f"{BILLING_URL}/subscribers/{event.subscriber_id}").json()

        repo = current_domain.repository_for(ProfileSnapshot)
        snapshot = ProfileSnapshot.from_payload(event.subscriber_id, payload)
        snapshot.store()                    # raises ProfileSnapshotStored
        repo.add(snapshot)
```

Because the fetch precedes the persist, the call holds no lock, and `protean
check` does not flag it: the rule fires only on a call that comes after a
repository access. A retry re-runs the fetch, a safe repeat for a read.

Persisting the snapshot and giving it an identity keeps the payload out of the
event. Each facet then loads the snapshot by id rather than carrying it on the
event or fetching it again. A fat event would put the whole payload into the event
store forever, and a re-fetch per facet turns one call into several.

**Apply the facets as sibling methods on one class.** They all mutate
`Subscriber`, so they belong together. Sibling methods run sequentially, each in
its own Unit of Work, and each one sees the previous method's commit. Each write
advances the aggregate's version by one, so they never collide.

```python
@domain.event_handler(part_of=Subscriber, stream_category="profile_snapshot")
class ProfileSync:
    @handle(ProfileSnapshotStored)
    def apply_contact(self, event):
        snapshot = current_domain.repository_for(ProfileSnapshot).get(event.snapshot_id)
        repo = current_domain.repository_for(Subscriber)
        subscriber = repo.get(event.subscriber_id)
        subscriber.update_contact(snapshot.email, snapshot.name)
        repo.add(subscriber)

    @handle(ProfileSnapshotStored)
    def apply_plan_and_flags(self, event):
        snapshot = current_domain.repository_for(ProfileSnapshot).get(event.snapshot_id)
        repo = current_domain.repository_for(Subscriber)
        subscriber = repo.get(event.subscriber_id)
        subscriber.change_plan(snapshot.tier, snapshot.seats)   # sets the tier
        subscriber.set_flags_for_tier()                         # reads the tier
        repo.add(subscriber)
```

**Dependent steps share a method.** The feature flags depend on the plan tier, so
they read what `change_plan` wrote. Sibling methods run in an unspecified order,
so a separate `set_flags` method could run first and read the old tier. Putting
both steps in `apply_plan_and_flags` makes their order ordinary code, which is
where an ordering dependency belongs.

### When the two genuinely cannot be split

Sometimes the write needs the call's result, so the two cannot go in separate
methods. An address validation service returns a normalized address, and the
aggregate stores what the service returned:

```python
@handle(AddressSubmitted)
def normalize_and_store(self, event):
    result = httpx.post(VALIDATOR_URL, json={"address": event.raw_address}).json()

    repo = current_domain.repository_for(Customer)
    customer = repo.get(event.customer_id)
    customer.set_address(result["normalized"])
    repo.add(customer)
```

Call first, then persist. Because the Unit of Work is lazy, the transaction opens
at `repo.get`, after the call has already returned, so the call holds no lock. The
risk that remains is that OCC or transient retry re-runs the whole method and
re-issues the call. Pass the remote system's idempotency key so the repeat is
harmless. Protean builds no mechanism for this; the idempotency key is what makes
the retry safe.

When the call itself needs a value you can only read from the aggregate first (a
stored token, the current balance), the call has to sit between the read and the
write, inside the transaction the read opened. `protean check` reports that method
as HANDLER_PERSISTS_AND_CALLS_OUT. Keep the call short, pass the idempotency key,
and silence the check on that handler with `suppress_checks`.

---

## Anti-Patterns

### One method that persists then calls out

This is the `confirm_and_notify` method from [The Problem](#the-problem): the
external call sits inside the transaction the write opened, so it holds locks and
a connection while it waits on the partner, and an OCC retry re-posts. Split it
into `confirm` and `notify_partner`, and chain the call to `OrderConfirmed` when
it must follow the write.

### A separate handler class per facet on a shared aggregate

ADR-0031 offers separate handler classes "for full independence with their own
subscriptions and checkpoints", and that is right when the handlers touch
different aggregates. It is the wrong tool when every handler mutates the same
one.

```python
# Anti-pattern: three classes, all mutating Subscriber, all subscribed to one event.
@domain.event_handler(part_of=Subscriber, stream_category="profile_snapshot")
class ContactSync:
    @handle(ProfileSnapshotStored)
    def apply(self, event): ...          # its own subscription and worker

@domain.event_handler(part_of=Subscriber, stream_category="profile_snapshot")
class PlanSync:
    @handle(ProfileSnapshotStored)
    def apply(self, event): ...          # runs concurrently with the others

@domain.event_handler(part_of=Subscriber, stream_category="profile_snapshot")
class FlagSync:
    @handle(ProfileSnapshotStored)
    def apply(self, event): ...          # and a third worker again
```

Each class gets its own subscription and its own worker, so the three run
concurrently. They all load `Subscriber` at the same version and all try to write
the next one, so two of every three writes lose the version race and retry.
Sibling methods on one class avoid this: they are sequential, and each sees the
previous commit.

### A fat event or a re-fetch per facet

Passing the fetched snapshot on the event makes the event large and writes the
payload into the event store permanently. Re-fetching the snapshot in each facet
turns one external call into one per facet. Persist the snapshot once, give it an
identity, and load it by id.

---

## When Not to Use / Trade-offs

The one-method form covered in [When the two genuinely cannot be
split](#when-the-two-genuinely-cannot-be-split) is the exception: when the write
needs the call's result, the split cannot help, so reach for the remote system's
idempotency key.

Splitting persistence from external calls means more handler methods, and the
value one method needs from another travels on an event. That is the cost of not
holding a transaction open while an external call runs.

---

## Summary

| Situation | What to write |
|-----------|---------------|
| Persist and call out, independent | Two sibling methods on one class |
| Call must follow the write, or needs its value | Persisting method raises an event; calling method handles it |
| Many facets of one aggregate from one snapshot | Fetch and persist the snapshot once, raise one event, apply facets as sibling methods |
| A facet depends on what an earlier facet wrote | Put both in one method |
| The write needs the call's result | One method, plus the remote system's idempotency key |
| Facets that touch different aggregates | Separate handler classes, one per aggregate |
| Facets that all mutate one aggregate | Sibling methods on one class, never separate classes |

---

!!! tip "Related reading"
    **Guides:**

    - [Unit of Work](../guides/change-state/unit-of-work.md): When the transaction opens, and why a call-only method holds no connection.
    - [Event Handlers](../guides/consume-state/event-handlers.md): Defining handlers, sibling independence, and subscriptions.

    **Reference:**

    - [HANDLER_PERSISTS_AND_CALLS_OUT](../reference/fitness-functions.md#handler-persists-and-calls-out): The advisory check for a call that follows a repository access.

    **Explanation:**

    - [ADR-0031](../adr/0031-handlers-persist-or-call-out.md): The decision and what was rejected along the way.
    - [Outbox](../concepts/async-processing/outbox.md): How an event published after commit delivers the value to the next handler.

    **Patterns:**

    - [One Aggregate Per Transaction](one-aggregate-per-transaction.md): The sibling rule for cross-aggregate writes.
    - [Idempotent Event Handlers](idempotent-event-handlers.md): Making a duplicated delivery harmless.
