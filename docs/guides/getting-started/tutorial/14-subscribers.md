# Chapter 14: Connecting to the Outside World — Subscribers

Bookshelf has partnered with a book distributor — **BookSupply** — that
sends webhook notifications when new books become available or when
stock is replenished. These messages arrive on a Redis stream from an
external system. We need to consume them and translate them into our
domain language.

## Subscribers vs. Event Handlers

| | Event Handlers | Subscribers |
|---|---------------|-------------|
| **Listens to** | Internal domain events (typed) | External broker messages (raw dicts) |
| **Input** | Typed event objects | Raw `dict` payloads |
| **Purpose** | React to domain state changes | Anti-corruption layer for external data |
| **Registration** | `part_of=Aggregate` | `stream="stream_name"` |

Event handlers trust the data because it comes from our own aggregates.
Subscribers do **not** trust the data — they validate, translate, and
map it into domain operations.

## Defining the Subscriber

```python
--8<-- "guides/getting-started/tutorial/ch14.py:subscriber"
```

The subscriber listens to the `"book_supply"` stream. When a message
arrives, `__call__` receives the raw dict payload. We inspect the
`event_type` field and dispatch to the appropriate domain command.

## The RestockInventory Command

We need a new command and handler for restocking:

```python
--8<-- "guides/getting-started/tutorial/ch14.py:restock_command"
```

```python
--8<-- "guides/getting-started/tutorial/ch14.py:restock_handler"
```

## How It Works

```
External System           Protean
(BookSupply)              (Bookshelf)
     │                        │
     │ webhook POST           │
     │───────────────────►    │
     │                  Redis Stream
     │                  "book_supply"
     │                        │
     │                  ┌─────▼──────┐
     │                  │ Subscriber │
     │                  │ (ACL)      │
     │                  └─────┬──────┘
     │                        │ domain.process(AddBook)
     │                  ┌─────▼──────┐
     │                  │  Command   │
     │                  │  Handler   │
     │                  └────────────┘
```

The subscriber acts as an **anti-corruption layer** (ACL) — it prevents
external data formats from leaking into the domain. If BookSupply
changes their payload format, only the subscriber needs to change.

## Testing the Subscriber

```python
--8<-- "guides/getting-started/tutorial/ch14.py:tests"
```

## What We Built

- A **`BookSupplyWebhookSubscriber`** that consumes messages from an
  external system.
- A **`RestockInventory`** command and handler for replenishing stock.
- An **anti-corruption layer** that translates external data into
  domain operations.

In the next chapter, we will enable fact events so the marketing team
can get complete state snapshots for their analytics dashboard.

## Full Source

```python
--8<-- "guides/getting-started/tutorial/ch14.py:full"
```

## Next

[Chapter 15: Fact Events and the Reporting Pipeline →](15-fact-events.md)
