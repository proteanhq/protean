# Cross-Aggregate Patterns

## Pattern 1: State sync

Source aggregate changes state → target aggregate updates its state.

```python
# Order shipped → Inventory stock reduced
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class InventorySyncHandler:
    @handle(OrderShipped)
    def on_order_shipped(self, event):
        inventory = domain.repository_for(Inventory)._dao.find_by(product_id=event.product_id)
        inventory.reduce_stock(event.quantity)
        domain.repository_for(Inventory).add(inventory)
```

## Pattern 2: Lifecycle trigger

Source aggregate reaches a lifecycle point → target aggregate is created or activated.

```python
# Payment confirmed → Subscription activated
@domain.event_handler(part_of=Subscription, stream_category=Payment.meta_.stream_category)
class SubscriptionSyncHandler:
    @handle(PaymentConfirmed)
    def on_payment_confirmed(self, event):
        subscription = domain.repository_for(Subscription)._dao.find_by(customer_id=event.customer_id)
        subscription.activate(plan_name=event.plan_name)
        domain.repository_for(Subscription).add(subscription)
```

## Pattern 3: Counter tracking

Source aggregate events increment/decrement counters on target aggregate.

```python
# Task assigned/completed/unassigned → TeamMember workload updated
@domain.event_handler(part_of=TeamMember, stream_category=Task.meta_.stream_category)
class WorkloadSyncHandler:
    @handle(TaskAssigned)
    def on_assigned(self, event):
        member = domain.repository_for(TeamMember).get(event.assignee_id)
        member.assigned_count += 1
        domain.repository_for(TeamMember).add(member)
```

## Finding the target aggregate

The event handler needs to find the correct target aggregate instance. Common approaches:

| Approach | When to use |
|----------|------------|
| `repo.get(id)` | Event carries the target's ID directly |
| `repo._dao.find_by(field=value)` | Event carries a foreign key to look up by |

## Handler configuration

```python
@domain.event_handler(
    part_of=TargetAggregate,                          # Handler belongs to target
    stream_category=SourceAggregate.meta_.stream_category,  # Listen to source
)
```

The `stream_category` is automatically derived from the source aggregate's class name. Use `SourceAggregate.meta_.stream_category` to get it.
