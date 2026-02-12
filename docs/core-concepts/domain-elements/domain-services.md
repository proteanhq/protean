# Domain Services

Domain services encapsulate domain logic that doesn't naturally fit within an
[aggregate](./aggregates.md), [entity](./entities.md) or
[value object](./value-objects.md). Domain services are used to model
operations and behaviors that involve multiple entities.

Domain services help to maintain a clean and organized domain model by
offloading operations that don't belong to any specific entity.

## Facts

### Domain Services encapsulate domain logic. { data-toc-label="Encapsulate Domain Logic" }
Domain services contain business logic that spans multiple entities or value
objects. They provide a place for operations that can't be naturally assigned
to a single entity.

### Domain Services enforce business rules. { data-toc-label="Enforce Business Rules" }
Domain services can enforce business rules that apply to operations spanning
multiple entities. They ensure that the rules are consistently applied across
the domain model.

### Domain Services should follow Ubiquitous Language. { data-toc-label="Service Names" }
The names of domain services should clearly indicate their purpose. A
meaningful name helps to communicate the service's role within the domain model.

### Domain Services coordinate operations. { data-toc-label="Handle Complexity" }
Domain services often coordinate complex operations that involve multiple
entities or value objects. They orchestrate the interactions between these
objects to achieve a specific outcome.

### Domain Services are stateless. { data-toc-label="Stateless" }
Domain services typically do not hold state. They operate on data provided to
them and persist or return results without maintaining internal state between
calls.

### Domain Services define clear interfaces. { data-toc-label="Expose Interfaces" }
Domain services define clear and explicit interfaces, named to reflect the
business functionality. These interfaces describe the operations that the
service provides, making the service's role and capabilities clear.

### Domain Services are invoked by application services. { data-toc-label="Used by Application Services" }
Services in the application layer, like
[application services](./application-services.md),
[command handlers](./command-handlers.md), or
[event handlers](./event-handlers.md), invoke domain services to perform
domain operations.
