# Tutorial: Building Bookshelf

In this tutorial we will build **Bookshelf**, a small but complete online
bookstore with Protean. By the end, we will have a working application with
aggregates, value objects, commands, events, projections, a real database,
and tests.

## What We Will Build

- A **Book** catalog with rich fields and value objects
- An **Order** system with child entities and business rules
- An **Inventory** tracker that reacts to events automatically
- **Commands** that express intent and **events** that record what happened
- A **BookCatalog** projection for fast browsing queries
- Real **database persistence** with PostgreSQL

## How the Tutorial Is Organized

The tutorial is divided into four parts. Each chapter builds on the
previous one, growing the Bookshelf application step by step.

| Part | Chapters | What We Build |
|------|----------|---------------|
| **I. Building the Domain** | 1–4 | Aggregates, fields, value objects, entities, and business rules |
| **II. Making It Event-Driven** | 5–6 | Commands, command handlers, domain events, and event handlers |
| **III. Read Models & Persistence** | 7–8 | Projections, projectors, and a real PostgreSQL database |
| **IV. Testing** | 9–10 | Testing strategies and next steps |

!!! tip "Cumulative Codebase"
    Each chapter builds on the previous one. The code you write in Chapter 1
    grows throughout the tutorial into a complete application. Follow along
    in order for the best experience.

## Prerequisites

- **Python 3.11+**
- **Protean installed** — see [Installation](../installation.md)
- **Familiarity with the [Quickstart](../quickstart.md)** — the tutorial
  assumes you've seen a basic Protean domain

## Ready?

Start with **[Chapter 1: Your First Aggregate](01-your-first-aggregate.md)**
and build your bookstore from the ground up.
