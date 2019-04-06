Definition
----------

An Entity represents a Domain Object. It contains one or more groups of attributes related to the domain object and generally maps to well-defined persisted structures in a database.

In short:

* Each entity is a Python class that subclasses ``protean.core.entity.Entity``.
* Each attribute of the entity represents a Data Attribute.
* An Entity can be persisted to a mapped repository during runtime, purely by configurations

Fields
~~~~~~

An Entity typically has one or more attributes associated with it, in the form of Fields. Such fields are typically specified as class attributes and their names cannot clash with published Entity API attributes like `clean`, `save`, or `delete`.

.. code-block:: python

    from protean.core.entity import Entity
    from protean.core import field

    class Customer(Entity):
        firstname = field.String(required=True, max_length=50)
        lastname = field.String(required=True, max_length=50)
        date_of_birth = field.Date()
        ssn = field.String(max_length=50)
        countrycode = field.String(max_length=3)

    class Airline(Entity):
        name = field.String(required=True, max_length=50)

    class Booking(Entity):
        airline = field.Reference(Airline)
        customer = field.Reference(Customer)
        departure = field.DateTime()
        arrival = field.DateTime()

Field Types
^^^^^^^^^^^

Each field in the entity is an instance of a :ref:`api-field` class. The :ref:`api-field` specifies the data type of the attribute value that can be stored, and is also typically associated with pre-built validations to ensure data consistency.

You can customize the behavior of a :ref:`api-field` through many available options listed in :ref:`entity-field`. Protean comes pre-packaged with a built-in field types, listed in the :ref:`api-field` documentation. You can also easily extend the :ref:`api-field` class and write your own implementations; see :ref:`entity-field-custom` for more information.

``Meta`` options
^^^^^^^^^^^^^^^^

Reflection on the Entity's fields and configurations is supported via its ``meta_`` attribute:

.. code-block:: python

    >>> Customer.meta_
    <protean.core.entity.EntityMeta at ...>

    >>> c = Customer(firstname='John', lastname='Doe')
    >>> c.meta_
    <protean.core.entity.EntityMeta at ...>

With the meta object, you can retrieve a dict of all fields associated with the entity through ``declared_fields`` attribute, as well as the field identified as the identifier key for the entity with ``id_field`` attribute.
