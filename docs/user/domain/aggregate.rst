.. _aggregate:

==========
Aggregates
==========

Aggregates are the coarse-grained building blocks of a domain model. They are conceptual wholes - they enclose all behaviors and data of a distinct domain concept and are often composed of one or more :ref:`Entities <entity>` and :ref:`Value Objects <value-object>`.

Aggregates essential are just ::ref:`Entity` with the additional responsibility of managing a cluster of objects. They responsible for the lifecycle management of all Entities and Value Objects within them, including fetching and persisting data.

Put another way, all elements in the Aggregate are only accessible through the Root Entity. The Aggregate acts as a consistency boundary and preserves data sanctity within the cluster.

Definition
==========

Aggregates are defined with the help of `@domain.aggregate` decorator:

.. code-block:: python

    from protean.domain import Domain
    from protean.core.field.basic import Date, String

    publishing = Domain(__name__)

    @publishing.aggregate
    class Post:
        name = String(max_length=50)
        created_on = Date()

In the above example, ``Post`` is defined to be an Aggregate with two fields, ``name`` and ``created_on`` and registered with the ``publishing`` domain.

You can also define the Aggregate as a subclass of ``BaseAggregate`` and register it manually with the domain::

    >>> class Post(BaseAggregate):
    ...     name = String(max_length=50)
    ...     created_on = Date()

    ... publishing.register(Post)
    <class '__main__.Post'>

Field Declarations
==================

Aggregate definitions enclose fields and behaviors that represent the domain concept. The complete list of available fields is available in :ref:`api-fields`

This example defines a ``Person`` Aggregate, which has a ``first_name`` and ``last_name``.

.. code-block:: python

    @domain.aggregate
    class Person:
        first_name = String(max_length=30)
        last_name = String(max_length=30)

``first_name`` and ``last_name`` are fields of the aggregate. Each field is specified as a class attribute, and each attribute ultimately maps to a database column (or node if you are using a NoSQL database)::

    >>> Person.meta_.declared_fields
    {'first_name': <protean.core.field.basic.String at 0x114a3be20>,
    'last_name': <protean.core.field.basic.String at 0x114a3bc40>,
    'id': <protean.core.field.basic.Auto at 0x114a3b310>}

You can initialize the values of a person object by passing them as key-value pairs during initialization::

    >>> person = Person(first_name="John", last_name="Doe")
    >>> person.to_dict()
    {'first_name': 'John',
    'last_name': 'Doe',
    'id': '6c5e7221-e0c6-4901-9a4f-c9218096b0c2'}

A default identifier field named ``id`` is associated with an Aggregate object on initialization. Read more about :ref:`identity` to understand aspects of primary key generation.


Subclassing Aggregates
======================



Metadata
========

Aggregate metadata is available under the ``meta_`` attribute of an aggregate object in runtime, and is made up of two parts:

Meta options:
-------------

Options that control Aggregate behavior, such as its database provider, the name used to persist the aggregate entity, or if the Aggregate is abstract. These options can be overridden with an inner ``class Meta``, like so:

.. code-block:: python

    @domain.aggregate
    class Person:
        first_name = String(max_length=30)
        last_name = String(max_length=30)

        class Meta:
            provider = 'nosql'

The overridden attributes are reflected in the ``meta_`` attribute:

    >>> Person.meta_.provider
    'nosql'

Available options are:

- ``abstract``: The flag used to mark an Aggregate as abstract. If abstract, the aggregate class cannot be instantiated and needs to be subclassed. Refer to the section on :ref:`entity-abstraction` for a deeper discussion.

.. code-block:: python

    @domain.aggregate
    class Person:
        first_name = String(max_length=30)
        last_name = String(max_length=30)

        class Meta:
            abstract = True

Trying to instantiate an abstract Aggregate will throw a ``NotSupportedError``:

    >>> p = Person(first_name='John', last_name='Doe')
    NotSupportedError                         Traceback (most recent call last)
    ...
    NotSupportedError: Person class has been marked abstract and cannot be instantiated

- ``provider``:

- ``model``:

- ``schema_name``:

- ``ordering``:



Reflection:
-----------

Aggregates are decorated with additional attributes that you can use to examine the aggregate structure in runtime. The following meta attributes are available:

- ``declared_fields``:

- ``id_field``:

- ``attributes``:

- ``value_object_fields``:

- ``reference_fields``:



Persistence
===========

An *Aggregate* is connected to the ``default`` provider, by default. Protean's out-of-the-box configuration specifies the in-built InMemory database as the  ``default`` provider.
