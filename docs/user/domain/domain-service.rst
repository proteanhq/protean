.. _domain-services:

===============
Domain Services
===============

A **Domain Service** handles stateless operations that execute domain-specific tasks.

    When a significant process or transformation in the domain is not a natural responsibility of an ENTITY or VALUE OBJECT, add an operation to the model as a standalone interface declared as a SERVICE. Define the interface in terms of the language of the model and make sure the operation name is part of the UBIQUITOUS LANGUAGE. Make the SERVICE stateless. - [|evans|, pp. 104, 106]

A Domain Service **is not** the same as an Application Service. Application Services are not supposed to have any business logic in them, but Domain Services do. Application Services, being the natural clients of the domain model, would normally be the client of a Domain Service. But the Service needs to be stateless and should have an interface that clearly expresses the Ubiquitous Language in its Bounded Context.

A Domain Service would be very similar to behavior defined in the domain model. It is fine-grained, focuses on some specific aspect of the business at hand, and does not deal with infrastructure. Typically, it is used be operate on two or more domain objects in a single, atomic operation, so it can handle more complexity than usual domain elements.

Typically, Domain Services are used when you need to:
* Transform one domain object to another
* Handle a business process of considerable complexity as a fine-grained, atomic transaction.
* Derive values from two or more than domain objects

.. |evans| raw:: html

    <a href="https://www.amazon.com/Domain-Driven-Design-Tackling-Complexity-Software/dp/0321125215" target="_blank">Evans</a>

Usage
=====

A Domain Service can be defined in two ways, as usual:

1. As a class inheriting from ``BaseDomainService``

.. code-block:: python

    class FavoriteArticle(BaseDomainService):
        """Mark as an Article as the current user's favorite"""

        @classmethod
        def mark_favorite(current_user, article):
            current_user.favorites.add(article)

You will then have to register the Domain Service with the domain:

.. code-block:: python

    domain.register(FavoriteArticle)

2. As a class annotated with ``@domain.domain_service``

.. code-block:: python

    @domain.domain_service
    class FavoriteArticle(BaseDomainService):
        """Mark as an Article as the current user's favorite"""

        @classmethod
        def mark_favorite(current_user, article):
            current_user.favorites.add(article)

In this case, registration is automatic and does not require manual registration of the domain element.
