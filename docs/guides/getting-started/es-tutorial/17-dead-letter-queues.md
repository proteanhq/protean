# Chapter 17: When Things Go Wrong — Dead Letter Queues

A production bug in the `ComplianceAlertHandler` causes it to crash
with a `TypeError` on deposits where `source_type` is `None` — a
pre-upcasting edge case. The handler exhausts its retry attempts and
messages pile up in the **dead-letter queue**.

This chapter covers the operational workflow for discovering, diagnosing,
and recovering from handler failures.

## How DLQ Works

When a `StreamSubscription` handler throws an exception:

1. The message is retried up to `max_retries` times (default: 3)
2. Each retry uses exponential backoff (`retry_delay_seconds * 2^N`)
3. After exhausting retries, the message moves to the **DLQ stream**
4. The subscription continues processing the next message

The DLQ preserves the original payload, the failure reason, the retry
count, and the timestamp. Nothing is lost.

## Discovering the Problem

```shell
$ protean dlq list --domain=fidelis
 DLQ ID              Subscription       Failure Reason           Failed At            Retries
 1719234567890-0     fidelis::account   TypeError: 'NoneT...    2025-06-16 14:22:00  3
 1719234568123-0     fidelis::account   TypeError: 'NoneT...    2025-06-16 14:22:01  3
 1719234569456-0     fidelis::account   TypeError: 'NoneT...    2025-06-16 14:23:15  3

3 DLQ message(s) found.
```

You can filter by subscription:

```shell
$ protean dlq list --subscription=fidelis::account --domain=fidelis
```

## Inspecting a Failed Message

```shell
$ protean dlq inspect 1719234567890-0 --domain=fidelis
DLQ ID:          1719234567890-0
Stream:          fidelis::account
Failure Reason:  TypeError: 'NoneType' object has no attribute 'startswith'
Failed At:       2025-06-16 14:22:00
Retry Count:     3

Payload:
{
  "type": "Fidelis.DepositMade.v1",
  "data": {
    "account_id": "acc-7742",
    "amount": 12000.0,
    "reference": "DEP-8834"
  }
}
```

The inspection shows everything needed to diagnose the issue:

- The **failure reason** (`TypeError`) tells you what went wrong.
- The **payload** shows the exact message that caused the failure.
- The **type** (`Fidelis.DepositMade.v1`) reveals it was a v1 event
  — the `source_type` field is missing because the upcaster has not
  run yet at the handler level.

## Fixing and Replaying

After fixing the handler code (adding a `None` check for
`source_type`) and redeploying:

```shell
# Replay a single message
$ protean dlq replay 1719234567890-0 --domain=fidelis
Replayed message 1719234567890-0 to stream 'fidelis::account'.

# Replay all failed messages for a subscription
$ protean dlq replay-all --subscription=fidelis::account --domain=fidelis
Replay all DLQ messages for subscription 'fidelis::account'? [y/N]: y
Replayed 3 message(s) to stream 'fidelis::account'.
```

Replaying puts the message back on the original stream. The handler
(now fixed) processes it normally.

## Purging Unrecoverable Messages

If messages cannot be fixed (e.g., they reference deleted data):

```shell
$ protean dlq purge --subscription=fidelis::account --domain=fidelis
Purge all DLQ messages for subscription 'fidelis::account'? [y/N]: y
Purged 3 message(s) from DLQ.
```

!!! warning
    `purge` permanently removes messages. Use it only when you are
    certain the messages are unrecoverable or no longer relevant.

## Verifying Recovery

```shell
$ protean dlq list --domain=fidelis
No DLQ messages found.
```

## The Fix-and-Replay Cycle

This pattern will become your standard operating procedure:

1. **Discover** — `protean dlq list` finds failed messages
2. **Inspect** — `protean dlq inspect` reveals the cause
3. **Fix** — update handler code and redeploy
4. **Replay** — `protean dlq replay-all` reprocesses the messages
5. **Verify** — `protean dlq list` confirms the DLQ is empty

## DLQ Configuration

The DLQ is configured in `domain.toml`:

```toml
[server.stream_subscription]
max_retries = 3          # Retry before DLQ
retry_delay_seconds = 1  # Base delay (exponential backoff)
enable_dlq = true        # Enable dead-letter queue
```

Setting `enable_dlq = false` means failed messages are dropped after
exhausting retries. This is almost never what you want in production.

## What We Built

- The **fix-and-replay cycle** for production incident response.
- **`protean dlq list`** — discover failed messages.
- **`protean dlq inspect`** — diagnose the root cause.
- **`protean dlq replay`** / **`replay-all`** — reprocess after fixing.
- **`protean dlq purge`** — discard unrecoverable messages.
- DLQ configuration for retries and backoff.

Next, we set up proactive monitoring to catch problems before they
fill the DLQ.

## Next

[Chapter 18: Monitoring Subscription Health →](18-monitoring-health.md)
