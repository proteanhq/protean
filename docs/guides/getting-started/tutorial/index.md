# Tutorial: Building Bookshelf

In this tutorial we will build **Bookshelf**, a complete online bookstore
with Protean. By the end, we will have a production-ready application with
aggregates, value objects, commands, events, projections, a FastAPI web
layer, async background processing, external integrations, operational
tooling, and tests.

## What We Will Build

- A **Book** catalog with rich fields and value objects
- An **Order** system with child entities and business rules
- An **Inventory** tracker that reacts to events automatically
- **Commands** that express intent and **events** that record what happened
- A **BookCatalog** projection for fast browsing queries
- Real **database persistence** with PostgreSQL
- A proper **project structure** with auto-discovery
- A **FastAPI** web layer exposing commands and projections
- **Async processing** with the Protean server and Redis
- **Domain services** for cross-aggregate business logic
- **External integrations** via subscribers
- **Production operations** — monitoring, tracing, dead-letter queues,
  and bulk imports

## How the Tutorial Is Organized

The tutorial is divided into five parts. Each chapter builds on the
previous one, growing the Bookshelf application step by step.

| Part | Chapters | What We Build |
|------|----------|---------------|
| **I. Building the Domain** | 1–4 | Aggregates, fields, value objects, entities, and business rules |
| **II. Making It Real** | 5–11 | Commands, events, projections, a real database, project structure, API endpoints, and tests |
| **III. Growing the System** | 12–15 | Async processing, domain services, external integrations, and fact events |
| **IV. Production Operations** | 16–19 | Message tracing, dead-letter queues, monitoring, and bulk imports |
| **V. System Mastery** | 20–22 | Process managers, advanced queries, and the complete architecture |

!!! tip "Cumulative Codebase"
    Each chapter builds on the previous one. The code you write in Chapter 1
    grows throughout the tutorial into a complete application. Follow along
    in order for the best experience.

!!! info "Which pathway does this tutorial follow?"
    This tutorial covers **DDD foundations** (Chapters 1–4) that apply
    regardless of your chosen architecture, then introduces **CQRS patterns**
    (Chapters 5–7) with Commands, Command Handlers, and Projections. If
    you're using the pure **DDD** approach with Application Services instead,
    the domain modeling chapters (1–4) still apply directly — see the
    [DDD Pathway](../../pathways/ddd.md) for that reading order.

## Prerequisites

- **Python 3.11+**
- **Protean installed** — see [Installation](../installation.md)
- **Familiarity with [Hello, Protean!](../hello.md)** — the tutorial
  assumes you've seen a basic Protean domain (the
  [Quickstart](../quickstart.md) is also recommended)
- **Docker** (from Chapter 8 onward) — for PostgreSQL, Redis, and other
  services

## Ready?

Start with **[Chapter 1: Your First Aggregate](01-your-first-aggregate.md)**
and build your bookstore from the ground up.
