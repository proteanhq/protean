# Events

### Events allows different components to communicate with each other.

Within a domain or across, events can be used as a mechanism to implement
eventual consistency, in the same bounded context or across. This promotes
loose coupling by decoupling the producer (e.g., an aggregate that raises
an event) from the consumers (e.g., various components that handle the
event).

Such a design eliminates the need for two-phase commits (global
transactions) across bounded contexts, optimizing performance at the level
of each transaction.

### Events act as API contracts.

Events define a clear and consistent structure for data that is shared
between different components of the system. This promotes system-wide
interoperability and integration between components.

### Events help preserve context boundaries.

Events propagate information across bounded contexts, thus helping to
sync changes throughout the application domain. This allows each domain
to be modeled in the architecture pattern that is most appropriate for its
use case.

- Events should be named in past tense, because we observe domain events _after
the fact_. `StockDepleted` is a better choice than the imperative
`DepleteStock` as an event name.
- An event is associated with an aggregate or a stream, specified with
`part_of` or `stream` parameters to the decorator, as above. We will
dive deeper into these parameters in the Processing Events section.
<!-- FIXME Add link to events processing section -->
- Events are essentially Data Transfer Objects (DTO)- they can only hold
simple fields and Value Objects.
- Events should only contain information directly relevant to the event. A
receiver that needs more information should be listening to other pertinent
events and add read-only structures to its own state to take decisions later.
A receiver should not query the current state from the sender because the
sender's state could have already mutated.