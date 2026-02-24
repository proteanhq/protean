# Chapter 7: Reacting to Events

The compliance team mandates that every deposit over $10,000 triggers a
suspicious-activity alert. The marketing team wants a welcome email when
a new account opens. These are **side effects** that do not belong in
the aggregate or the projector. In this chapter we will create **event
handlers** — decoupled listeners that react to events and trigger
external actions.

## Event Handlers vs. Projectors

| | Projectors | Event Handlers |
|---|-----------|---------------|
| **Purpose** | Maintain read models | Trigger side effects |
| **State** | Update projections | Stateless |
| **Decorator** | `@on(EventType)` | `@handle(EventType)` |
| **Output** | Projection writes | Commands, API calls, logs |

Both consume events, but their responsibilities are different.

## The Compliance Alert Handler

```python
--8<-- "guides/getting-started/es-tutorial/ch07.py:compliance_handler"
```

This handler watches all `DepositMade` events. When one exceeds $10,000,
it prints an alert. In a real system, this would create a
`ComplianceAlert` aggregate or call an external service.

## The Notification Handler

```python
--8<-- "guides/getting-started/es-tutorial/ch07.py:notification_handler"
```

A single event handler can handle multiple event types. The
`NotificationHandler` listens for both `AccountOpened` (welcome message)
and `WithdrawalMade` (large withdrawal alert).

## Multiple Consumers, One Event

A key principle of event-driven architecture: **a single event can be
consumed by multiple listeners**. When a large deposit occurs:

1. The **AccountSummaryProjector** updates the dashboard
2. The **ComplianceAlertHandler** triggers an alert
3. The **NotificationHandler** could send a receipt

None of these consumers know about each other. They are decoupled by
the event.

## Trying It Out

```python
--8<-- "guides/getting-started/es-tutorial/ch07.py:usage"
```

```shell
$ python fidelis.py
[NOTIFICATION] Welcome Alice Johnson! Account ACC-001 is ready.
Account opened: acc-001-uuid...
[COMPLIANCE ALERT] Large deposit: $15,000.00 to account acc-001-uuid
[NOTIFICATION] Large withdrawal alert: $6,000.00
Final balance: $10,000.00
```

## Issuing Commands from Handlers

Event handlers can also issue commands to trigger work in other
aggregates. For example, a compliance handler could create an
investigation:

```python
@handle(DepositMade)
def on_large_deposit(self, event: DepositMade):
    if event.amount >= 10_000:
        current_domain.process(
            CreateComplianceInvestigation(
                account_id=event.account_id,
                amount=event.amount,
            )
        )
```

This is how **cross-aggregate coordination** works without coupling —
the Account aggregate knows nothing about the Compliance aggregate. The
event handler bridges them.

## What We Built

- **ComplianceAlertHandler** — reacts to large deposits.
- **NotificationHandler** — sends welcome messages and withdrawal alerts.
- Event handlers that are **stateless** and **decoupled** from the
  aggregate.
- The pattern for **issuing commands from handlers** for cross-aggregate
  coordination.

Our system now reacts to events. But everything still runs synchronously
— a slow compliance check blocks the deposit response. In the next
chapter, we will switch to asynchronous processing with Redis and the
Protean server.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch07.py:full"
```

## Next

[Chapter 8: Going Async — The Server →](08-going-async.md)
