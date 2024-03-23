Foreword
========

Read this before you get started with Protean. This hopefully answers some questions about the purpose and goals of the project and when you should or should not be using it.

Mirror the domain in code
-------------------------

Protean allows you to express your domain (a.k.a, business requirements) clearly and concisely, without worrying about underlying technology or infrastructure.

By separating domain logic from infrastructure, Protean allows you to:
- Reflect the business as accurately as possible in code without translation
- Delay making technology choices until the choices are obvious
- Test business logic thoroughly and have 100% coverage

The underlying infrastructure is abstracted away, and you specify the technology choice through config attributes. Even with this flexibility, Protean remains pragmatic and allows you to override its implementation. For instance, you can use exclusive technology features (like non-SQL92-compliant database queries or non-standard messaging interfaces) for performance or aesthetic reasons.

.. //FIXME Include reference to Escape hatches

Remain technology agnostic
--------------------------

Protean allows you to pick and choose technology components through configuration without affecting core domain logic. These components are made available as adapters that conform in structure and behavior to a published port interface.

Infrastructure components like databases, API frameworks, message brokers, and cache are instantiated outside the application and injected into the framework at runtime. This helps choose different technologies in diverse circumstances for the same code base - tests, for example, can be run on a lightweight database.

Protean comes pre-packaged with adapters for many technology choices, but it is relatively straightforward to roll out your own if need be.

Choose the right design pattern
-------------------------------

Protean adopts |ddd| as its primary approach to building large-scale applications but also allows other architecture patterns, like CRUD, CQRS, and EventSourcing, to be used in combination. You are also free to choose the extent to which you follow each architecture's principles.

A Protean application is typically made up of one or more microservices that communicate with each other through Domain Events but are in total control of their own architecture. They can choose from a variety of patterns like DDD, CQRS, ES, or CRUD. The decision of which pattern is most suited for the problem at hand is left to each microservice.

In reality, Protean applications tend to be a combination of one or more of these patterns. It is indeed an anti-pattern to have the entire application built on a single design pattern.

.. |ddd| raw:: html

    <a href="https://en.wikipedia.org/wiki/Domain-driven_design" target="_blank">Domain-Driven Design</a>
