# Chapter 19: The Great Catalog Import — Priority Lanes

Bookshelf has acquired the catalog of **Vintage Press** — 50,000 books
that need to be imported. Running 50,000 `AddBook` commands through the
normal pipeline would flood the Redis streams and starve real-time
orders and browsing. We need a way to run the import without
affecting production traffic.

## Priority Lanes

Protean supports **priority lanes** — two separate processing streams:

| Lane | Purpose | Priority Levels |
|------|---------|-----------------|
| **Primary** | Normal production traffic | NORMAL, HIGH, CRITICAL |
| **Backfill** | Bulk operations, migrations | BULK, LOW |

The server always drains the primary lane first. Backfill messages are
only processed when the primary lane is empty. This guarantees that
production traffic is never delayed by bulk operations.

## Configuration

Enable priority lanes in `domain.toml`:

```toml
[server]
priority_lanes = true
```

## The Import Script

```python
--8<-- "guides/getting-started/tutorial/ch19.py:import_script"
```

The `processing_priority(Priority.BULK)` context manager tags all
commands dispatched within it as bulk priority. These flow to the
backfill stream instead of the primary stream.

You can also set priority per command:

```python
domain.process(
    AddBook(title="...", author="...", price_amount=9.99),
    priority=Priority.BULK,
)
```

## Running the Import

Start the import in one terminal while the server processes both lanes:

```shell
# Terminal 1 — server (processes both lanes)
$ protean server --domain bookshelf

# Terminal 2 — run the bulk import
$ python import_vintage_press.py
Importing 50,000 books with BULK priority...
Progress: 10,000 / 50,000
Progress: 20,000 / 50,000
...

# Terminal 3 — production traffic continues normally
$ curl -X POST http://localhost:8000/orders ...   # instant response
```

## Monitoring the Import

Check the backfill lane progress:

```shell
$ protean subscriptions status --domain bookshelf
Subscription              Stream                    Lag (primary)  Lag (backfill)
BookCommandHandler        bookshelf::book:command   0              32,451
BookCatalogProjector      bookshelf::book           0              28,109
...
```

The primary lane stays at zero lag — production traffic is unaffected.
The backfill lane processes the import at its own pace.

## Priority Levels

| Level | Value | Use Case |
|-------|-------|----------|
| `BULK` | -100 | Data migrations, large imports |
| `LOW` | -50 | Background tasks, non-urgent updates |
| `NORMAL` | 0 | Standard production traffic (default) |
| `HIGH` | 50 | Time-sensitive operations |
| `CRITICAL` | 100 | System-critical operations |

## What We Built

- **Priority lanes** for isolating bulk operations from production
  traffic.
- A **bulk import script** using `processing_priority(Priority.BULK)`.
- Understanding of how the server prioritizes primary over backfill
  lanes.

Part IV is complete! The bookstore now has full production operations:
message tracing, dead-letter queue management, monitoring, and bulk
import support. In the next chapter, we will tackle advanced patterns
starting with process managers.

## Full Source

```python
--8<-- "guides/getting-started/tutorial/ch19.py:full"
```

## Next

[Chapter 20: Orchestrating Multi-Step Workflows →](20-process-managers.md)
