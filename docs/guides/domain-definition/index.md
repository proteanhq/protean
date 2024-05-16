# Define Domain Concepts

Domain-driven Design (DDD) is all about identifying and naming domain concepts
and translating them as closely as possible - terminology, structure, and
behavior - in code. Protean supports the tactical patterns outlined by DDD
to mirror the domain model in [code model](../../glossary.md#code-model).

In this section, we will talk about the foundational structures that make up
the domain model. In the next, we will explore how to define behavior and
set up invariants (business rules) that bring the Domain model to life.

## Domain Layer

One of the most important building block of a domain model is the Aggregate.
Aggregates are fundamental, coarse-grained building blocks of a domain model.
They are conceptual wholes - they enclose all behaviors and data of a distinct
domain concept. Aggregates are often composed of one or more Aggregate
Elements, that work together to codify the concept.
<!-- FIXME Fix link to Aggregate elements in above paragraph -->

In a sense, Aggregates act as **Root Entities** - they manage the lifecycle
of all [Entities](../../glossary.md#entity) and 
[Value Objects](../../glossary.md#value-object) enclosed within them.
All elements enclosed within an Aggregate are only accessible through the
Aggregate itself - it acts as a consistency boundary and protects data
sanctity within the cluster.

Read more about Aggregates in Building Blocks.
<!-- FIXME Fix link to Aggregate Building block page -->

Entities
Value Objects
Domain Services
Events

## Application Layer

Application Services
Subscribers

## Infrastructure

### Persistence

Repositories
Models
Read Models
Caches

### Communication

Brokers

## Architecture Patterns

CQRS
Event Sourcing

## Data Container Elements
