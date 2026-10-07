# Cross-Aggregate Patterns

In every pattern, the event handler sits in the cluster that owns the event and
issues a command to the target aggregate. The target's command handler does the
write. Events are delivered at least once, so each command carries a
deterministic id taken from the event, and the command handler returns without
changes when it has already done that work.

## Pattern 1: State sync

Source aggregate changes state → target aggregate updates its state.

```python
# Order shipped → Inventory stock reduced
@domain.event_handler(part_of=Order)
class InventorySyncHandler:
    @handle(OrderShipped)
    def on_order_shipped(self, event):
        current_domain.process(
            ReduceStock(
                order_id=event.order_id,
                product_id=event.product_id,
                quantity=event.quantity,
            )
        )

@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReduceStock)
    def reduce_stock(self, command):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(product_id=command.product_id)
        if command.order_id in inventory.applied_order_ids:
            return  # already applied
        inventory.reduce_stock(command.order_id, command.quantity)
        repo.add(inventory)
```

## Pattern 2: Lifecycle trigger

Source aggregate reaches a lifecycle point → target aggregate is created or activated.

```python
# Payment confirmed → Subscription activated
@domain.event_handler(part_of=Payment)
class SubscriptionSyncHandler:
    @handle(PaymentConfirmed)
    def on_payment_confirmed(self, event):
        current_domain.process(
            ActivateSubscription(
                payment_id=event.payment_id,
                customer_id=event.customer_id,
                plan_name=event.plan_name,
            )
        )

@domain.command_handler(part_of=Subscription)
class SubscriptionCommandHandler:
    @handle(ActivateSubscription)
    def activate_subscription(self, command):
        repo = current_domain.repository_for(Subscription)
        subscription = repo.find_by(customer_id=command.customer_id)
        if command.payment_id in subscription.applied_payment_ids:
            return  # already applied
        subscription.activate(command.payment_id, command.plan_name)
        repo.add(subscription)
```

When the lifecycle point creates the target, give the new aggregate the id from
the event and check for it first: `repository.get(command.<id>)`, add the
aggregate on `ObjectNotFoundError`, and return otherwise.

## Pattern 3: Counter tracking

Source aggregate events increment/decrement counters on target aggregate.

```python
# Task assigned/completed/unassigned → TeamMember workload updated
@domain.event_handler(part_of=Task)
class WorkloadSyncHandler:
    @handle(TaskAssigned)
    def on_assigned(self, event):
        current_domain.process(
            RecordAssignment(
                member_id=event.assignee_id,
                change_id=event._metadata.headers.id,
            )
        )

@domain.command_handler(part_of=TeamMember)
class TeamMemberCommandHandler:
    @handle(RecordAssignment)
    def record_assignment(self, command):
        repo = current_domain.repository_for(TeamMember)
        member = repo.get(command.member_id)
        if command.change_id in member.applied_change_ids:
            return  # already counted
        member.record_assignment(command.change_id)
        repo.add(member)
```

A task can be assigned, unassigned and assigned again, so the task id cannot
name one change. `event._metadata.headers.id` is the event's own id, the same on
every delivery of that event.

## Choosing the deterministic id

| Situation | Id to carry in the command |
|-----------|----------------------------|
| One event causes one write to the target | An id from the event, such as `order_id` |
| One event causes several writes to the target | A derived key, such as `f"{order_id}:{product_id}"` |
| The same kind of event can recur for one source | The event's own id, `event._metadata.headers.id` |

Never generate a fresh `uuid4()` in the event handler, because a redelivered
event would then look like new work.

## Finding the target aggregate

The target's command handler needs to find the correct target aggregate instance. Common approaches:

| Approach | When to use |
|----------|------------|
| `repo.get(id)` | The command carries the target's ID directly |
| `repo.find_by(field=value)` | The command carries a foreign key to look up by |

## Handler configuration

```python
# fragment
@domain.event_handler(part_of=SourceAggregate)  # The cluster that owns the event
```

With no `stream_category`, the handler listens to its own aggregate's stream.
A handler with `part_of=TargetAggregate` that reacts to the source's event is
what `check` reports as `EVENT_HANDLER_FOREIGN_EVENT`. See
[Anti-patterns](./anti-patterns.md).

For a flow with several causally dependent steps, use a process manager. See
[process-manager](../../process-manager/SKILL.md).
