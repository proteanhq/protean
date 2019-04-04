.. _queryset:

Querying
--------

Retrieving objects
~~~~~~~~~~~~~~~~~~

To retrieve objects, construct a QuerySet on your entity class.

A QuerySet represents a collection of items from your database. It can have zero, one or many filters. Filters narrow down the query results based on the given parameters.

You get a QuerySet by using your Entity class, like so:

.. code-block:: python

    >>> Customer.query
        <QuerySet: entity: Customer, criteria: ...>
    >>> c = Customer(firstname='John', lastname='Doe')
    >>> c.query
    Traceback:
        ...
    AttributeError: 'Customer' object has no attribute 'query'

In the above example, you get an error if you try to access a QuerySet on an instance, because queries make sense only at the Entity level, where there are multiple items and you are filtering among them. To reiterate, a QuerySet is accessible only via the Entity class.

Retrieving all objects
~~~~~~~~~~~~~~~~~~~~~~

The simplest way to retrieve all items of an Entity is to get all of them. To do this, use the all() method on a QuerySet:

.. code-block:: python

    >>> all_customers = Customer.query.all()

The :ref:`api-queryset-all` method returns all items in the database.
