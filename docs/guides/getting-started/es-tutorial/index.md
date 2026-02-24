# Tutorial: Building Fidelis

In this tutorial we will build **Fidelis**, a digital banking ledger
platform with Protean's Event Sourcing capabilities. By the end, we will
have a production-grade system with immutable audit trails, temporal
queries, schema evolution, cross-domain integrations, and full operational
tooling.

## Why Event Sourcing for Banking?

Every financial transaction is an **immutable fact**. A deposit happened.
A withdrawal happened. You cannot delete or overwrite a transaction — you
record a new one. Event Sourcing captures this reality directly: instead
of storing the current balance, we store every event that changed it and
derive the balance by replaying the history.

This gives us:

- **Complete audit trails** — every state change is recorded forever
- **Temporal queries** — "what was the balance on March 15th?"
- **Schema evolution** — new regulations add fields without rewriting history
- **Debugging superpowers** — trace every action back to its cause

## What We Will Build

- An **Account** ledger with deposits, withdrawals, and business rules
- A **Transfer** system that coordinates funds between accounts
- **Projections** for dashboards and regulatory reports
- **Event handlers** for compliance alerts and notifications
- An **external payment gateway** integration
- **Production tooling** — monitoring, dead letter queues, migrations

## How the Tutorial Is Organized

The tutorial is divided into five parts. Each chapter builds on the
previous one, growing the Fidelis platform step by step.

| Part | Chapters | What We Build |
|------|----------|---------------|
| **I. Building the Foundation** | 1–5 | Event-sourced aggregates, commands, invariants, and tests |
| **II. Growing the Platform** | 6–10 | Projections, event handlers, async processing, transfers, and entities |
| **III. Evolution and Adaptation** | 11–14 | Event upcasting, snapshots, temporal queries, and external integrations |
| **IV. Production Operations** | 15–19 | Fact events, message tracing, DLQ management, monitoring, and migrations |
| **V. Mastery** | 20–22 | Projection rebuilding, event store exploration, and the full architecture |

!!! tip "Cumulative Codebase"
    Each chapter builds on the previous one. The code you write in Chapter 1
    grows throughout the tutorial into a complete platform. Follow along
    in order for the best experience.

!!! info "Which pathway does this tutorial follow?"
    This tutorial follows the **Event Sourcing** path — aggregates derive
    their state from events rather than storing snapshots in a database.
    If you are looking for the standard CQRS approach, see the
    [Bookshelf tutorial](../tutorial/index.md).

## Prerequisites

- **Python 3.11+**
- **Protean installed** — see [Installation](../installation.md)
- **Familiarity with the [Bookshelf tutorial](../tutorial/index.md)** —
  this tutorial assumes you understand aggregates, fields, commands, and
  events. We build on those concepts with Event Sourcing specifics.
- **Docker** (from Chapter 8 onward) — for Redis and other services

## Ready?

Start with **[Chapter 1: The Faithful Ledger](01-the-faithful-ledger.md)**
and build your banking platform from the ground up.
