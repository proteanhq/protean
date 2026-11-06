# Domain Services

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Some business operations naturally span two or more aggregates. For example,
placing an order requires confirming the order *and* reserving inventory. The
two aggregates must be validated together. If you put this logic in the `Order`
aggregate, it needs to know about `Inventory`. If you put it in the command
handler, the application layer holds business rules. Domain services solve
this: they keep **cross-aggregate business logic** in the domain layer.

For background on when and why to use domain services, see
[Domain Services concept](../../concepts/building-blocks/domain-services.md).

!!!warning "Persist one aggregate, let events handle the rest"
    A domain service reads several aggregates to check its invariants, but it
    changes only **one**, the primary aggregate. The command handler invoking
    the service persists that aggregate. The primary aggregate raises an
    event, and an event handler issues a command that changes the other
    aggregate later. This preserves the
    [one aggregate per transaction](../../patterns/one-aggregate-per-transaction.md)
    rule.

## Defining a Domain Service

A Domain Service is defined with the `Domain.domain_service` decorator, and
associated with at least two aggregates with the `part_of` option. The
`part_of` option is **required** and must be a list of **two or more**
aggregates. Put logic that operates on a single aggregate on the aggregate
itself.

The service methods in a Domain Service can be structured in three flavors:

### 1. Class with class methods

If the Domain Service has no invariants, each of its methods can be a class
method. Each class method receives all the input the business function needs.
The method checks the stock itself and returns the order.

```python hl_lines="2-3"
# fragment
--8<-- "guides/domain-behavior/008.py:service"
```

Invoking it is straightforward:

```python
# fragment
OrderPlacementService.place_order(order, inventories)
```

!!!note
    Protean does not run a Domain Service's invariants around its class
    methods, so a class-method service should not declare any. If you need
    pre/post invariants, use the instance-method or callable-class flavor.
    Protean still wraps a public class method and treats its first argument
    as the service instance. It runs that argument's own invariants around
    the call, so pass an aggregate first: a list there raises
    `AttributeError`. Call the method on the class. A call on an instance
    raises `TypeError`, because the instance is passed as one argument too
    many.

### 2. Class with instance methods

In this flavor, you instantiate the Domain Service with the aggregates. Each
method performs a distinct business function.

```python hl_lines="2-3 10"
# fragment
--8<-- "guides/domain-behavior/007.py:service"
```

First, instantiate the Domain Service with the relevant aggregates. Then invoke
the methods on the instance.

```python
# fragment
service = OrderPlacementService(order, inventories)
service.place_order()
```

### 3. Callable class

If you have a single business function, you can model it as a callable
class:

```python hl_lines="2-3 10"
# fragment
--8<-- "guides/domain-behavior/006.py:service"
```

```python
# fragment
service = place_order(order, inventories)
service()
```

### Deciding between flavors

| Criterion | Class methods | Instance methods | Callable class |
|-----------|:---:|:---:|:---:|
| Invariants needed | No | Yes | Yes |
| Multiple operations | Yes | Yes | No (single `__call__`) |
| Simplest for single operation | — | — | Yes |

To choose between instance methods and a callable class, answer two questions:

1. **How many business functions does the Domain Service have?** If only one,
   a callable class is the simpler shape.
2. **Do you have `pre` invariants that only apply to specific methods?** Then
   construct each method as a separate callable class. If invariants apply to
   all methods, a class with instance methods is preferable.

As your domain model matures, review regularly and decide on the best
way to model the Domain Service.

!!!note
    Invariants only wrap public methods and `__call__`. They skip dunder
    methods (other than `__call__`) and private methods (prefixed with `_`).
    A public method that calls another public method on the same instance
    runs the invariants again around the inner call. An invariant that calls
    a public method fails: that method's wrapper runs the invariant again,
    which calls the method again, until Python's recursion limit stops the
    call. Put helpers in private methods (prefixed with `_`) so
    they are not wrapped.

## Domain Service vs Application Service vs Command Handler

These three constructs coordinate behavior, but at different levels:

| Aspect | Domain Service | Application Service | Command Handler |
|--------|---------------|-------------------|-----------------|
| **Contains business logic** | Yes, cross-aggregate rules | No, orchestration only | No, orchestration only |
| **Operates on** | 2+ aggregates | 1 aggregate | 1 aggregate |
| **Has invariants** | Yes (`@invariant.pre`/`.post`) | No | No |
| **Invoked by** | Command handlers, app services | External callers (API, CLI) | `domain.process(command)` |
| **Returns values** | Optional | Yes (synchronous) | No (fire-and-forget) |

For detailed guidance, see the
[Application Service vs Command Handler](../../patterns/application-service-vs-command-handler.md)
pattern.

## Typical Workflow

In the example below, an `OrderPlacementService` checks inventory stock and
confirms an order. The typical workflow of a Domain Service is below:

```mermaid
sequenceDiagram
  autonumber
  Command Handler->>Repository: Fetch order and product inventories
  Repository-->>Command Handler: order and inventories
  Command Handler->>Domain Service: Invoke operation
  Domain Service->>Domain Service: Validate (pre-invariants)
  Domain Service->>Domain Service: Change the order (it raises OrderConfirmed)
  Domain Service->>Domain Service: Validate (post-invariants)
  Domain Service-->>Command Handler: Done
  Command Handler->>Repository: Persist order (one aggregate)
```

The handler loads the necessary aggregates through repositories, invokes the
domain service to perform the cross-aggregate operation, and then persists only
the primary aggregate. `OrderConfirmed` carries the ordered items. An event
handler in the order's cluster reacts to `OrderConfirmed` and issues a command
to each inventory. The inventory's command handler reserves the stock in its
own transaction. In [Chapter 13 of the
tutorial](../getting-started/tutorial/13-domain-services.md), you build the
whole flow, including the event handler and the inventory command.

### Handler Integration Example

```python
# fragment
--8<-- "guides/domain-behavior/domain-services/001.py:handler"
```

## Invariants

Just like Aggregates and Entities, Domain Services can also have invariants.
These invariants validate the state of the aggregates passed to the service
method. Unlike in Aggregates, invariants in Domain Services typically check
rules that **span across multiple aggregates**.

`pre` invariants check the state of the aggregates before the service changes
the primary aggregate. `post` invariants check the state after the change. When
a pre-invariant fails, a `ValidationError` is raised and the change never
happens.

!!!note
   Review the business logic in the Domain Service at regular intervals. An
   invariant that does not use multiple aggregates likely belongs within an
   aggregate and not in the service.

## A Full-Blown Example

```python hl_lines="105-150"
--8<-- "guides/domain-behavior/006.py:full"
```

When an order is placed, `Order` status has to be `CONFIRMED` _and_ the stock
record of each product in `Inventory` has to be reduced.

The service checks the stock and the payment method before anything changes.
Then it confirms the order. It does not touch `Inventory`. `OrderConfirmed`
lists each ordered product and quantity. The inventory reduces its stock when
it handles the command issued for that event. The post invariants check two
things: the order is confirmed, and the event lists every ordered item. An item
missing from the event would never be reserved.

A Domain Service fits here because the stock rule needs both aggregates. The
`Order` aggregate cannot see `Inventory`. A command handler should not hold
business rules.

The stock check reads the inventory as it was loaded. Two orders placed at the
same time can both pass it. The inventory's command handler should check the
stock again before it reserves.

---

!!! seealso "See also"
    **Concept overview:** [Domain Services](../../concepts/building-blocks/domain-services.md): When and why to use domain services for cross-aggregate business logic.

    **Related guides:**

    - [Invariants](invariants.md): Business rules enforced on aggregates, entities, and domain services.
    - [Aggregate Mutation](aggregate-mutation.md): How state changes work inside aggregates.
    - [Command Handlers](../change-state/command-handlers.md): Orchestrating state changes from commands.
    - [Application Services](../change-state/application-services.md): Coordinating use cases.

    **Patterns:**

    - [One Aggregate per Transaction](../../patterns/one-aggregate-per-transaction.md): Why domain services persist only one aggregate.
    - [Thin Handlers, Rich Domain](../../patterns/thin-handlers-rich-domain.md): Keeping business logic in the domain, not handlers.
    - [Application Service vs Command Handler](../../patterns/application-service-vs-command-handler.md): Choosing the right orchestration layer.
