# Events

Most applications have a definite state - they reflect past user input and
interactions in their current state. It is advantageous to model these past
changes as a series of discrete events. Domain events happen to be those
activities that domain experts care about and represent what happened as-is.

In Protean, an `Event` is an immutable object that represents a significant
occurrence or change in the domain. Events are raised by aggregates to signal
that something noteworthy has happened, allowing other parts of the system to
react - and sync - to these changes in a decoupled manner.

Events have a few primary functions:

1. **Events allows different components to communicate with each other.**

    Within a domain or across, events can be used as a mechanism to implement
    eventual consistency, in the same bounded context or across. This promotes
    loose coupling by decoupling the producer (e.g., an aggregate that raises
    an event) from the consumers (e.g., various components that handle the
    event).

    Such a design eliminates the need for two-phase commits (global
    transactions) across bounded contexts, optimizing performance at the level
    of each transaction.

2. **Events act as API contracts.**

    Events define a clear and consistent structure for data that is shared
    between different components of the system. This promotes system-wide
    interoperability and integration between components.

3. **Events help preserve context boundaries.**

    Events propagate information across bounded contexts, thus helping to
    sync changes throughout the application domain. This allows each domain
    to be modeled in the architecture pattern that is most appropriate for its
    use case.

## Defining Events

Event names should be descriptive and convey the specific change or occurrence
in the domain clearly, ensuring that the purpose of the event is immediately
understandable.  Events are named as past-tense verbs to clearly indicate
that an event has already occurred, such as `OrderPlaced` or `PaymentProcessed`.

You can define an event with the `Domain.event` decorator:

```python hl_lines="22 26 29-31 34-37"
{! docs_src/guides/domain-definition/events/001.py !}
```

Events are always connected to an Aggregate class, specified with the
`part_of` param in the decorator. An exception to this rule is when the
Event class has been marked _Abstract_.

## Event Facts

- Events should be named in past tense, because we observe domain events _after
the fact_. `StockDepleted` is a better choice than the imperative
`DepleteStock` as an event name.
- An event is associated with an aggregate or a stream, specified with
`part_of` or `stream` parameters to the decorator, as above. We will
dive deeper into these parameters in the Processing Events section.
<!-- FIXME Add link to events processing section -->
- Events are essentially Data Transfer Objects (DTO)- they can only hold
simple fields.
- Events should only contain information directly relevant to the event. A
receiver that needs more information should be listening to other pertinent
events and add read-only structures to its own state to take decisions later.
A receiver should not query the current state from the sender because the
sender's state could have already mutated.

## Immutability

