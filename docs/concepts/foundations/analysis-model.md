# What is the Analysis Model?

The Analysis Model describes the real-world domain in a form that developers
can implement in software. It is a layer of abstraction that describes the core
concepts and behaviors of the domain and leaves out technological details.

When you build an Analysis Model, you get a structured way to understand and
model the domain. Everyone involved then shares a common language and a shared
understanding of the system being built.

## How the model expresses the ubiquitous language

The Analysis Model is developed collaboratively by domain experts and
developers. It is one of the artifacts that make up the ubiquitous language of
the domain. Domain experts and developers use the model to align the business
and engineering teams on the domain's terminology, concepts, and behaviors. In
the Analysis Model, the team translates this shared understanding into a
technical representation with DDD's tactical patterns (like Aggregates,
Entities, Value Objects, and Repositories). The system's design and
implementation then follow that representation.

## Why the model stays standalone and technology-agnostic

The Analysis Model should remain independent of implementation aspects such as
specific technologies and infrastructure choices. When you describe the essence
of the domain and leave out the details of its implementation, the Analysis
Model becomes a standalone artifact with several benefits:

* **You can change technology:** New technologies and platforms appear all the
time. When you keep the Analysis Model independent, you can adapt the
implementation to new technologies or platforms without changing the core
domain understanding.
* **You can reuse the model:** A well-defined Analysis Model becomes a reusable
asset. It can be a foundation for building multiple applications within the
same domain, even when using different technical stacks.
* **Your team communicates clearly:** Because the model is technology-agnostic,
everyone on the team can discuss it clearly. Domain experts can focus on
business functionalities. Developers can translate those functionalities from
business needs into code, and neither group has to use technology-specific
jargon.

## How does the Analysis Model differ from the code model?

The analysis model is a conceptual artifact, diagrams, documents, and
conversations that capture the team's understanding of the domain. The code
model is the working software that implements that understanding in classes,
methods, and tests.

In practice, these two models tend to drift apart. Teams often create the
analysis model at the start of a project and then stop updating it. Developers
keep changing the code to meet deadlines, new requirements, and technical
constraints. Over time, the code model develops its own vocabulary and
structure. That vocabulary and structure no longer match the domain experts'
description. The gap becomes a source of bugs, miscommunication, and costly
rework.

DDD's central goal is to keep these two models aligned. The code should be a
direct expression of the analysis model. When the team learns something new
about the domain, the team updates the analysis model and refactors the code to
match. Sometimes the code shows the analysis model to be wrong or incomplete.
The team then updates the analysis model. Neither model is disposable. The two
models evolve together.

## How Protean Keeps Them Aligned

With Protean's decorators, you declare each domain element explicitly in code.
An aggregate is declared with `@domain.aggregate`, a command with
`@domain.command`, an event with `@domain.event`. These decorators name the
elements in the [ubiquitous language](./ubiquitous-language.md) and make them
visible in the codebase. When a domain expert asks "where is the Order
aggregate?" a developer can point to a class with that exact name and role.

In-memory adapters enable immediate validation of domain logic without
infrastructure dependencies. The analysis model can be expressed as working
code and tested against real scenarios the same day it is discussed. With this
short feedback loop, you find misunderstandings early, before you add
infrastructure code around the domain logic.

When the team renames, splits, or restructures a concept in the analysis model,
developers refactor the code to match. Because domain elements are explicitly
declared, the refactoring is mechanical: rename the class, update the
decorator, adjust the references. The cost of keeping the models aligned stays
low throughout the life of the project.

## Make the model 100% testable

The Analysis Model should be designed to be testable in isolation from the
final software implementation. You can then verify the domain logic in the
model early and often, and confirm its integrity and correctness before
full-scale development begins.

By keeping the Analysis Model independent of underlying technology, it becomes
100% testable using plain old Python objects. You do not need mocks or
dependency injection of external systems, so you can validate domain logic
directly with unit tests. You find and fix issues early, so development goes
faster. Domain logic also stays separate from infrastructure concerns, so the
codebase is easier to maintain.
