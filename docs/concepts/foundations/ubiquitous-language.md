# Ubiquitous Language

A ubiquitous language is a shared vocabulary developed collaboratively by domain experts and developers, used consistently in code, conversations, documentation, and tests. It is the linguistic backbone of Domain-Driven Design -- the mechanism that ensures everyone involved in building a system means the same thing when they use the same words.

Miscommunication between business and engineering is the root cause of software that solves the wrong problem. A shared language eliminates the translation layer between "what the business says" and "what the code does." When domain experts describe a process and developers can point to the exact class, method, or event that implements it, the gap between intent and implementation disappears.

The language is not invented by developers. It is discovered through conversation with domain experts and refined through modeling.

## The Language Lives in Code

Class names, method names, field names, event names, and command names should all use terms from the ubiquitous language. When a domain expert says "the order is placed," the code should have a `place()` method on an `Order` aggregate that raises an `OrderPlaced` event.

If developers cannot name something in the language, the model is incomplete. Naming difficulties are not a code problem -- they are a signal to go back to domain experts and deepen understanding of the concept. Conversely, if the code contains abstractions that have no counterpart in domain conversations, those abstractions are suspect. They may be technical conveniences that obscure the domain rather than clarify it.

The ubiquitous language is not limited to nouns. Verbs (place, ship, cancel), adjectives (pending, active, expired), and even phrases (back-ordered, out of stock) all belong in the language and should appear in the code exactly as the domain describes them.

## Boundaries Matter

A ubiquitous language is valid within a [bounded context](./bounded-contexts.md). The same word can mean different things in different contexts. "Account" in a billing context has payment terms and invoices. "Account" in an identity context has credentials and permissions. These are not the same concept -- they share a name but have different structures, behaviors, and rules.

Do not try to create one universal vocabulary for the entire organization. Each bounded context has its own language, and translation happens at context boundaries through well-defined interfaces.

## The Language Evolves

As understanding deepens, terms are refined, renamed, split, or merged. A concept that starts as "Shipment" might later be distinguished into "Dispatch" and "Delivery" as the team learns more about the logistics domain.

When the language evolves, the code must evolve with it. Refactoring code to match updated language is not cosmetic -- it is an essential practice that keeps the [analysis model](./analysis-model.md) aligned with the domain. Stale names in code are not just technical debt; they are a source of ongoing miscommunication that compounds over time.

## Further Reading

- [Bounded Contexts](./bounded-contexts.md) -- how language scope is defined
- [Analysis Model](./analysis-model.md) -- how the language becomes a model
- [Glossary](../../glossary.md) -- Protean-specific terms and definitions
