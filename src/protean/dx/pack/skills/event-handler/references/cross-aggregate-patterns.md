# Cross-Aggregate Patterns

In every pattern, the event handler sits in the cluster that owns the event and
issues a command to the target aggregate. The target's command handler does the
write, and returns without changes when it has already done that work.

Patterns 2 and 3 use these elements, shortened from the skill's assets:

```python
# Pattern 2
@domain.aggregate
class Payment:
    customer_id: Identifier(required=True)
    plan_name: String(required=True)

@domain.event(part_of=Payment)
class PaymentConfirmed:
    payment_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    plan_name: String(required=True)

@domain.aggregate
class Subscription:
    customer_id: Identifier(required=True)
    plan_name: String(required=True)
    status: String(default="inactive")
    applied_payment_ids: List(content_type=String)

    def activate(self, payment_id, plan_name):
        self.plan_name = plan_name
        self.status = "active"
        self.applied_payment_ids = [*self.applied_payment_ids, payment_id]

@domain.command(part_of=Subscription)
class ActivateSubscription:
    payment_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    plan_name: String(required=True)

# Pattern 3
@domain.aggregate
class Task:
    title: String(required=True)
    assignee_id: Identifier()

@domain.event(part_of=Task)
class TaskAssigned:
    task_id: Identifier(required=True)
    assignee_id: Identifier(required=True)

@domain.aggregate
class TeamMember:
    member_id: Identifier(identifier=True)
    assigned_count: Integer(default=0)
    applied_change_ids: List(content_type=String)

    def record_assignment(self, change_id):
        self.assigned_count += 1
        self.applied_change_ids = [*self.applied_change_ids, change_id]

@domain.command(part_of=TeamMember)
class RecordAssignment:
    member_id: Identifier(required=True)
    change_id: Identifier(required=True)
```

## Pattern 1: State sync

Source aggregate changes state → target aggregate updates its state. `OrderShipped`
reduces `Inventory` stock. The code is in SKILL.md, under "Building a
cross-aggregate handler", and in
[assets/cross_sync_order_inventory.py](../assets/cross_sync_order_inventory.py).

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

When the lifecycle point creates the target instead, follow the "command creates
B" case in SKILL.md's "Making the receiving end safe to repeat".

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
name one change. The command carries the event's message id,
`event._metadata.headers.id`, which stays the same on every delivery of that
event. SKILL.md's "Making the receiving end safe to repeat" gives its form and
when it is safe to use.
