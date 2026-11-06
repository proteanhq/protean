# Domain Services

Domain services encapsulate domain logic that doesn't naturally fit within an
[aggregate](./aggregates.md), [entity](./entities.md) or [value
object](./value-objects.md). Specifically, domain services model business
operations that take **two or more aggregates** as input. In these operations,
the logic genuinely spans aggregate boundaries.

## What problem do domain services solve?

Consider placing an order that requires confirming the order and reserving
inventory. Which element should hold this logic?

- **In the `Order` aggregate?** Then `Order` needs to know about `Inventory`,
  which violates aggregate boundaries and creates tight coupling.
- **In the command handler?** Then the application layer contains business
  rules (like "sufficient stock must be available"), and the domain model does
  not enforce them.
- **In a domain service?** The service receives both aggregates, validates
  cross-aggregate invariants, and confirms the order. The business logic
  remains in the domain layer. An event handler then reacts to the order's
  event and sends the inventory a command to reserve stock, in a separate
  transaction.

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
Domain services often coordinate complex operations that take multiple
aggregates as input. They orchestrate the interactions between these aggregates
to achieve a specific business outcome.

### Domain Services are stateless between calls. { data-toc-label="Stateless" }
Domain services do not persist their own state or maintain data between
invocations. Domain services may hold references to aggregates as instance
attributes during execution. They retain no state after the operation
completes.

### Domain Services define clear interfaces. { data-toc-label="Expose Interfaces" }
Domain services define clear and explicit interfaces, named to reflect the
business functionality. These interfaces describe the operations that the
service provides, making the service's role and capabilities clear.

### Domain Services are invoked by application-layer elements. { data-toc-label="Invoked by Handlers" }
Elements in the application layer invoke domain services to perform domain
operations: [command handlers](./command-handlers.md), [application
services](./application-services.md), or [event handlers](./event-handlers.md).
The handler is responsible for loading aggregates from repositories, passing
them to the domain service, and persisting the result.

## When NOT to Use Domain Services

Domain services are a specialized tool for cross-aggregate logic. Do not use
them when:

- **The logic needs only one aggregate**: If you can express the business rule
  as an invariant or method on a single aggregate, put the rule on that
  aggregate. Domain services require `part_of` to list at least two aggregates.
- **You need orchestration without business rules**: If you only load an
  aggregate, call a method, and save it, use command handlers and application
  services for that work.
- **You want a reusable utility function**: Domain services model business
  operations from the ubiquitous language, not technical utilities.

---

## Read more about domain services

For practical details on defining and using domain services in Protean, see the guide:

- [Domain Services](../../guides/domain-behavior/domain-services.md): Defining domain services, three implementation flavors, invariants, and a full example.

For design guidance:

- [Thin Handlers, Rich Domain](../../patterns/thin-handlers-rich-domain.md): Balancing logic between domain services, aggregates, and handlers.
- [Application Service vs Command Handler](../../patterns/application-service-vs-command-handler.md): Choosing the right orchestration layer.
