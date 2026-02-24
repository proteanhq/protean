# Chapter 17: When Things Go Wrong — Dead Letter Queues

A deployment introduced a bug in the `BookReportProjector` — it crashes
on books without an ISBN (the field is optional). The server retries the
message three times, then moves it to the **dead-letter queue** (DLQ).
Meanwhile, new books are being added but the marketing dashboard is not
updating.

## How the DLQ Works

When a handler fails to process a message:

1. The message is retried (up to `max_retries` times, with exponential
   backoff).
2. After all retries are exhausted, the message is moved to the DLQ.
3. The handler continues processing subsequent messages — one failure
   does not block the stream.

## Discovering the Problem

List DLQ entries:

```shell
$ protean dlq list --domain bookshelf
Dead Letter Queue:
  ID          Stream                Handler              Error                  Time
  msg-001     bookshelf::book-fact  BookReportProjector   KeyError: 'isbn'      2024-03-15 10:23:45
  msg-002     bookshelf::book-fact  BookReportProjector   KeyError: 'isbn'      2024-03-15 10:24:12
```

## Inspecting a Failed Message

Get the full details of a failed message:

```shell
$ protean dlq inspect msg-001 --domain bookshelf
Message ID: msg-001
Stream: bookshelf::book-fact
Handler: BookReportProjector
Error: KeyError: 'isbn'
Traceback:
  File "bookshelf/projections.py", line 42, in on_book_report
    report.isbn = event.isbn  # isbn is None for this book!
    ...
Payload:
  {"id": "abc-123", "title": "Brave New World", "author": "Aldous Huxley", "isbn": null, ...}
Retries: 3/3
First failure: 2024-03-15 10:23:45
Last failure: 2024-03-15 10:23:52
```

Now we can see the issue: the projector assumes `isbn` is always present.

## The Fix-and-Replay Cycle

1. **Fix the bug** — handle the `None` case in the projector:

```python
@on(BookFactEvent)
def on_book_report(self, event):
    report = BookReport(
        book_id=event.id,
        title=event.title,
        author=event.author,
        price=event.price,
        isbn=event.isbn or "",  # Handle None
    )
    current_domain.repository_for(BookReport).add(report)
```

2. **Deploy the fix** and restart the server.

3. **Replay the failed messages**:

```shell
# Replay a single message
$ protean dlq replay msg-001 --domain bookshelf

# Or replay all failed messages
$ protean dlq replay-all --domain bookshelf
Replayed 2 messages. 0 failures.
```

4. **Verify** the marketing dashboard now shows all books.

## Purging Abandoned Messages

If a message is truly unrecoverable (bad data that will never process
successfully), purge it:

```shell
$ protean dlq purge --domain bookshelf
Purged 0 messages from DLQ.
```

## DLQ Configuration

The DLQ behavior is configured in `domain.toml`:

```toml
[server.stream_subscription]
max_retries = 3
retry_delay_seconds = 1
enable_dlq = true
```

- **`max_retries`** — how many times to retry before moving to DLQ.
- **`retry_delay_seconds`** — base delay between retries (exponential
  backoff is applied).
- **`enable_dlq`** — set to `false` to disable DLQ (failed messages
  are dropped instead).

## What We Built

- Understanding of the **fix-and-replay cycle**: discover, inspect, fix,
  replay, verify.
- Using `protean dlq list`, `inspect`, `replay`, and `purge`.
- Configuring retry behavior and DLQ settings.

In the next chapter, we will set up monitoring so the team knows about
problems before customers report them.

## Next

[Chapter 18: Monitoring Subscription Health →](18-monitoring.md)
