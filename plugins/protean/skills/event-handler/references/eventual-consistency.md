# Eventual Consistency

## What it means

When Aggregate A raises an event and Aggregate B reacts to it, there is a brief window where A has been updated but B has not yet. This is **eventual consistency**: both aggregates will be consistent, but not at the same instant.

## Guarantees in Protean

- Events are persisted with the source aggregate, in the same transaction
- Event handlers process events at least once
- In `"sync"` mode, events are processed immediately (for testing)
- In production, events are processed asynchronously

## Designing for eventual consistency

SKILL.md covers putting enough data in the event and making the receiving end safe to repeat. Two more points:

1. **Accept brief staleness**: UI might show slightly outdated data
2. **Use read models for queries**: Projections can combine data from multiple aggregates
