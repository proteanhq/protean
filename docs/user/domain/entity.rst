.. _entity:

========
Entities
========

An Entity represents an unique object in the domain. A passenger, for example, in the airline domain is an Entity. A seat, on the other hand, is an Entity if airlines distinguish each seat uniquely on every flight, or a Value Object if they consider all seats the same.

Unlike Value Objects, an Entity is not defined by its attributes or values. It is identified by a unique identity that remains the same throughout the object's life.

Entities are always defined as part of an Aggregate, which is a root entity that manages a cluster of related entities.

Usage
=====

You can define and register an Entity by annotating it with the `@domain.entity` decorator::

    >>> from protean.domain import Domain
    >>> from protean.core.field.basic import Date, String
    >>>
    >>> domain = Domain(__name__)
    >>>
    >>> @domain.aggregate
    ... class Post:
    ...     name = String(max_length=50)
    ...     created_on = Date()
    ...
    >>> @domain.entity
    ... class Comment:
    ...     content = String(max_length=500)
    ...     class Meta:
    ...         aggregate_cls = Post
    ...

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
