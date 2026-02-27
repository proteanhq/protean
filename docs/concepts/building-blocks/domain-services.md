# Domain Services

Domain services encapsulate domain logic that doesn't naturally fit within an
[aggregate](./aggregates.md), [entity](./entities.md) or
[value object](./value-objects.md). Specifically, they model business
operations that require **two or more aggregates** as input — operations where
the logic genuinely spans aggregate boundaries.

## The Problem

Consider placing an order that requires confirming the order and reserving
inventory. Where does this logic live?

- **In the `Order` aggregate?** Then `Order` needs to know about `Inventory`,
  which violates aggregate boundaries and creates tight coupling.
- **In the command handler?** Then business rules (like "sufficient stock must
  be available") leak into the application layer, bypassing the domain model.
- **In a domain service?** The service receives both aggregates, validates
  cross-aggregate invariants, and mutates both — keeping the business logic in
  the domain layer where it belongs.

Domain services solve the specific problem of **cross-aggregate business logic
that doesn't belong to any single aggregate**.

## Facts

### Domain Services encapsulate cross-aggregate logic. { data-toc-label="Encapsulate Domain Logic" }
Domain services contain business logic that spans two or more aggregates.
They provide a place for operations that can't be naturally assigned
to a single aggregate.

### Domain Services enforce cross-aggregate business rules. { data-toc-label="Enforce Business Rules" }
Domain services can enforce business rules that apply to operations spanning
multiple aggregates, using `@invariant.pre` and `@invariant.post` decorators.
They ensure that the rules are consistently applied across the domain model.

### Domain Services should follow Ubiquitous Language. { data-toc-label="Service Names" }
The names of domain services should clearly indicate their purpose. A
meaningful name helps to communicate the service's role within the domain model.

### Domain Services coordinate operations. { data-toc-label="Handle Complexity" }
Domain services often coordinate complex operations that involve multiple
aggregates. They orchestrate the interactions between these aggregates to
achieve a specific business outcome.

### Domain Services are stateless between calls. { data-toc-label="Stateless" }
Domain services do not persist their own state or maintain data between
invocations. While they may hold references to aggregates during execution
(as instance attributes), they do not retain state after the operation
completes.

### Domain Services define clear interfaces. { data-toc-label="Expose Interfaces" }
Domain services define clear and explicit interfaces, named to reflect the
business functionality. These interfaces describe the operations that the
service provides, making the service's role and capabilities clear.

### Domain Services are invoked by application-layer elements. { data-toc-label="Invoked by Handlers" }
Services in the application layer — [command handlers](./command-handlers.md),
[application services](./application-services.md), or
[event handlers](./event-handlers.md) — invoke domain services to perform
domain operations. The handler is responsible for loading aggregates from
repositories, passing them to the domain service, and persisting the result.

## When NOT to Use Domain Services

Domain services are a specialized tool for cross-aggregate logic. Do not use
them when:

- **The logic involves only one aggregate.** If the business rule can be
  expressed as an invariant or method on a single aggregate, it belongs there.
  Domain services require `part_of` to list at least two aggregates.
- **You need orchestration without business rules.** If you're just loading an
  aggregate, calling a method, and saving — that's what command handlers and
  application services are for.
- **You want a reusable utility function.** Domain services model business
  operations from the ubiquitous language, not technical utilities.

---

## Next steps

For practical details on defining and using domain services in Protean, see the guide:

- [Domain Services](../../guides/domain-behavior/domain-services.md) — Defining domain services, three implementation flavors, invariants, and a full example.

For design guidance:

- [Thin Handlers, Rich Domain](../../patterns/thin-handlers-rich-domain.md) — Balancing logic between domain services, aggregates, and handlers.
- [Application Service vs Command Handler](../../patterns/application-service-vs-command-handler.md) — Choosing the right orchestration layer.
