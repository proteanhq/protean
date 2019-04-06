.. _entity-lifecycle:

CRUD
----

Once the entities are defined, you can use a database-agnostic API to create, query, update, and delete objects. Let us explore the different options to manage the lifecycle of an Entity.

Throughout this guide, we will refer to the following models as example:

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

Creating Entities
~~~~~~~~~~~~~~~~~

An Entity typically maps to a database schema, and an instance of the entity represents a particular item in the database. The item could be a row in a table if an RDBMS such as MySQL and Postgresql is being used, or a document if its a document-oriented like MongoDB, or a key value pair in a data structure store like Redis.

To create an entity, instantiate it using keyword arguments to the Entity class, then call save() to save it to the database.

Assuming your entities have been defined in app/flight/entities.py, here's an example:

.. code-block:: python

    >>> from flight.entities import Customer
    >>> cust = Customer(firstname='John', lastname='Doe')
    >>> cust.save()

.. seealso:: Refer to :ref:`documentation of save<api-entity-save>` for a list of advanced options that ``save()`` supports.

Once saved, an entity instance will be associated with a unique primary identifier that can be used to retrieve it later.

Retrieving Entities
~~~~~~~~~~~~~~~~~~~

To retrieve an entity by its primary key, you can use the :ref:`api-entity-get` method on the Entity class. Assuming that customer object above was saved with an identifier say 1, you can retrieve the customer object like so:

.. code-block:: python

    >>> old_customer = Customer.get(1)

It is also possible to specify filter criteria to retreive specific sections of items. Refer to :ref:`entity-queryset` documentation for detailed information on constructing such criteria and fetching items.

Updating Entities
~~~~~~~~~~~~~~~~~

If you want to update an object that's already in the database, it's as simple as changing its attributes and calling :ref:`api-entity-save` on the object:

.. code-block:: python

    >>> old_customer.firstname = 'Jane'
    >>> old_customer.save()

You can also do this operation in one step, by supplying the details to be updated to the :ref:`api-entity-update` method:

.. code-block:: python

    >>> old_customer.update(firstname='Jane')

:ref:`api-entity-update` can accept either keyword arguments containing attribute-value pairs, or a dictionary of key-values.

If you want to mass update entities matching a set of criteria, you can call :ref:`api-queryset-update` on a queryset:

.. code-block:: python

    >>> Customer.filter(firstname='John').update(firstname='Jane')

If you wanted to do the same update but without running validations, you can use :ref:`api-queryset-update-all`:

.. code-block:: python

    >>> Customer.filter(firstname='John').update_all(firstname='Jane')

Deleting Entities
~~~~~~~~~~~~~~~~~

To remove items from the database, you can simply call :ref:`api-entity-delete` on the entity instance:

.. code-block:: python

    >>> old_customer.delete()

A call to :ref:`api-entity-delete` returns the deleted entity.

You can also delete entities matching a specific criteria by calling :ref:`api-queryset-delete`:

.. code-block:: python

    >>> Customer.filter(firstname='John').delete()

Note that :ref:`api-queryset-delete` above loops through each entity and calls the ``delete()`` method in each object in order to trigger all validations and callbacks. If you wanted to delete entities without running validations or cascades, you can use :ref:`api-queryset-delete-all`:

.. code-block:: python

    >>> Customer.filter(firstname='John').delete_all()
