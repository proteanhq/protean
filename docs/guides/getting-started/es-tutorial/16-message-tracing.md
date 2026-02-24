# Chapter 16: Following the Trail — Message Tracing

An auditor asks: "Show me every system action triggered by deposit
DEP-9921." This deposit was over $10,000 — it triggered a compliance
alert, which generated an investigation, which led to an account hold.

To answer this, we need to trace the complete **causal chain** from the
original command through every downstream event and reaction.

## Correlation and Causation IDs

Every message in Protean carries two tracing identifiers:

- **Correlation ID** — shared by all messages in a causal chain. If
  you set it on the initial command, every event raised by that command,
  every command issued by event handlers reacting to those events, and
  so on, all share the same correlation ID.
- **Causation ID** — points to the message that directly caused this
  one, creating a parent-child relationship.

```
correlation_id: "audit-trail-dep-9921" (same for all)

MakeDeposit (causation_id: null)
  └── DepositMade (causation_id: MakeDeposit.id)
        ├── AccountSummary updated (causation_id: DepositMade.id)
        └── ComplianceAlert created (causation_id: DepositMade.id)
              └── AccountHoldPlaced (causation_id: ComplianceAlert.id)
```

## Setting the Correlation ID

Set it explicitly when processing a command:

```python
domain.process(
    MakeDeposit(
        account_id="acc-7742",
        amount=15_000.00,
        reference="DEP-9921",
    ),
    correlation_id="audit-trail-dep-9921",
)
```

If you do not set a correlation ID, Protean generates one automatically.

## Tracing with the CLI

The `protean events trace` command visualizes the causal tree:

```shell
$ protean events trace audit-trail-dep-9921 --domain=fidelis
CMD MakeDeposit (...) @ 2025-06-15 10:30:00
├── EVT DepositMade (...) @ 2025-06-15 10:30:00
│   ├── EVT AccountFactEvent (...) @ 2025-06-15 10:30:00
│   └── CMD CreateComplianceAlert (...) @ 2025-06-15 10:30:01
│       └── EVT ComplianceAlertCreated (...) @ 2025-06-15 10:30:01
│           └── CMD PlaceAccountHold (...) @ 2025-06-15 10:30:02
│               └── EVT AccountHoldPlaced (...) @ 2025-06-15 10:30:02

Causation tree: 7 message(s) for correlation 'audit-trail-dep-9921'
```

For a flat, chronological view:

```shell
$ protean events trace audit-trail-dep-9921 --flat --domain=fidelis
```

## Tracing Events with Metadata

Add `--trace` to event CLI commands to see correlation and causation
IDs:

```shell
$ protean events read "fidelis::account-acc-7742" --trace --domain=fidelis
 Pos  Type          Time                 Correlation ID     Causation ID
 15   DepositMade   2025-06-15 10:30     audit-trail-d...   fidelis::ac...
 ...
```

```shell
$ protean events search --type=DepositMade --trace --domain=fidelis
```

## Programmatic Tracing

Use the causation chain API for programmatic access:

```python
with domain.domain_context():
    event_store = domain.event_store

    # Walk UP from a message to the root command
    chain = event_store.trace_causation(message_id)

    # Walk DOWN from a message to all its effects
    effects = event_store.trace_effects(message_id, recursive=True)

    # Build the full tree for a correlation ID
    tree = event_store.build_causation_tree("audit-trail-dep-9921")
```

The `CausationNode` tree structure contains:

- `message_id` — the message's unique identifier
- `message_type` — the event or command type string
- `stream` — the stream the message was written to
- `timestamp` — when it was created
- `children` — list of `CausationNode` children

## Automatic Propagation

Correlation IDs propagate automatically through the system:

1. You set `correlation_id` on `domain.process()`
2. The command handler runs — events raised by the aggregate inherit
   the correlation ID
3. Event handlers receive events with the correlation ID
4. When a handler issues a new command via `domain.process()`, the
   correlation ID is forwarded automatically
5. The chain continues through the entire causal flow

You never need to manually pass correlation IDs between handlers.

## What We Built

- **Correlation IDs** that tie together entire causal chains.
- **Causation IDs** that establish parent-child relationships.
- **`protean events trace`** CLI for tree and flat visualization.
- **`--trace`** flag on event CLI commands.
- **Programmatic API** with `trace_causation()`, `trace_effects()`,
  and `build_causation_tree()`.
- **Automatic propagation** through handlers and commands.

Message tracing is essential for debugging, auditing, and understanding
the behavior of event-driven systems. Next, we face a production
incident — a handler bug that fills the dead-letter queue.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch16.py:full"
```

## Next

[Chapter 17: When Things Go Wrong — Dead Letter Queues →](17-dead-letter-queues.md)
