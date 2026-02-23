# protean subscriptions

Monitor subscription lag and health for all handlers in a Protean domain.

## Commands

### `protean subscriptions status`

Display a table showing each subscription's lag, pending count, DLQ depth,
and overall health status.

```bash
protean subscriptions status --domain=my_app
```

```
                     Subscriptions — my_app
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━┳━━━━━━━━━┳━━━━━┳━━━━━━━━━━━┳━━━━━━━━┓
┃ Handler            ┃ Type        ┃ Stream ┃ Lag ┃ Pending ┃ DLQ ┃ Consumers ┃ Status ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━╇━━━━━━━━━╇━━━━━╇━━━━━━━━━━━╇━━━━━━━━┩
│ OrderProjector     │ event_store │ order  │   0 │       0 │   - │         - │ ok     │
│ PaymentHandler     │ stream      │ payment│  42 │       3 │   1 │         2 │ lagging│
│ OutboxProcessor    │ outbox      │ db→brk │   5 │       5 │   - │         - │ lagging│
└────────────────────┴─────────────┴────────┴─────┴─────────┴─────┴───────────┴────────┘

3 subscription(s), 1 ok, 2 lagging, total lag: 47
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--json` | Output raw JSON instead of a table | `False` |

### JSON output

Use `--json` for machine-readable output suitable for scripting or
integration with external monitoring:

```bash
protean subscriptions status --domain=my_app --json
```

```json
[
  {
    "name": "order-projector",
    "handler_name": "OrderProjector",
    "subscription_type": "event_store",
    "stream_category": "order",
    "lag": 0,
    "pending": 0,
    "current_position": "42",
    "head_position": "42",
    "status": "ok",
    "consumer_count": 0,
    "dlq_depth": 0
  }
]
```

## Subscription types

The command discovers all subscriptions from the domain registry and queries
the appropriate backend for each:

| Type | Backend | Lag calculation |
|------|---------|-----------------|
| `event_store` | Event store position streams | `head_position - current_position` |
| `stream` | Redis consumer groups | Native lag (Redis 7.0+) or `xrange` fallback |
| `broker` | Broker consumer group info | Same as stream for Redis brokers |
| `outbox` | Outbox repository | `pending + processing` count |

## Status values

| Status | Meaning |
|--------|---------|
| `ok` | Caught up -- lag is 0 and nothing pending |
| `lagging` | Behind -- lag > 0 or pending > 0 |
| `unknown` | Unable to query backend infrastructure |

## How it works

This command does **not** require the engine to be running. It walks the
domain registry to discover what subscriptions would exist, then queries
infrastructure directly:

1. Event handlers, command handlers, projectors, and process managers are
   discovered from `domain.registry`
2. The `ConfigResolver` determines each handler's subscription type
3. For event store subscriptions, position streams and `stream_head_position()`
   are queried
4. For stream subscriptions, Redis `XINFO GROUPS` and `XLEN` are queried
5. For outbox processors, `count_by_status()` is queried

## See also

- [Observability](../../server/observability.md) -- Observatory dashboard
  and REST API (includes `/api/subscriptions` endpoint)
- [Subscription Types](../../server/subscription-types.md) -- How
  StreamSubscription and EventStoreSubscription work
- [Run the Server](../../../guides/server/index.md) -- Starting and monitoring
  the engine
