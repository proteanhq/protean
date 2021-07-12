==========
Aggregates
==========

Aggregates are the coarse-grained building blocks of a domain model. They are conceptual wholes - they enclose all behaviors and data of a distinct domain concept and are often composed of one or more :ref:`Entities <entity>` and :ref:`Value Objects <value-object>`.

Aggregates essential are just ::ref:`Entity` with the additional responsibility of managing a cluster of objects. They responsible for the lifecycle management of all Entities and Value Objects within them, including fetching and persisting data.

Put another way, all elements in the Aggregate are only accessible through the Root Entity. The Aggregate acts as a consistency boundary and preserves data sanctity within the cluster.

Definition
==========

Aggregate Roots are identified with the help of `@domain.aggregate` decorator:

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

Aggregate definitions enclose fields and behaviors that represent the domain concept. The fields declared in the aggregate are available as a map in :ref:`user-aggregate-meta-declared-fields`.

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

The complete list of available fields is available in :ref:`api-fields`.

Identity
========

Identity is one of the primary characteristics of Protean Entities - they are expected to have a unique identity.

All Aggregates and Entities have a unique identifier field named ``id``, added automatically by Protean. ``id`` is an :ref:`field-auto` field and populated with the strategy specified for the :ref:`identity-strategy` in Configuration.

.. code-block:: python

    @domain.aggregate
    class Person:
        first_name = String(max_length=30)
        last_name = String(max_length=30)

The identifier field is available as among ``declared_fields`` and is also accessible via the special ``id_field`` meta attribute::

    >>> Person.meta_.declared_fields
    {'first_name': <protean.core.field.basic.String at 0x10a647c70>,
    'last_name': <protean.core.field.basic.String at 0x10a6476d0>,
    'id': <protean.core.field.basic.Auto at 0x10a647340>}
    >>> Person.meta_.id_field
    <protean.core.field.basic.Auto at 0x10a647340>

By default, identifiers hold ``UUID`` values::

    >>> p = Person(first_name='John', last_name='Doe')
    >>> p.to_dict()
    {'first_name': 'John',
    'last_name': 'Doe',
    'id': '6667ec6e-d568-4ac5-9d66-0c9c4e3a571b'}

The identifier can be optionally overridden by setting ``identifier=True`` to a field. Fields marked as identifiers are both ``required`` and ``unique`` and can contain either Integer or String values.

.. code-block:: python

    @domain.aggregate
    class Person:
        email = String(identifier=True)
        first_name = String(max_length=30)
        last_name = String(max_length=30)

When overridden, the application is responsible for initializing the entity with a unique identifier value::

    >>> p = Person(first_name='John', last_name='Doe')
    ValidationError                           Traceback (most recent call last)
    ...
    ValidationError: {'email': ['is required']}

You can find an Aggregate's identifier field from its meta property :ref:`user-aggregate-meta-id-field` ::

    >>> Person.meta_.id_field
    <protean.core.field.basic.String at 0x10b8f67c0>
    >>> Person.meta_.id_field.attribute_name
    'email'

Aggregates marked abstract do not have an identity.

.. code-block:: python

    @domain.aggregate
    class TimeStamped(BaseAggregate):
        created_at = DateTime(default=datetime.utcnow)
        updated_at = DateTime(default=datetime.utcnow)

        class Meta:
            abstract=True

The base Aggregate ``TimeStamped`` will not have an automatically generated ``id`` field:

    >>> TimeStamped.meta_.declared_fields
    {'created_at': <protean.core.field.basic.DateTime at 0x1101cce50>,
    'updated_at': <protean.core.field.basic.DateTime at 0x1101cc040>}

Abstract Aggregates cannot have an explicit identifier field:

.. code-block:: python

    @test_domain.aggregate
    class User(BaseAggregate):
        email = String(identifier=True)
        name = String(max_length=55)

        class Meta:
            abstract=True

Trying to declare one will through an ``IncorrectUsageError``::

    >>>
    IncorrectUsageError                       Traceback (most recent call last)
    ...
    IncorrectUsageError: {'entity': ['Aggregates marked as abstract cannot have identity fields']}

Inheritance
===========

Often, you may want to put some common information into a number of Aggregates into your domain. A Protean Aggregate can be inherited from another Aggregate class:

.. code-block:: python

    @domain.aggregate
    class TimeStamped(BaseAggregate):
        created_at = DateTime(default=datetime.utcnow)
        updated_at = DateTime(default=datetime.utcnow)

    @domain.aggregate
    class User(TimeStamped):
        name = String(max_length=30)
        timezone = String(max_length=30)

The ``User`` aggregate will have three fields of its own including an identifier, and two derived from its parent class:

    >>> User.meta_.declared_fields
    {'name': <protean.core.field.basic.String at 0x10a80d8b0>,
    'timezone': <protean.core.field.basic.String at 0x1063753d0>,
    'created_at': <protean.core.field.basic.DateTime at 0x106375dc0>,
    'updated_at': <protean.core.field.basic.DateTime at 0x10a80dd60>,
    'id': <protean.core.field.basic.Auto at 0x10a83e6d0>}

    >>> user = User(name='John Doe', address='101, Timbuktu St.')
    >>> user.to_dict()
    {'name': 'John Doe',
    'timezone': None,
    'created_at': datetime.datetime(2021, 7, 7, 16, 35, 10, 799318),
    'updated_at': datetime.datetime(2021, 7, 7, 16, 35, 10, 799327),
    'id': '557770a2-5f34-4f80-895b-c38f2679766b'}

If you do not want the parent Aggregate to be instantiable, you can mark it as abstract.

Abstraction
===========

By default, Protean Aggregates and Entities are concrete and instantiable:

.. code-block:: python

    @domain.aggregate
    class Person:
        first_name = String(max_length=30)
        last_name = String(max_length=30)

``Person`` is concrete and can be instantiated:

    >>> Person.meta_.abstract
    False
    >>> person = Person(first_name='John', last_name='Doe')
    >>> person.to_dict()
    {'first_name': 'John',
    'last_name': 'Doe',
    'id': '6667ec6e-d568-4ac5-9d66-0c9c4e3a571b'}

You can optionally declare an Aggregate as abstract with the ``abstract`` :ref:`Meta option <user-aggregate-meta-abstract>`:

.. code-block:: python

    @domain.aggregate
    class AbstractPerson:
        first_name = String(max_length=30)
        last_name = String(max_length=30)

        class Meta:
            abstract = True

An Aggregate marked as ``abstract`` cannot be instantiated. It's primary purpose is to serve as a base class for other aggregates.

    >>> AbstractPerson.meta_.abstract
    True

Trying to instantiate an abstract Aggregate will raise a `NotSupportedError` error::

    >>> person = AbstractPerson()
    NotSupportedError                         Traceback (most recent call last)
    ...
    NotSupportedError: AbstractPerson class has been marked abstract and cannot be instantiated

An Aggregate derived from an abstract parent is concrete by default:

.. code-block:: python

    class Adult(AbstractPerson):
        age = Integer(default=21)

``Adult`` class is instantiable::

    >>> Adult.meta_.abstract
    False
    >>> adult = Adult(first_name='John', last_name='Doe')
    >>> adult.to_dict()
    {'first_name': 'John',
    'last_name': 'Doe',
    'age': 21,
    'id': '6667ec6e-d568-4ac5-9d66-0c9c4e3a571b'}

An Aggregate can be marked as ``abstract`` at any level of inheritance.

Metadata
========

Aggregate metadata is available under the ``meta_`` attribute of an aggregate object in runtime, and is made up of two parts:

Meta options
------------

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

abstract
~~~~~~~~

The flag used to mark an Aggregate as abstract. If abstract, the aggregate class cannot be instantiated and needs to be subclassed. Refer to the section on :ref:`entity-abstraction` for a deeper discussion.

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

provider
~~~~~~~~

The database that the aggregate is persisted in.

    Aggregates are connected to underlying data stores via providers. The definitions of these providers are supplied within the ``DATABASES`` key as part of the Domain's configuration during initialization. Protean identifies the correct data store, establishes the connection and takes the responsibility of persisting the data.

    Protean requires at least one provider, named ``default``, to be specified in the configuration. When no provider is explicitly specified, Aggregate objects are persisted into the ``default`` data store.

    Configuration:

    .. code-block:: python

        ...
        DATABASES = {
            'default': {
                'PROVIDER': 'protean_sqlalchemy.provider.SAProvider'
            },
            "nosql": {
                "PROVIDER": "protean.adapters.repository.elasticsearch.ESProvider",
                "DATABASE": Database.ELASTICSEARCH.value,
                "DATABASE_URI": {"hosts": ["localhost"]},
            },
        }
        ...

    You can then connect the provider explicitly to an Aggregate by its ``provider`` Meta option:

    .. code-block:: python

        @domain.aggregate
        class Person:
            first_name = String(max_length=30)
            last_name = String(max_length=30)

            class Meta:
                provider = 'nosql'

    Refer to :ref:`user-persistence` for an in-depth discussion about persisting to databases.

model
~~~~~

Protean automatically constructs a representation of the aggregate that is compatible with the configured database. While the generated model suits most use cases, you can also explicitly construct a model and associated it with the aggregate. Note that custom models are associated with a specific database type. The model is used only when database of the right type  is in use.

// FIXME Pending Documentation

schema_name
~~~~~~~~~~~

The name to store and retrieve the aggregate from the persistence store. By default, ``schema_name`` is the snake case version of the Aggregate's name.

    .. code-block:: python

        @domain.aggregate
        class UserProfile:
            name = String()

    ``schema_name`` is available under ``meta_``:

    >>> UserProfile.meta_.schema_name
    'user_profile'

Reflection
----------

Aggregates are decorated with additional attributes that you can use to examine the aggregate structure in runtime. The following meta attributes are available:

.. _user-aggregate-meta-declared-fields:

declared_fields
~~~~~~~~~~~~~~~

A map of fields explicitly declared in the Aggregate.

    >>> @domain.aggregate
    ... class Person:
    ...     first_name = String(max_length=30)
    ...     last_name = String(max_length=30)
    ...
    >>> Person.meta_.declared_fields
    {'first_name': <protean.core.field.basic.String at 0x10a647c70>,
    'last_name': <protean.core.field.basic.String at 0x10a6476d0>,
    'id': <protean.core.field.basic.Auto at 0x10a647340>}

.. _user-aggregate-meta-id-field:

id_field
~~~~~~~~

The identifier field configured for the Entity or Aggregate. A field can be marked as an identifier by setting the ``identifier=True`` option.

    >>> @domain.aggregate
    ... class Person:
    ...     email = String(identifier=True)
    ...     first_name = String(max_length=30)
    ...     last_name = String(max_length=30)
    ...
    >>> Person.meta_.id_field
    <protean.core.field.basic.String at 0x10b8f67c0>
    >>> Person.meta_.id_field.attribute_name
    'email'

When not explicitly identified, an identifier field named ``id`` of type :ref:`Auto`  is added automatically to the Aggregate::

    >>> @domain.aggregate
    ... class Person:
    ...     first_name = String(max_length=30)
    ...     last_name = String(max_length=30)
    ...
    >>> Person.meta_.declared_fields
    {'first_name': <protean.core.field.basic.String at 0x10a647c70>,
    'last_name': <protean.core.field.basic.String at 0x10a6476d0>,
    'id': <protean.core.field.basic.Auto at 0x10a647340>}
    >>> Person.meta_.id_field
    <protean.core.field.basic.Auto at 0x10a647340>

attributes
~~~~~~~~~~

A map of all fields, including :ref:`user-aggregate-meta-value-object-fields` and :ref:`user-aggregate-meta-reference-fields` fields. These attribute names are used during persistence of Aggregates, unless overridden by :ref:`api-fields-referenced-as`.

.. code-block:: python

    @domain.entity(aggregate_cls="Account")
    class Profile:
        email = String(required=True)
        name = String(max_length=50)
        password = String(max_length=50)

    @domain.value_object
    class Balance:
        currency = String(max_length=3)
        amount = Float()

    @domain.aggregate
    class Account:
        account_type = String(max_length=25)
        balance =  ValueObjectField(Balance)
        profile = Reference(Profile)

All fields are available under ``meta_``:

    >>> Account.meta_.attributes
    {'account_type': <protean.core.field.basic.String at 0x111ff3cd0>,
    'balance_currency': <protean.core.field.embedded._ShadowField at 0x111fe9d60>,
    'balance_amount': <protean.core.field.embedded._ShadowField at 0x111fe9df0>,
    'profile_id': <protean.core.field.association._ReferenceField at 0x111fe9cd0>,
    'id': <protean.core.field.basic.Auto at 0x111fe9be0>}

.. _user-aggregate-meta-value-object-fields:

value_object_fields
~~~~~~~~~~~~~~~~~~~

A map of fields derived from value objects embedded within the Aggregate.

.. code-block:: python

    @domain.value_object
    class Balance:
        currency = String(max_length=3)
        amount = Float()

    @domain.aggregate
    class Account:
        account_type = String(max_length=25)
        balance =  ValueObjectField(Balance)

The fields are now available as part of ``meta_`` attributes:

    >>> Account.meta_.value_object_fields
    {'balance_currency': <protean.core.field.embedded._ShadowField at 0x106d4d2e0>,
    'balance_amount': <protean.core.field.embedded._ShadowField at 0x106d4d310>}

.. _user-aggregate-meta-reference-fields:

reference_fields
~~~~~~~~~~~~~~~~

A map of reference fields (a.k.a Foreign keys, if you are familiar with the relational world) embedded within the Aggregate.

.. code-block:: python

    @domain.aggregate
    class Post:
        content = Text(required=True)
        author = Reference("Author")

    @domain.entity(aggregate_cls="Post")
    class Author:
        first_name = String(required=True, max_length=25)
        last_name = String(max_length=25)

An attribute named `author_id` (<Entity Name>_<Identifier>) is automatically generated and attached to the Aggregate::

    >>> Post.meta_.reference_fields
    {'author_id': <protean.core.field.association._ReferenceField at 0x105c65760>}

Persistence
===========

An *Aggregate* is connected to the ``default`` provider, by default. Protean's out-of-the-box configuration specifies the in-built InMemory database as the  ``default`` provider.

Custom Models
-------------
