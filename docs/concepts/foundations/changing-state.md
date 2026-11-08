# Changing State

In DDD, changing the state of the system is a critical operation that is
carefully controlled and structured. This section outlines the principles and
practices that govern how state transitions occur within an application.

You need them to keep the integrity and consistency of your domain model while
your application processes user-driven changes reliably and at scale.

## The Domain Model is protected

The Domain Model is not accessible by the external world.

The domain model represents the core business logic and rules of your
application. One of the foundational principles in DDD is that the domain model
is protected from direct access by external systems or layers. Because of this
encapsulation, the domain model stays pure, focused on business logic, and free
from concerns about external interactions.

Code outside the domain model should call it only through specific interfaces
built for business operations. That way, every call into the model is
controlled and follows the defined business rules.

*In Protean, these "interfaces" are aggregate methods named in line with the
ubiquitous language.*

## Only the Application Layer talks to the Domain Model

The application layer acts as the intermediary between the domain model and the
rest of the system. It is the only layer that can directly invoke changes on
the domain model. This separation of concerns means that the application layer
invokes the domain logic only through well-defined use cases.

The application layer changes at a different rate than the domain model, so
keeping the two apart makes your application easier to maintain and more
flexible. The separation also lets you test the domain model in isolation and
refactor the domain logic so that it evolves independently from other
system concerns.

## Application Layer encloses actions

The API layer often serves as the entry point for external requests. The API
layer captures user inputs or requests and invokes the appropriate actions
in the application layer.

By having the API layer delegate actions to the application layer, we maintain
a clear separation between external communication and internal processing.
With this delegation, external code cannot reach the domain model directly. The
application layer can also run validation, check authorization, and orchestrate
complex workflows before it calls the domain model.

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

Each application service is responsible for a specific set of related
operations. With this split, business logic is better organized and the
application layer is less complex overall.

### Commands

In systems that implement CQRS and Event Sourcing architecture patterns, the
separation between command (write) and query (read) models is a key principle.
When a user interacts with the system, the API captures their intent as a
command (an explicit request to perform a specific operation) and submits it to
the domain.

By capturing intent as commands, the system can ensure that each operation is
processed consistently, with a clear audit trail of how the system's state
evolves over time.

With this separation, the system can optimize write operations for changing its
state, while it processes queries separately and optimizes them for
reading data.

Each Command is processed by a handler method in a Command Handler element.

Once a command is submitted, it is processed by the command handler. Each
command handler method contains the logic necessary to interpret the command,
hydrate the relevant aggregate, and apply the appropriate changes to the domain
model.

Command handlers provide a clear and organized way to handle write operations.
By isolating command processing in dedicated handlers, the system remains
modular, with each handler focused on a specific aspect of the domain,
improving both maintainability and scalability.

## Application layer hydrates aggregates

The application layer retrieves (a.k.a hydrates) an aggregate from the
persistence store, and then persists it. If you use the Event Sourcing pattern,
the application layer uses an event store in place of the persistence store.

When a command is processed, the application layer hydrates the aggregate and
then invokes methods on the up-to-date aggregate.

## Aggregates mutate

Aggregates encapsulate business logic and ensure that all state transitions are
valid. When an aggregate receives input through a command, it evaluates the
request against its internal rules and invariants. If all conditions are met,
the aggregate mutates, changing its state accordingly.

In addition to mutating, aggregates can also raise events that represent
significant changes in the system. These events can be used to trigger other
processes or communicate state changes to external systems, leading to richer,
complex workflows.

## Application layer persists mutated aggregates

After the aggregate has mutated, the changes need to be persisted to ensure
that the system's state is durable and consistent. Repositories save aggregates
back to the persistence store or event store.

Repositories not only persist the changes but also handle the publication of
events raised by the aggregate. These events are stored in the event store,
providing a detailed history of how the system's state has evolved over time.
