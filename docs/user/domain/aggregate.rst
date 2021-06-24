.. _aggregate:

==========
Aggregates
==========

Aggregates are the coarse-grained building blocks of a domain model. They are conceptual wholes - they enclose all behaviors and data of a distinct domain concept and are often composed of one or more :ref:`Entities <entity>` and :ref:`Value Objects <value-object>`.

Aggregates essential are just ::ref:`Entity` with the additional responsibility of managing a cluster of objects. They responsible for the lifecycle management of all Entities and Value Objects within them, including fetching and persisting data.

Put another way, all elements in the Aggregate are only accessible through the Root Entity. The Aggregate acts as a consistency boundary and preserves data sanctity within the cluster.

Definition
==========

Aggregates are defined with the help of `@domain.aggregate` decorator::

    >>> from protean.domain import Domain
    >>> from protean.core.aggregate import BaseAggregate
    >>> from protean.core.field.basic import Date, String
    >>>
    >>> publishing = Domain(__name__)
    >>>
    >>> @publishing.aggregate
    ... class Post:
    ...     name = String(max_length=50)
    ...     created_on = Date()

In the above example, ``Post`` is defined to be an Aggregate with two fields, ``name`` and ``created_on`` and registered with the ``publishing`` domain.

You can also define the Aggregate as a subclass of ``BaseAggregate`` and register it manually with the domain::

    >>> class Post(BaseAggregate):
    ...     name = String(max_length=50)
    ...     created_on = Date()

    ... publishing.register(Post)
    <class '__main__.Post'>

Field Definitions
=================

You can define an Aggregate's fields with help of Protean's Fields. The list of available fields is outlined in


Metadata
========


Persistence
===========

An *Aggregate* is connected to the ``default`` provider, by default. Protean's out-of-the-box configuration specifies the in-built InMemory database as the  ``default`` provider.
