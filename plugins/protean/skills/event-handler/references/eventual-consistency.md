# Eventual Consistency

## What it means

When Aggregate A raises an event and Aggregate B reacts to it, there is a brief window where A has been updated but B has not yet. This is **eventual consistency** — both aggregates will be consistent, but not at the same instant.

## Why it matters

- **Strong consistency** (both in one transaction) violates aggregate boundaries
- **Eventual consistency** (separate transactions) preserves aggregate independence
- The trade-off: briefly stale data vs clean architecture

## Guarantees in Protean

- Events are persisted with the source aggregate (atomic)
- Event handlers process events at least once
- Each handler runs in its own UnitOfWork (separate transaction)
- In `"sync"` mode, events are processed immediately (for testing)
- In production, events are processed asynchronously

## Designing for eventual consistency

1. **Include enough data in events** — The handler should not need to load the source aggregate
2. **Make handlers idempotent** — Processing the same event twice should produce the same result
3. **Accept brief staleness** — UI might show slightly outdated data
4. **Use read models for queries** — Projections can combine data from multiple aggregates
