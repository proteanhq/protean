Entity LifeCycle
----------------

Once the entities are defined, you can use a database-agnostic API to create, query, update, and delete objects. Let us explore the different options to manage the lifecycle of an Entity.

Throughout this guide, we will refer to the following models as example:

.. code-block:: python

    from protean.core.entity import Entity

    class Customer(Entity):
        firstname = field.String(required=True, max_length=50)
        lastname = field.String(required=True, max_length=50)
        date_of_birth = field.Date()
        ssn = field.String(max_length=50)

    class Airline(Entity):
        name = field.String(required=True, max_length=50)

    class Booking(Entity):
        airline = field.Reference(Airline)
        customer = field.Reference(Customer)
        departure = field.DateTime()
        arrival = field.DateTime()

Creating objects
~~~~~~~~~~~~~~~~

An Entity typically maps to a database schema, and an instance of the entity represents a particular item in the database. The item could be a row in a table if an RDBMS such as MySQL and Postgresql is being used, or a document if its a document-oriented like MongoDB, or a key value pair in a data structure store like Redis.

To create an entity, instantiate it using keyword arguments to the Entity class, then call save() to save it to the database.

Assuming your entities have been defined in app/flight/entities.py, here's an example:

.. code-block:: python

    >>> from flight.entities import Customer
    >>> cust = Customer(firstname='John', lastname='Doe')
    >>> cust.save()

.. seealso:: Refer to :ref:`documentation of save<api-entity-save>` for a list of advanced options that ``save()`` supports.