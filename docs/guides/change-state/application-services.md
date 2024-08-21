# Application Services

Application services act as a bridge between the external API layer and the
domain model, orchestrating business logic and use cases without exposing the
underlying domain complexity. They encapsulate and coordinate operations,
making them reusable and easier to manage, ensuring that all interactions with
the domain are consistent and controlled.

## Key Facts

- Application Services encapsulate business use cases and serve as the main
entry point for external requests to interact with the domain model.
- Application Services are predominantly used on the write side of the
application. If you want to use them on the read side as well, it is
recommended to create a separate application service for the read side.
- Application Services are stateless and should not hold any business logic
themselves; instead, they orchestrate and manage the flow of data and
operations to and from the domain model.
- Application Services ensure transaction consistency by automatically
enclosing all use case methods within a unit of work context.
- Application Services can interact with multiple aggregates and repositories,
but should only persist one aggregate, relying on events for eventual
consistency.

## Defining an Application Service

Application Services are defined with the `Domain.application_service`
decorator:

```python hl_lines="32 34 41"
{! docs_src/guides/change_state_008.py !}
```
