.. _aggregate:

==========
Aggregates
==========

Aggregates are the coarse-grained building blocks of a domain model. They are conceptual wholes - they enclose all behaviors and data of a distinct domain concept and are often composed of one or more :ref:`Entities <entity>` and :ref:`Value Objects <value-object>`.

Aggregates are effectively just Entities with the exception that an Aggregate is at the root of a cluster of objects. It is responsible for the lifecycle management of all Entities and Value Objects within the Aggregate, including fetching and persisting data.

Put another way, all elements in the Aggregate are only accessible through the Root Entity. The Aggregate acts preserves data sanctity and acts as a transaction boundary for the elements.


Definition
==========

Aggregates are defined with the help of `@domain.aggregate` decorator::

    >>> from protean.domain import Domain
    >>> from protean.core.field.basic import Date, String
    >>>
    >>> domain = Domain(__name__)
    >>>
    >>> @domain.aggregate
    ... class Post:
    ...     name = String(max_length=50)
    ...     created_on = Date()

In the above example, ``Post`` is defined to be an Aggregate with two fields, ``name`` and ``created_on`` and registered with the domain.

Domain Registration
-------------------

Fields
======


Metadata
========


Persistence
===========

An *Aggregate* is connected to the ``default`` provider, by default. Protean's out-of-the-box configuration specifies the in-built InMemory database as the  ``default`` provider.
