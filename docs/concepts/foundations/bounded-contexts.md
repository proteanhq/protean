# Bounded Contexts

A bounded context is a boundary within which a particular domain model is defined and applicable. Each bounded context has its own [ubiquitous language](./ubiquitous-language.md), its own aggregates, entities, value objects, and its own rules. The model inside one context does not need to be consistent with models in other contexts -- and attempting to force consistency across contexts is one of the most common sources of accidental complexity in software.

Without bounded contexts, a system grows into a Big Ball of Mud where every concept is entangled with every other concept. Bounded contexts are the strategic pattern that controls this complexity.

## Why Boundaries Exist

Different parts of a business have different vocabularies and different rules for the same real-world concepts. A "Customer" in a billing context has payment terms, invoices, and credit limits. A "Customer" in a support context has tickets, SLAs, and satisfaction scores. Forcing a single Customer model to serve both contexts creates a bloated, fragile class that satisfies neither context well and changes for reasons that have nothing to do with each other.

Bounded contexts let each part of the system model its own slice of reality without compromise. Each context captures exactly the concepts and rules it needs -- nothing more, nothing less.

## Characteristics of a Bounded Context

A well-defined bounded context has several distinguishing properties:

- **Its own ubiquitous language.** Terms are defined precisely within the context. The same word may carry different meaning in another context.
- **Its own domain model.** Aggregates, entities, and value objects are defined to serve the needs of this context specifically.
- **Its own persistence.** Ideally, each context has its own database or schema, preventing one context's data model from leaking into another.
- **Well-defined interfaces.** Communication with other contexts happens through explicit mechanisms -- domain events, APIs, or shared message schemas -- never through direct access to another context's internals.
- **Independent evolution.** Changes inside one context do not break others. Teams can develop, deploy, and scale contexts independently.

## Context Mapping

When two bounded contexts need to communicate, the relationship between them must be explicit. Common patterns for managing these relationships include:

- **Shared Kernel**: Two contexts share a small, jointly owned model. Changes require coordination between both teams. Use sparingly.
- **Customer-Supplier**: One context (supplier) provides data that another (customer) depends on. The supplier publishes; the customer consumes.
- **Anti-Corruption Layer**: A translation layer that prevents one context's model from leaking into another. The consuming context translates incoming data into its own language.
- **Published Language**: A well-defined schema (events, messages, APIs) that both contexts agree on. Neither context's internal model is exposed directly.

In Protean, cross-context communication is supported through domain events and [subscribers](../../guides/consume-state/subscribers.md) that act as anti-corruption layers, translating external messages into domain operations.

## How to Identify Boundaries

Recognizing where one context ends and another begins is a modeling skill that improves with practice. Three signals help:

- **Language divergence.** When the same word means different things to different people, a boundary likely exists between their contexts.
- **Organizational boundaries.** Different teams often correspond to different bounded contexts. Conway's Law suggests that system boundaries will mirror communication structures.
- **Rate-of-change differences.** Parts of the system that change for different reasons and at different rates belong in different contexts.

## Bounded Contexts and Protean

Each `Domain` instance in Protean can represent a bounded context. Events flow between domains via subscribers, and each domain maintains its own configuration, adapters, and domain elements independently.

For patterns on cross-context communication, see [Connecting Concepts Across Bounded Contexts](../../patterns/connect-concepts-across-domains.md) and [Consuming Events from Other Domains](../../patterns/consuming-events-from-other-domains.md).
