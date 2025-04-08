# Adding Rules and Behavior

Domain-Driven Design emphasizes the importance of building a rich domain model that accurately captures business rules and behaviors. Protean provides a comprehensive set of mechanisms to define and enforce these rules in your domain model.

## Core Concepts in Domain Behavior

### Validations

Validations ensure that data meets basic requirements before it can be processed. In Protean, validations can be applied at multiple levels:

- **Field-level restrictions** - Define type constraints, required fields, uniqueness
- **Built-in validators** - Leverage pre-defined validators for common validation patterns
- **Custom validators** - Create domain-specific validation logic

[Learn more about validations →](validations.md)

### Invariants

Invariants are business rules that must always hold true within your domain model. They preserve the consistency and integrity of your domain objects:

- **Always valid** - Invariants are conditions that must hold true at all times
- **Domain-driven** - Invariants stem from business rules and policies 
- **Immediate validation** - Triggered automatically during initialization and state changes

[Learn more about invariants →](invariants.md)

### Aggregate Mutation

Aggregates encapsulate the state and behavior of your domain. Mutating their state is how you implement business operations:

- **State change methods** - Well-defined methods for modifying aggregate state
- **Invariant enforcement** - All state changes are validated against defined invariants
- **Explicit behavior** - Business operations are expressed as meaningful methods

[Learn more about aggregate mutation →](aggregate-mutation.md)

### Raising Events

Domain events record significant state changes and enable communication between different parts of your system:

- **Delta events** - Generated when aggregates mutate to record state changes
- **Entity events** - Any entity in an aggregate cluster can raise events
- **Event dispatching** - Events are automatically dispatched or can be manually published

[Learn more about raising events →](raising-events.md)

### Domain Services

Domain services encapsulate business logic that doesn't naturally fit within any single aggregate:

- **Stateless operations** - Pure functions that operate on multiple aggregates
- **Complex workflows** - Coordinate operations that span multiple aggregates
- **Business rules** - Enforce constraints that involve multiple objects

[Learn more about domain services →](domain-services.md)

## Best Practices

When implementing domain behavior in Protean:

1. **Keep aggregates focused** - Aggregates should encapsulate only their own state and behavior
2. **Make business rules explicit** - Use invariants to clearly express domain constraints
3. **Use domain events for cross-aggregate communication** - Avoid direct dependencies between aggregates
4. **Consider domain services for complex operations** - When logic spans multiple aggregates
5. **Validate early and often** - Apply appropriate validation at all levels