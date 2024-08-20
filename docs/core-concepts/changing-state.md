# Changing State

In DDD, changing the state of the system is a critical operation that is
carefully controlled and structured. This section outlines the principles and
practices that govern how state transitions occur within an application.

It is essential for understanding how to maintain the integrity and consistency
of your domain model while handling user-driven changes in a reliable and
scalable way.

## The Domain Model is protected

The Domain Model is not accessible by the external world.

One of the foundational principles in DDD is that the domain model —
representing the core business logic and rules of your application — is
protected from direct access by external systems or layers. This encapsulation
ensures that the domain model remains pure, focused on business logic, and
free from concerns about external interactions.

The domain model should only be interacted with via specific interfaces
designed to handle business operations, ensuring that all interactions with the
model are controlled and follow the defined business rules.

*In Protean, these "interfaces" are aggregate methods named in line with the
ubiquitous language.*

## Only the Application Layer talks to the Domain Model

The application layer acts as the intermediary between the domain model and the
rest of the system. It is the only layer that can directly invoke changes on
the domain model. This separation of concerns ensures that the domain logic is
only manipulated through well-defined use cases.

This design allows for better maintainability and flexibility because the
application layer changes at a different rate than the domain model. It also
supports testing the domain model in isolation and the ability to refactor
the domain logic to evolve independently from other system concerns.

## Application Layer encloses actions

The API layer often serves as the entry point for external requests. The API
layer captures user inputs or requests and invokes the appropriate actions
in the application layer.

By having the API layer delegate actions to the application layer, we maintain
a clear separation between external communication and internal processing.
This approach not only protects the domain model from direct exposure but also
allows the application to handle various concerns such as validation,
authorization, and orchestration of complex workflows before interacting with
the domain model.

There are two ways the external API layer can invoke the application layer:

### Use cases

Application services are a common pattern in DDD, serving as a facade for
business operations. When an API layer receives a request, it delegates the
operation to the appropriate application service, which then coordinates the
necessary actions to fulfill the request.

Application services enclose and encapsulate business use cases, that are
defined in the ubiquitous language. These use cases may or may not be reusable,
but every business use case has a 1-1 mapping with a use case in application
services.

This design also allows for better organization of business logic, as each
service is responsible for a specific set of related operations, reducing the
overall complexity of the application layer.

### Commands

In systems that implement CQRS and Event Sourcing architecture patterns, the
separation between command (write) and query (read) models is a key principle.
When a user interacts with the system, the API captures their intent as a
command — an explicit request to perform a specific operation — and submits it
to the domain.

By capturing intent as commands, the system can ensure that each operation is
processed consistently, with a clear audit trail of how the system's state
evolves over time.

This separation also allows for optimized handling of write operations, focusing on
modifying the state of the system, while queries are handled separately,
optimized for reading data. 

Each Command is processed by a halder method in a Command Handler element.

Once a command is submitted, it is processed by the command handler. Each
command handler method contains the logic necessary to interpret the command,
hydrate the relevant aggregate, and apply the appropriate changes to the domain
model.

Command handlers provide a clear and organized way to handle write operations.
By isolating command processing in dedicated handlers, the system remains
modular, with each handler focused on a specific aspect of the domain,
improving both maintainability and scalability.

## Application layer hydrates aggregates

The Application Layer is responsible for retrieving (a.k.a hydrating) an
aggregate from the persistence store (or an event store if using the Event
Sourcing pattern), and then persisting it.

When a command is processed, the application layer hydrates the aggregate and
then invokes methods on the up-to-date aggregate. 

## Aggregates mutate

Aggregates encapsulate business logic and ensure that all state transitions are
valid. When an aggregate receives input through a command, it evaluates the
request against its internal rules and invariants. If all conditions are met,
the aggregate mutates — changing its state accordingly.

In addition to mutating, aggregates can also raise events that represent
significant changes in the system. These events can be used to trigger other
processes or communicate state changes to external systems, leadig to richer,
complex workflows.

## Application layer persists mutated aggregates

After the aggregate has mutated, the changes need to be persisted to ensure
that the system's state is durable and consistent. Repositories save aggregates
back to the persistence store or event store.

Repositories not only persist the changes but also handle the publication of
events raised by the aggregate. These events are stored in the event store,
providing a detailed history of how the system's state has evolved over time.
