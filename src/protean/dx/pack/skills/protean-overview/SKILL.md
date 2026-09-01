---
name: protean-overview
description: Orient a coding agent to a Protean domain before it writes code. Explains the core building blocks (aggregates, entities, value objects, events, commands, handlers) and the rules that hold across them. Use when starting work in a Protean project, when unsure which element to reach for, or when the user asks "how is a Protean domain put together".
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: orientation
---

# Protean overview

<!-- dx-pack-seed: minimal seed skill; the full teaching corpus lands with the
developer-experience epic. -->

Protean is a domain-driven framework. A domain is a registry of elements you
declare with decorators on a `Domain` object.

## Building blocks

- **Aggregate** (`@domain.aggregate`): the root entity of a consistency
  boundary. It owns its child entities and value objects and enforces the
  invariants that must hold whenever it changes.
- **Entity** (`@domain.entity`): an object with identity that lives inside an
  aggregate and is reached through it.
- **Value object** (`@domain.value_object`): an immutable value with no
  identity, compared by its attributes.
- **Event** (`@domain.event`): a record of something that happened. An
  aggregate raises one with `self.raise_(...)`.
- **Command** (`@domain.command`): an intent to change state, processed by a
  command handler.
- **Handlers** (`@domain.command_handler`, `@domain.event_handler`): load an
  aggregate, invoke a method on it, and persist the result.

## Rules that hold across elements

- One aggregate changes per transaction. Consistency between aggregates is
  eventual, carried by events.
- Business rules live in the domain layer: field constraints, value-object
  invariants, and aggregate invariants.
- An aggregate has a single identity. Composite keys have no place in the model.
