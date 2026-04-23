# Dead Letter Queues

When a handler or subscriber fails to process a message, Protean retries
it a configurable number of times and then moves it to a **dead letter
queue (DLQ)** instead of blocking the stream. The DLQ is how you recover
from handler bugs, bad data, and transient failures without losing
messages or halting production.

This guide is the operational walkthrough: how to find failed messages,
inspect them, replay them after a fix, and clear out messages that will
never succeed. For the full retry flow per subscription type — how
messages *enter* the DLQ — see
[Error Handling](./error-handling.md).

## When messages end up in the DLQ

A message is routed to the DLQ when:

- A handler fails more than `max_retries` times in a row.
- A message cannot be deserialized (StreamSubscription only — retrying
  a malformed message can't succeed).

The handler keeps processing subsequent messages — one poison pill does
not block the stream. See
[Error Handling: Subscription error flows](./error-handling.md#subscription-error-flows)
for the retry mechanics of each subscription type.

!!! note "DLQ support depends on the broker"
    StreamSubscription (Redis Streams) and BrokerSubscription route
    failed messages to `{stream}:dlq` streams. EventStoreSubscription
    uses a recovery-pass model instead — failed positions are retried
    from the event store rather than copied to a DLQ.

---

## Discover failed messages

Start with `protean dlq list` to see what's failed across the domain:

```shell
$ protean dlq list --domain=my_domain
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ DLQ ID            ┃ Subscription ┃ Consumer Group        ┃ Failure Reason      ┃ Failed At           ┃ Retries ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ 1708768400000-0   │ order        │ app.OrderHandler      │ max_retries_exceed… │ 2026-02-23 10:00:00 │       3 │
│ 1708768500000-0   │ payment      │ app.PaymentHandler    │ max_retries_exceed… │ 2026-02-23 10:01:40 │       3 │
└───────────────────┴──────────────┴───────────────────────┴─────────────────────┴─────────────────────┴─────────┘

2 DLQ message(s) found.
```

Filter by stream category when you know which subscription is failing:

```shell
$ protean dlq list --subscription=order --domain=my_domain
```

---

## Inspect a failure

Use the DLQ ID from `list` to pull the full record — payload, error, and
retry metadata:

```shell
$ protean dlq inspect 1708768400000-0 --domain=my_domain
```

Every DLQ entry carries a `_dlq_metadata` block that tells you where it
came from and why it stopped retrying:

```json
{
  "original_stream": "order",
  "original_id": "msg-abc-123",
  "consumer_group": "app.OrderHandler",
  "consumer": "OrderHandler-host-12345-a1b2c3",
  "failed_at": "2026-02-23T10:00:00+00:00",
  "retry_count": 3
}
```

Read the payload and the error together — they usually point straight
at the bug. A `KeyError: 'isbn'` on a payload with `"isbn": null` tells
you the handler needs to guard against missing optional fields.

---

## Fix and replay

The recovery loop is always the same:

1. **Fix the handler code** that caused the failure.
2. **Deploy the fix** and restart the server.
3. **Replay** the failed message:

   ```shell
   $ protean dlq replay 1708768400000-0 --domain=my_domain
   ```

4. **Verify** the downstream effect took place (e.g., a projection row
   appeared, an aggregate state updated).

`replay` removes the message from the DLQ and republishes it on the
original stream. The handler sees it as a fresh delivery — retries
start from zero.

!!! warning "Deploy the fix first"
    If you replay before deploying the fix, the handler fails again,
    runs through its retries a second time, and lands right back in
    the DLQ with `retry_count=3`. Deploy first, replay second.

---

## Bulk replay after a transient incident

When an external dependency was down — database, broker, third-party API
— and dozens or hundreds of messages have piled up in the DLQ with the
same root cause, replay the whole subscription at once:

```shell
$ protean dlq replay-all --subscription=order --domain=my_domain
```

You'll be prompted to confirm. In automation, skip the prompt with `-y`:

```shell
$ protean dlq replay-all --subscription=order --yes --domain=my_domain
```

Only replay in bulk when you're confident the root cause is resolved.
If the underlying handler bug still exists, every replayed message will
fail again and end up back in the DLQ — multiplying rather than reducing
the incident.

---

## Purge messages that will never succeed

Some DLQ entries are truly unrecoverable:

- The payload was produced by a deleted feature.
- The event refers to an aggregate that no longer exists.
- The bad data has been superseded by a later event.

In those cases, purge them rather than replay:

```shell
$ protean dlq purge --subscription=order --domain=my_domain
```

This is **irreversible** — there's no "undo" once a DLQ message is
purged. Confirm the subscription scope before typing `y`, and prefer
`replay` whenever a fix is possible.

---

## Recover from the Observatory dashboard

Every CLI operation has an equivalent in the
[Observatory dashboard](../../reference/cli/runtime/observatory.md)'s
**DLQ tab**:

- List DLQ messages with a subscription filter.
- Click a row to inspect the full payload.
- Replay a single message or all messages for a subscription.
- Purge messages for a subscription.

The tab auto-refreshes every 5 seconds, so a long-running incident
shows up in near-real-time without re-running `dlq list`.

For programmatic access — scripting replays from an incident runbook,
for example — the same actions are exposed as REST endpoints under
`/api/dlq`. See [DLQ Commands](../../reference/cli/data/dlq.md#observatory-rest-api).

---

## Configure DLQ behavior

DLQ behavior is configured per subscription type in `domain.toml`:

```toml
[server.stream_subscription]
max_retries = 3              # Retry attempts before routing to DLQ
retry_delay_seconds = 1      # Base delay (exponential backoff applies)
enable_dlq = true            # Set false to discard messages instead

[server.broker_subscription]
max_retries = 3
retry_delay_seconds = 1
enable_dlq = true
```

Set `enable_dlq = false` only if you're certain failed messages are safe
to drop — without the DLQ you lose the fix-and-replay workflow entirely.
The full configuration matrix is in
[Error Handling: Configuration reference](./error-handling.md#configuration-reference).

---

## Trim old entries and alert on depth

DLQ streams grow unboundedly unless you trim them. Turn on the DLQ
maintenance task to automate retention and depth alerts:

```toml
[server.dlq]
enabled = true                # Off by default — opt in explicitly
retention_hours = 168         # Trim entries older than 7 days
alert_threshold = 100         # Warn when a DLQ stream reaches 100 entries
check_interval_seconds = 60   # Maintenance cycle cadence
```

When `enabled = true` and a DLQ-capable broker is configured (Redis
Streams today), the Engine runs a background task that:

1. Trims entries older than `retention_hours` from every DLQ stream.
2. Measures each stream's depth every `check_interval_seconds`.
3. Logs a `WARNING` and invokes `alert_callback` (if set) when depth
   reaches `alert_threshold`.

### Route alerts to your paging system

Point `alert_callback` at a dotted import path. The callable receives
the breaching stream, its current depth, and the configured threshold:

```toml
[server.dlq]
enabled = true
alert_threshold = 50
alert_callback = "myapp.alerts.page_oncall"
```

```python
# myapp/alerts.py
def page_oncall(dlq_stream: str, depth: int, threshold: int) -> None:
    send_pagerduty_event(
        summary=f"DLQ {dlq_stream} has {depth} entries (threshold {threshold})",
        severity="warning",
    )
```

Exceptions raised by the callback are caught and logged — they never
crash the maintenance task. Use this hook for PagerDuty, Slack,
OpsGenie, or whatever your on-call system is.

### Override per subscription

Some DLQ streams are tolerant (large, slow-moving backfill); others are
critical (tiny, should stay empty). Override the global defaults for a
specific handler:

```toml
[server.dlq]
enabled = true
retention_hours = 168
alert_threshold = 100

[server.subscriptions.PaymentsProjector]
dlq_retention_hours = 24      # Shorter — faster cleanup for payments
dlq_alert_threshold = 5       # Tighter — page early on payment failures
```

For the full option reference, see
[Configuration: DLQ Maintenance](../../reference/configuration/index.md#dlq-maintenance).

---

## Common errors

| Condition | Behavior |
|---|---|
| Broker doesn't support DLQ | `inspect`, `replay`, and `purge` abort with "does not support dead letter queues". Only brokers implementing the DLQ contract (Redis Streams, BrokerSubscription's Redis-backed transport) expose these commands. |
| Subscription not found | Aborts with "No subscription found for stream category". Check the `--subscription` value against `protean subscriptions list`. |
| DLQ message not found | `inspect` and `replay` abort with "not found" — usually because the ID was already replayed or purged. Re-run `list` to get current IDs. |
| No DLQ messages | `list` prints "No DLQ messages found" — nothing to do. |

---

## See also

- [Error Handling](./error-handling.md) — Retry flows, subscription-specific behavior, and version-conflict auto-retry.
- [`protean dlq` CLI Reference](../../reference/cli/data/dlq.md) — Full command options, output formats, and REST API.
- [Observatory Dashboard](../../reference/cli/runtime/observatory.md) — Visual DLQ management.
- [Monitoring](./monitoring.md) — Alerting on DLQ depth and handler failures.
- [Priority Lanes](./using-priority-lanes.md) — Backfill streams use separate `{stream}:backfill:dlq` queues.
