Data Fields
===========

This document contains the field options and field types available in Protean, and their built-in capabilities.

Field options
-------------

required
````````

If ``True``, the field is not allowed to be blank. Default is ``False``.

.. code-block:: python

    @domain.aggregate
    class Person:
        name = String(required=True)

Leaving the field blank or not specifying a value will raise a ``ValidationError``::

    >>> p1 = Person()
    defaultdict(<class 'list'>, {'name': ['is required']})
    ...
    ValidationError: {'name': ['is required']}

identifier
``````````

If ``True``, the field is the primary key for the entity.

.. code-block:: python

    @domain.aggregate
    class Person:
        email = String(identifier=True)
        name = String(required=True)

The field is validated to be unique and non-blank::

    >>> p = Person(email='john.doe@example.com', name='John Doe')
    >>> p.meta_.declared_fields
    {'email': <protean.core.field.basic.String at 0x10b76de80>,
    'name': <protean.core.field.basic.String at 0x10fb96160>}
    >>> p = Person(name='John Doe')
    ValidationError                           Traceback (most recent call last)
    ...
    ValidationError: {'email': ['is required']}

If you don't specify ``identifier=True`` for any field in your Entity, Protean will automatically add a field called ``id`` to hold the primary key, so you don't need to set ``identifier=True`` on any of your fields unless you want to override the default primary-key behavior.

Alternatively, you can use the ::ref:`field-type-identifier` field for primary key fields. The type of the field can be specified per domain in config with :ref:`user-configuration-identity-type`.

default
```````

The default value for the field. This can be a value or a callable object. If callable, it will be called every time a new object is created.

.. code-block:: python

    @domain.aggregate
    class Adult:
        name = String(max_length=255)
        age = Integer(default=21)

The default can't be a mutable object (list, set, dict, entity instance, etc.), as a reference to the same object would be used as the default value in all new entity instances. Instead, wrap the desired default in a callable.

For example, to specify a default ``list`` for ``List`` field, use a function:

.. code-block:: python

    def standard_topics():
        return ["Music", "Cinema", "Politics"]

    @domain.aggregate
    class Adult:
        name = String(max_length=255)
        age = Integer(default=21)
        topics = List(default=standard_topics)

Initializing an ``Adult`` aggregate would populate the defaults when values are not specified explicitly::

    >>> adult1 = Adult(name="John Doe")
    >>> adult1.to_dict()
    {'name': 'John Doe', 'age': 21, 'topics': ['Music', 'Cinema', 'Politics'], 'id': '8c0f63c0-f4c2-4f73-baad-889f63565986'}

You can even use a lambda expression to specify an anonymous function:

.. code-block:: python

    import random

    @domain.aggregate
    class Dice:
        throw = Integer(default=lambda: random.randrange(1, 6))

unique
``````

If ``True``, this field must be unique among all entities.

.. code-block:: python

    @domain.aggregate
    class Person:
        name = String(max_length=255)
        email = String(unique=True)

This is enforced by entity validation. If you try to save an entity with a duplicate value in a ``unique`` field, a :ref:`validation-error` will be raised::

    >>> p1 = Person(name='John Doe', email='john.doe@example.com')
    >>> domain.repository_for(Person).add(p1)
    >>> p2 = Person(name= 'Jane Doe', email='john.doe@example.com')
    >>> domain.repository_for(Person).add(p2)
    ValidationError                           Traceback (most recent call last)
    ...
    ValidationError: {'email': ["Person with email 'john.doe@example.com' is already present."]}

choices
```````

When supplied, the value of the field is validated to be one among the specified options.

.. code-block:: python

    class BuildingStatus(Enum):
        WIP = "WIP"
        DONE = "DONE"

    @domain.aggregate
    class Building:
        name = String(max_length=50)
        floors = Integer()
        status = String(choices=BuildingStatus)

The value is generally supplied as a string during entity initialization::

    >>> building = Building(name="Atlantis", floors=3, status="WIP")
    >>> building.to_dict()
    {'name': 'Atlantis',
    'floors': 3,
    'status': 'WIP',
    'id': '66562983-bd3a-4ac0-864c-2034cb6bea0d'}

The choices are enforced during entity validation::

    >>> building = Building(name="Atlantis", floors=3, status="COMPLETED")
    ValidationError                           Traceback (most recent call last)
    ...
    ValidationError: {'status': ["Value `'COMPLETED'` is not a valid choice. Must be one of ['WIP', 'DONE']"]}

.. _api-fields-referenced-as:

referenced_as
`````````````

The name used to store and retrieve the attribute's value. A field's ``referenced_as`` name is used by Protean's persistence mechanism while storing and retrieving the field.

.. code-block:: python

    @domain.aggregate
    class Person:
        email = String(unique=True)
        name = String(referenced_as='fullname', required=True)

``meta_.declared_fields`` will preserve the original field name, while ``meta_.attributes`` will reflect the new name::

    >>> Person.meta_.declared_fields
    {'email': <protean.core.field.basic.String at 0x109f20820>,
    'fullname': <protean.core.field.basic.String at 0x109f20880>,
    'id': <protean.core.field.basic.Auto at 0x109eed940>}
    >>> Person.meta_.attributes
    {'email': <protean.core.field.basic.String at 0x109f20820>,
    'fullname': <protean.core.field.basic.String at 0x109f20880>,
    'id': <protean.core.field.basic.Auto at 0x109eed940>}

TO BE DOCUMENTED

validators
``````````

A list of validators to run for this field. See :ref:`Validators API Documentation <api-validators>`  for more information.

error_messages
``````````````

If supplied, the default messages that the field will raise will be overridden. Error message keys include **required**, **invalid**, **unique**, and **invalid_choice**. Additional error message keys are specified for each field in the :ref:`field-types` section below.

.. code-block:: python

    @domain.aggregate
    class Child:
        name = String(required=True, error_messages={'required': "Please specify child's name"})
        age = Integer(required=True)

The custom error message can be observed in the ``ValidationError`` exception::

    >>> Child()
    ValidationError                           Traceback (most recent call last)
    ...
    ValidationError: {'name': ["Please specify child's name"], 'age': ['is required']}

The error message can be formatted with additional keyword arguments:

.. //FIXME Pending Documentation

.. _field-types:

Basic Fields
------------

.. _field-type-string:

String
``````

A string field, for small- to large-sized strings. For large amounts of text, use :ref:`field-type-text`.

``String`` has two optional arguments:

- ``max_length``: The maximum length (in characters) of the field, enforced during validation using :ref:`MaxLengthValidator <max-value-validator>`. Defaults to 255.
- ``min_length``: The minimum length (in characters) of the field, enforced during validation using :ref:`MinLengthValidator <min-value-validator>`.

.. _field-type-text:

Text
````

A large text field, to hold large amounts of text. Text fields do not have size constraints.

.. _field-type-integer:

Integer
```````

An integer. It uses :ref:`MinValueValidator <min-value-validator>` and :ref:`MaxValueValidator <max-value-validator>` to validate the input based on the values that the default database supports.

``Integer`` has two optional arguments:

- ``max_value``: The maximum numeric value of the field, enforced during validation using :ref:`MaxValueValidator <max-value-validator>`.
- ``min_value``: The minimum numeric value of the field, enforced during validation using :ref:`MinValueValidator <min-value-validator>`.

Float
`````

A floating-point number represented in Python by a float instance.

``Float`` has two optional arguments:

- ``max_value``: The maximum numeric value of the field, enforced during validation using :ref:`MaxValueValidator <max-value-validator>`.
- ``min_value``: The minimum numeric value of the field, enforced during validation using :ref:`MinValueValidator <min-value-validator>`.

Boolean
```````

A ``True``/``False`` field.

.. code-block:: python

    @domain.aggregate
    class Person:
        name = String(required=True)
        adult = Boolean()

The default value is ``None`` when ``default`` option isn’t defined::

    >>> person = Person(name='John Doe')
    >>> p4.to_dict()
    {'name': 'John Doe',
    'adult': None,
    'id': 'e30e97fb-540b-43f0-8fc9-937baf413080'}

.. _field-type-auto:

Auto
````

Automatically-generated unique identifiers. By default, all entities and aggregates hold an ``Auto`` field named ``id`` that acts as their unique identifier. You cannot supply values explicitly to ``Auto`` fields - they are self-generated.

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

An ``Auto`` field is unique by default::

    >>> vars(Person.meta_.id_field)
    ...
    {'field_name': 'id',
    'attribute_name': 'id',
    'identifier': True,
    'default': None,
    'unique': True,
    'required': False,
    ...

At the same time, ``Auto`` fields cannot be marked as ``required`` because their values cannot be specified explicitly.

.. _field-type-identifier:

Identifier
``````````

.. //FIXME Pending Documentation

Date
````

A date, represented in Python by a ``datetime.date`` instance.

.. code-block:: python

    @domain.aggregate
    class Person:
        name = String(required=True)
        born_on = Date(required=True)

The date can be specified as a ``datetime.date`` object::

    >>> p = Person(name="John Doe", born_on=datetime(1962, 3, 16).date())
    >>> p.to_dict()
    {'name': 'John Doe',
    'born_on': datetime.date(1962, 3, 16),
    'id': '0f9d4f86-a47c-48ec-bb14-8b8bb8a65ae3'}

Or as a string, which will be parsed by ``dateutil.parse``::

    >>> p = Person(name="John Doe", born_on="2018-03-16")
    >>> p.to_dict()
    {'name': 'John Doe',
    'born_on': datetime.date(1962, 3, 16),
    'id': '0f9d4f86-a47c-48ec-bb14-8b8bb8a65ae3'}

DateTime
````````

A date and time, represented in Python by a ``datetime.datetime`` instance.

.. code-block:: python

    @domain.aggregate
    class User:
        email = String(required=True)
        created_at = DateTime(required=True)

The timestamp can be specified as a ``datetime.datetime`` object::

    >>> u = User(email="john.doe@example.com", created_at=datetime.utcnow())
    >>> u.to_dict()
    {'email': 'john.doe@example.com',
    'created_at': datetime.datetime(2021, 6, 25, 22, 55, 19, 28744),
    'id': '448f885e-be8f-4968-bb47-c637eabc21f8'}

Or as a string, which will be parsed by ``dateutil.parse``::

    >>> u = User(email="john.doe@example.com", created_at="2018-03-16 10:23:32")
    >>> u.to_dict()
    {'email': 'john.doe@example.com',
    'created_at': datetime.datetime(2018, 3, 16, 10, 23, 32),
    'id': '1dcb17e1-64e9-43ef-b9bd-802b8a004765'}

Container Fields
----------------

List
````

A collection field that accepts values of a specified basic field type.

.. code-block:: python

    @domain.aggregate
    class User:
        email = String(max_length=255, required=True, unique=True)
        roles = List()  # Defaulted to hold String Content Type

``roles`` now accepts a list of strings:

    >>> user = User(email='john.doe@example.com', roles=['ADMIN', 'EDITOR'])
    >>> user.to_dict()
    {'email': 'john.doe@example.com',
    'roles': ['ADMIN', 'EDITOR'],
    'id': 'ef2b222b-de5c-4968-8b1c-7e3cdb4a3c2c'}

The supplied value needs to be a Python ``list``. Specifying values of a different basic type or a mixture of types throws a ``ValidationError``::

    >>> user = User(email='john.doe@example.com', roles=[2, 1])
    ValidationError                           Traceback (most recent call last)
    ...
    ValidationError: {'roles': ['Invalid value [2, 1]']}

``List`` has two optional arguments:

- ``content_type``: The type of Fields enclosed in the list.

    Accepted Field Types are:

    - ``Boolean``
    - ``Date``
    - ``DateTime``
    - ``Float``
    - ``Identifier``
    - ``Integer``
    - ``String``
    - ``Text``

    Default ``content_type`` is ``String``.

- ``pickled``: Flag to treat the field as a Python object. Defaults to ``False``. Some database implementations (like Postgresql) can store lists by default. You can  force it to store the pickled value as a Python object by specifying ``pickled=True``. Databases that don't support lists simply store the field as a python object, serialized using pickle.

Dict
````

A map that closely resembles the Python Dictionary in its utility.

.. code-block:: python

    @domain.aggregate
    class Event:
        name = String(max_length=255)
        created_at = DateTime(default=datetime.utcnow)
        payload = Dict()

A regular dictionary can be supplied as value to ``payload``::

    >>> event=Event(name='UserRegistered', payload={'name': 'John Doe', 'email': 'john.doe@example.com'})
    >>> event.to_dict()
    {'name': 'UserRegistered',
    'created_at': datetime.datetime(2021, 6, 25, 22, 37, 24, 680524),
    'payload': {'name': 'John Doe', 'email': 'john.doe@example.com'},
    'id': 'ab803d41-b8b0-48e6-a930-f0f265f62d9e'}

``Dict`` accepts an optional argument:

- ``pickled``: Flag to treat the field as a Python object. Defaults to ``False``. Some database implementations (like Postgresql) can store dicts as JSON by default. You can  force it to store the pickled value as a Python object by specifying ``pickled=True``. Databases that don't support lists simply store the field as a python object, serialized using pickle.

Method
``````

Nested
``````

Associations
------------

Embedded Fields
---------------
