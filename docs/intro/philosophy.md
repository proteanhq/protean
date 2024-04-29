# Philosophy

Protean is designed around the core principles and practices of
domain-driven design (DDD), enabling developers to mirror complex business
environments in code with precision and clarity. Protean advocates the
separation of domain logic from infrastructural concerns, ensuring that
developers can focus on delivering value through clear, technology-agnostic
domain models.

## Distill the problem domain

The distillation of the problem domain is at the core of Protean's approach.
Protean provides multiple mechanisms to deeply understand and reflect the
business domain in a domain model.

Rapid Prototyping

A visual mechanism to construct the domain model, bridging the gap between
business and technical team. It allows to take an experimental approach to
domain modeling. Multiple versions can be constructed. Domain models can be
evolved progressively.

The domain model as a graph with all its
elements and associations, allowing better colloboration between domain experts
and developers.

## Mirror the domain in code

Rapid Prototyping. Protean allows you to construct your domain model independently without
worrying about underlying technology or infrastructure. It empowers you to
translate business requirements into domain elements directly, using standard
DDD constructs and patterns.

The domain model can then be subjected to business use cases to test for its
validity.

## Remain technology agnostic

Protean encourages building applications independent of technology constraints,
using abstractions that can be powered by a technology adapter of your choice.
This approach prevents premature lock-in to specific technologies, enhancing
the adaptability and longevity of your applications.

The underlying infrastructure is abstracted away, and you specify your
technology choices through configuration. But there will always be fine-tuning
necessary for practical reasons, so Protean remains pragmatic and provides
escapte hatches to allow you to override its implementation and specify your
own.

By decoupling domain logic from infrastructure, Protean helps you:

- Accurately reflect the business needs in code with minimal translation.
- Postpone technological decisions until they become necessary and evident.
- Achieve extensive test coverage of business logic, aiming for 100% coverage.

Infrastructure elements, whether databases, API frameworks, or message brokers,
are integrated at runtime, ensuring that your core domain logic is insulated
and remains consistent across various environments, including testing scenarios.

## Choose the right architecture patterns

Protean does not prescribe a one-size-fits-all solution but instead offers
the flexibility to choose and combine architectural patterns that best suit
the needs of the domain:

- Flexibility and Choice: Developers are free to implement DDD, CRUD, CQRS,
Event Sourcing, or any combination thereof, depending on what best addresses
the problem at hand.
- Microservices Architecture: The use of microservices within Protean allows
for decentralized governance and technology diversity, which is crucial for
large-scale enterprise applications.
- Pattern Suitability: Each microservice or component can independently decide
its architectural style, promoting a system that is as heterogeneous as it
needs to be.

## Progressive fragmentation of domain