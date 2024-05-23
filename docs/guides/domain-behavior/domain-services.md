# Domain Services

Domain services act as orchestrators, centralizing complex domain logic that
doesn't neatly fit within an entity or aggregate. They encapsulate business
rules and domain decisions that need multiple aggregates as input.

Domain services free us from having to shoehorn business logic into aggregate
clusters. This keeps domain objects focused on their core state and behavior,
while domain services handle the broader workflows and complex interactions
within the domain.

Even though Domain services can access multiple aggregates, they are not meant
to propagate state changes in more than one aggregate. A combination of
Application Services, Events, and eventual consistency sync aggregates when a
transaction spans beyond an aggregate's boundary. We will discuss these aspects
more thoroughly in the Application Layer section.

## Key Facts

- **Stateless:** Domain services are stateless - they don’t hold any internal
state between method calls. They operate on the state provided to them through
their method parameters.
- **Encapsulate Business Logic:** Domain Services encapsulate complex business
logic or operations that involve multiple aggregate, specifically, logic that
doesn't naturally fit within any single aggregate.
- **Pure Domain Concepts:** Domain services focus purely on domain logic and
cannot handle technical aspects like persistence or messaging, though they
mutate aggregates to a state that they is ready to be persisted. Technical
concerns are typically handled by invoking services like application services
or command/event handlers.

## Defining a Domain Service

A Domain Service is defined with the `Domain.domain_service` decorator:

```python hl_lines="1 5-6"
--8<-- "guides/domain-behavior/006.py:83:100"
```

The domain service has to be associated with at least two aggregates with the
`part_of` option, as seen in the example above.

Each method in the Domain Service element is a class method, that receives two
or more aggregates or list of aggregates.

## Typical Workflow

Let us consider an example `OrderPlacementService` that places an order and
updates inventory stocks simultaneously. The typical workflow of a Domain
Service is below:

```mermaid
sequenceDiagram
  autonumber
  Application Service->>Repository: Fetch order and product invehtories
  Repository-->>Application Service: order and inventories
  Application Service->>Domain Service: Invoke operation
  Domain Service->>Domain Service: Mutate aggregates
  Domain Service-->>Application Service: 
  Application Service->>Repository: Persist aggregates
```

The application service loads the necessary aggregates through repositories,
and invokes the service method to place order. The service method executes
the business logic, mutates the aggregates, and returns them to the application
service, which then persists them again with the help of repositories.


## A full-blown example

```python hl_lines="67-82"
--8<-- "guides/domain-behavior/006.py:16:98"
```

When an order is placed, `Order` status has to be `CONFIRMED` _and_ the stock
record of each product in `Inventory` has to be reduced.

This change could be performed with events, with `Order` generating an event
and `Inventory` aggregate consuming the event and updating its records. But
there is a possibility of encountering stock depleted issues if multiple
orders are placed at the same time.

So a Domain Service works best here because it updates the states of both
the `Order` aggregate as well as the `Inventory` aggregate in a single
transaction.
