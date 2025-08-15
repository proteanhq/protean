# Philosophy

Protean is designed around the core principles and practices of
domain-driven design (DDD), enabling developers to mirror complex business
environments as closely as possible in code.

Protean advocates the separation of domain logic from infrastructural concerns,
ensuring that developers can focus on delivering value through clear,
technology-agnostic domain models.

Below are some **high-level tenets** of the framework:

- [Rapid prototyping](#rapid-prototyping)
- [Mirroring the domain in code](#mirroring-the-domain-in-code)
- [Technology-agnostic domain model](#technology-agnostic-domain-model)
- [Choose the right patterns](#choose-the-right-patterns)
- [Progressive fragmentation of domain](#progressive-fragmentation-of-domain)
- [Delay technology choices](#delay-technology-choices)
- [100% coverage](#100-coverage)

## Rapid prototyping

Not having to deal with the technology layer initially means that one can
construct and rapidly iterate on the domain model in isolation.

The domain model is built as a graph with all its elements and associations.
Since Python is easily readable, this facilitates better collaboration between
domain experts and developers, free from the hindrance of boilerplate code or
technical jargon.

## Mirroring the domain in code

Protean allows you to construct your domain model independently without
worrying about underlying technology or infrastructure. This means that you can
translate business requirements into domain elements directly using standard
DDD constructs and patterns.

The domain model can then be subjected to business use cases to test for its
validity.

## Technology-agnostic domain model

Protean encourages building applications independent of technology constraints,
using abstractions powered by a technology adapter of your choice.
This approach prevents premature lock-in to specific technologies, enhancing
the adaptability and longevity of your applications.

The underlying infrastructure is abstracted away, and you specify your
technology choices through configuration.

There will always be a need to fine-tune infrastructure code for practical
reasons, so Protean remains pragmatic and provides *escape hatches* to allow
you to override its implementation and specify your own.

Infrastructure elements, whether databases, API frameworks, or message brokers,
are initialized and injected at runtime, ensuring that your core domain logic
is insulated and remains consistent across various environments, including
local development and CI/CD.

## Pragmatism over Purity

Protean prioritizes practical solutions over architectural purity, recognizing
that real-world applications often require different patterns for different
parts of the same domain.

While architectural consistency within a domain is desirable, forcing a
single pattern across all aggregates can lead to over-engineering some
components while under-serving others. Protean embraces a **pragmatic
approach** that allows mixing CQRS and Event Sourcing patterns at the
aggregate level within the same domain, provided the decision is explicit,
well-documented, and justified.

## Progressive fragmentation of domain

Protean supports the gradual and organic decomposition of the domain model
into finer-grained bounded contexts. This approach ensures that complexity is
managed incrementally and allows for the natural evolution of the architecture.
As the understanding of the domain deepens, developers can break down larger
models into more specific bounded contexts, facilitating better maintainability
and scalability.

By enabling this progressive fragmentation, Protean ensures that the system
remains agile and adaptable, capable of evolving in response to changing
business needs and priorities. This flexibility is essential for sustaining
long-term development efforts and avoiding the pitfalls of monolithic designs.

## Delay technology choices

Postpone technological decisions until they become necessary and evident.

Protean emphasizes deferring technology decisions to the last responsible
moment. This principle ensures that the focus remains on accurately modeling
the domain and addressing business concerns without being prematurely
constrained by technology choices.

By delaying these decisions, teams can better align their technology stack
with the evolving requirements and priorities of the project. This approach
minimizes the risk of technology lock-in and allows for more informed and
strategic selections when the time comes to implement specific solutions.

Even once the technology choice has bee made, Protean's configuration-based
approach to specifying technology makes switching costs extremely low.

## 100% coverage

Achieve extensive test coverage of business logic, aiming for 100% coverage.

Protean advocates for comprehensive testing of business logic to ensure the
robustness and reliability of the application. The framework's design, which
allows for constructing the domain model independently of the tech
infrastructure makes it feasible to aim for 100% test coverage,
particularly within the domain model.

To facilitate this, Protean comes with built-in support for `pytest` and
`pytest-bdd`, streamlining the practice of Test-Driven Development (TDD).
This integration helps developers write effective tests and validate business
logic early and often, ensuring that the domain model behaves as expected and
remains resilient to changes.
