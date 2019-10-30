.. _foreword:

========
Foreword
========

Protean is built with two broad goals in mind:

**1. Domain-centric Code**
==========================

**Model the domain as closely as possible in code**

Developers should be able to express infrastructure-free domain logic clearly and concisely using Protean, without having to worry about underlying technology implementation.

Protean should allow developers to delay making technology choices until the problem domain is clear, and the decisions are obvious. Protean should support delaying taking decisions on critical technology components until the Last Responsible Moment (LRM) and, even after choosing a technology or architecture, should allow switching to a different technology.

By separating the domain-logic from infrastructure concerns, Protean allows developers to test the business logic thoroughly and maintain a high level of quality, including having 100% code coverage.

Even with this flexibility, Protean should remain pragmatic and allow the use of exclusive technology features (like non-SQL92-compliant database queries or non-standard messaging interfaces) for performance or aesthetic reasons.

To accomplish this goal, Protean adopts the **Domain-driven Design** methodology.

In its creator's words, **Domain-driven Design** is the expansion upon and application of the domain concept, as it applies to the development of software. It aims to ease the creation of complex applications by connecting the related pieces of the software into an ever-evolving model.

DDD focuses on three core principles:

* Focus on the core domain and domain logic.
* Base complex designs on models of the domain.
* Constantly collaborate with domain experts, to improve the application model and resolve any emerging domain-related issues.

In short, Domain-driven Design (DDD) is about trying to build an application as a model of a real-world system or process. In using DDD, Developers are meant to work closely with a domain expert who can explain how the real-world system works.

For example, if you're developing a system that handles financial transactions, your domain expert might be an experienced banker.

The thought process also applies to cases where there is no expert (as would be the case if you are building a new Product), but you have an opinion on how the real world process should work (a Hypothesis), and you are looking to prove it right or wrong (a Validation).

Between the developers and the domain expert, the team builds creates and maintains a Ubiquitous Language (UL), which is a conceptual description of the system. The idea is to write down what the system does in a way that the domain expert can read it and verify that it is correct. In our banking example, the ubiquitous language would include the definition of words such as 'account,' 'transfer,' 'interest,' and so on.

The essential concepts associated with a Domain model are:

* **Context**: The setting in which a word or statement appears that determines its meaning. Statements about a model are understandable only within a context.
* **Domain**: A sphere of knowledge (ontology), influence, or activity. The subject area to which the user applies a program is the domain of the software;
* **Model**: A system of abstractions that describes selected aspects of a domain and can be used to solve problems related to that domain.
* **Ubiquitous Language**: A language structured around the domain model and used by all team members to connect all the activities of the team with the software.
* **Bounded Context**: A description of a boundary (typically a subsystem, or the work of a specific team) within which a particular model definition applies.

DDD has two broad categories of patterns associated with it:

**Strategic Patterns**
^^^^^^^^^^^^^^^^^^^^^^

Ideally, it would be preferable to have a single, unified domain model. But in reality, applications tend to end up with two or more distinct models. The Strategic Design side of DDD is a set of principles for maintaining model integrity, distilling the Domain Model, and working with multiple models.

Strategic Patterns help model the domain better starting with Ubiquitous language:

* **Bounded Context**

Bounded Context (BC) is an explicit boundary that defines the context within which a model applies. A BC could also set boundaries in terms of team organization, specify usage within specific parts of the application, and be associated with physical manifestations such as code bases and database schemas. The model is strictly kept consistent within these bounds and does not care about issues outside it.

* **Context Map**

A Context map helps describe the different models in play on the project and their bounded contexts. It also outlines the points of contact between models outlining explicit translation for any communication and highlighting any sharing. It is a map of the existing terrain.

When connections are established between different contexts, a Context Map helps avoid models bleeding into each other.

**Tactical Patterns**
^^^^^^^^^^^^^^^^^^^^^

Tactical DDD is a set of design patterns and building blocks that you can use to design domain-driven systems.

Compared to strategic domain-driven design, the tactical design patterns are much more hands-on and closer to the actual code. Strategic design deals with abstract wholes, whereas tactical design deals with classes and modules. The purpose of tactical design is to refine the domain model to a stage where it can be transformed into a working code.

* **Entity**: An object that is identified by its consistent thread of continuity, instead of data attributes.
* **Value Object**: An immutable (unchangeable) object that has attributes, but no distinct identity.
* **Domain Event**: An object that is used to record a discrete event related to model activity within the system. While it is possible to track all events within the system, a domain event is only for those event types that are important to the domain experts.
* **Aggregate**: A cluster of entities and value objects with defined boundaries around the group. Rather than allowing every single entity or value object to perform all actions on its own, a singular aggregate root item owns the collective aggregate of items. Now, external objects no longer have direct access to every individual entity or value object within the aggregate, but instead, only have access to the single aggregate root item, and use that to pass along instructions to the group as a whole.
* **Service**: Essentially, a service is an operation or form of business logic that doesn't naturally fit within the realm of objects. In other words, if some functionality must exist, but it cannot be related to an entity or value object, it's probably a service.
* **Repositories**: The DDD meaning of a repository is a service that uses a global interface to provide access to all entities and value objects that are within a particular aggregate collection. By using this repository service to make data queries, the goal is to remove data query and persistence capabilities from within the business logic of object models.
* **Factories**: A factory encapsulates the logic of creating complex objects and aggregates, ensuring that the client does not know the inner-workings of object manipulation.

**2. Technology-agnostic Implementation**
=========================================

Protean enables developers to plugin technologies into the Domain layer, without affecting the core domain logic. All infrastructure components, like databases, API frameworks, message brokers, and cache, are instantiated outside the application and injected into the framework during runtime.

Protean also supports deploying and scaling applications independent of hosting platforms, including private data centers. Applications built on Protean come pre-packaged with DevOps scripts that ease the pain of deployment while allowing essential mechanisms like stability and failover to be available from day one.

Protean references the **Ports and Adapters** architecture pattern to provide this technology-agnostic support.

The main aim of Ports and Adapters architecture pattern is to decouple the application's core logic from the services it uses. This detachment allows different services to be "plugged in," and the application to run without these services.

The core logic, or business logic, of an application consists of the algorithms that are essential to its purpose, and they implement the use cases that are the heart of the application. When you change them, you change the essence of the application.

The infrastructure services are not essential; they are simply details. It should be possible to change services without changing the purpose of the application. As an example, you could switch from an RDBMS to a NoSQL database without changing the core behavior of your application. The same thought process applies to any other infrastructure service, like types of storage, UI components, email and SMS notifications, and hardware devices.

It goes on to say that even the application's web framework is a set of services. The core logic of an application should not depend on these services so that it becomes "framework agnostic."

There are many advantages of using this architecture pattern, the most notable being:

* The core logic can be tested independent of outside services
* It is easy to switch to services that fit better to changing requirements
