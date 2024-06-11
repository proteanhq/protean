# Compose a Domain

A [`Domain`](../../glossary.md#domain) in Protean represents a 
[Bounded Context](../../glossary.md#bounded-context) of the application. 
Because it is aware of all domain elements, the `protean.Domain` class acts as
the **Composition Root** of a domain and composes all domain elements together.
It is responsible for creating and maintaining the object graph of all the
domain elements in the Bounded Context.

`Domain` class is the one-stop gateway to:
- Register domain elements
- Retrieve dynamically-constructed artifacts like repositories and models
- Access injected technology components at runtime

!!! note
    A **domain** here is sometimes also referred to as the "Bounded Context",
    because it is an implementation of the domain model.

!!! info
    A **Composition Root** is a unique location in the application where 
    modules are composed together. It's the place where we instantiate objects
    and their dependencies before the actual application starts running.

