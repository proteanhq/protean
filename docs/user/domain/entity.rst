.. _entity:

========
Entities
========

An Entity represents an unique object in the domain model. Entities are identified by their unique identities that remain the same throughout its life - they are not defined by their attributes or values. For example, a passenger in the airline domain is an Entity. The passenger's identity remains the same across multiple seat bookings, even if her profile information (name, address, etc.) changes over time.

An Entity in one domain may not be an Entity in another. For example, a seat is an Entity if airlines distinguish each seat uniquely on every flight. If passengers are not allotted specific seats, then a seat can be considered a :ref:`value_object` as one seat can be exchanged with another.

In Protean, Entities are always associated with an :ref:`aggregate`, which is the root Entity that manages the cluster of related entities.

Usage
=====

You can define and register an Entity by annotating it with the `@domain.entity` decorator::

.. code-block:: python

    from protean.domain import Domain
    from protean.core.field.basic import Date, String

    publishing = Domain(__name__)

    @publishing.aggregate
    class Post:
        name = String(max_length=50)
        created_on = Date()

    @publishing.entity
    class Comment:
        content = String(max_length=500)

        class Meta:
            aggregate_cls = Post



    >>> Comment.meta_.aggregate_cls
    <class '__main__.Post'>

.. _entity-abstraction:

Abstraction
===========

By default, Protean Entities are concrete and instantiable::

    >>> from protean.core.entity import BaseEntity
    >>> from protean.core.field.basic import String

    >>> class Customer(BaseEntity):
    ...         first_name = String(max_length=255, required=True)
    ...         last_name = String(max_length=255)
    ...
    >>> Customer.meta_.abstract
    False

You can optionally declare them as abstract::

    >>> from protean.core.field.basic import Integer

    >>> class AbstractPerson(BaseEntity):
    ...     age = Integer(default=5)
    ...     class Meta:
    ...         abstract = True
    ...
    >>> AbstractPerson.meta_.abstract
    True

Trying to instantiate an abstract Entity will raise a `NotSupportedError` error::

    >>> person = AbstractPerson()
    Traceback (most recent call last):
    ...
    protean.core.exceptions.NotSupportedError: AbstractPerson class has been marked abstract and cannot be instantiated

An Entity derived from an abstract parent Entity is concrete by default:

    >>> class Adult(AbstractPerson):
    ...     class Meta:
    ...         schema_name = "adults"
    ...
    >>> Adult.meta_.abstract
    False

You can mark an Entity as abstract at any level of inheritance.
