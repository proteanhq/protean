.. _fields:

===============
Field Reference
===============

This document contains the field options and field types Protean offers.

Field options
-------------

required
~~~~~~~~

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
~~~~~~~~~~

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

Alternatively, you can use the ::ref:`Identifier` field for primary key fields. The type of the field can be specified per domain in config with :ref:`IDENTITY_TYPE`.

default
~~~~~~~

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
~~~~~~

If ``True``, this field must be unique among all entities.

.. code-block:: python

    @domain.aggregate
    class Person:
        name = String(max_length=255)
        email = String(unique=True)

This is enforced by entity validation. If you try to save an entity with a duplicate value in a ``unique`` field, a :ref:`ValidationError` will be raised::

    >>> p1 = Person(name='John Doe', email='john.doe@example.com')
    >>> domain.repository_for(Person).add(p1)
    >>> p2 = Person(name= 'Jane Doe', email='john.doe@example.com')
    >>> domain.repository_for(Person).add(p2)
    ValidationError                           Traceback (most recent call last)
    ...
    ValidationError: {'email': ["Person with email 'john.doe@example.com' is already present."]}

choices
~~~~~~~

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

referenced_as
~~~~~~~~~~~~~

.. //FIXME Pending Documentation

TO BE DOCUMENTED

validators
~~~~~~~~~~

A list of validators to run for this field. See :ref:`Validators API Documentation <validators>`  for more information.

error_messages
~~~~~~~~~~~~~~

If supplied, the default messages that the field will raise will be overridden. Error message keys include **required**, **invalid**, **unique**, and **invalid_choice**. Additional error message keys are specified for each field in the :ref:`Field types` section below.

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

Field Types
------------

String
~~~~~~

A string field, for small- to large-sized strings. For large amounts of text, use :ref:`Text`.

``String`` has two optional extra arguments:

- ``max_length``: The maximum length (in characters) of the field, enforced during validation using :ref:`MaxLengthValidator`. Defaults to 255.
- ``min_length``: The minimum length (in characters) of the field, enforced during validation using :ref:`MaxLengthValidator`.

Text
~~~~

A large text field, to hold large amounts of text. Text fields do not have size constraints.

Integer
~~~~~~~

An integer. It uses :ref:`MinValueValidator` and :ref:`MaxValueValidator` to validate the input based on the values that the default database supports.

``Integer`` has two extra optional arguments:

- ``max_value``: The maximum numeric value of the field, enforced during validation using :ref:`MaxValueValidator`.
- ``min_value``: The minimum numeric value of the field, enforced during validation using :ref:`MinValueValidator`.

Float
~~~~~

A floating-point number represented in Python by a float instance.

``Float`` has two extra arguments:

- ``max_value``: The maximum numeric value of the field, enforced during validation using :ref:`MaxValueValidator`.
- ``min_value``: The minimum numeric value of the field, enforced during validation using :ref:`MinValueValidator`.

Boolean
~~~~~~~

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

List
~~~~

Set
~~~

Dict
~~~~

Auto
~~~~

Identifier
~~~~~~~~~~

CustomObject
~~~~~~~~~~~~

Method
~~~~~~

Nested
~~~~~~

Date
~~~~

DateTime
~~~~~~~~

Associations
------------


Embedded Fields
---------------
