.. _entity-queryset:

Querying
--------

To retrieve items from your database, construct a QuerySet through the ``query`` object on your Entity class. A QuerySet represents a collection of objects from your database. It can have zero, one or many filters. Filters narrow down the query results based on the given criteria.

You can access the queryset object directly via the Entity class, like so:

.. code-block:: python

    >>> Customer.query
    <QuerySet: entity: Customer, criteria: ('protean.utils.query.Q', (), {}), ...>

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

The most straightforward way to retrieve objects of a particular Entity type from a database is to get all of them. You can use the :ref:`api-queryset-all` method on a QuerySet:

.. code-block:: python

    >>> all_customers = Customer.query.all()

The :ref:`api-queryset-all` method returns all items in the database.

Retrieving specific objects with filters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To retrieve a subset of objects in the database, you would apply filter criteria on a QuerySet. The two most common ways to define the criteria are:

``filter(*args, **kwargs)``
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Returns a new :ref:`api-queryset` object containing items that match the given criteria.

.. code-block:: python

    >>> Customer.query.filter(lastname='Doe')

``exclude(*args, **kwargs)``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Returns a new :ref:`api-queryset` object containing items that do **NOT** match the given criteria.

.. code-block:: python

    >>> Customer.query.exclude(firstname='John')

The criteria supplied to these methods should be in the format described in :ref:`entity-queryset-field-lookups`.

QuerySet Properties
~~~~~~~~~~~~~~~~~~~

Chainability
^^^^^^^^^^^^

These methods return a new :ref:`api-queryset`, so it is possible to chain criteria together. For example:

.. code-block:: python

    >>> Customer.query.filter(lastname='Doe').exclude(firstname='John')

Immutability
^^^^^^^^^^^^

Each time you refine a **QuerySet**, you get a brand-new QuerySet that is independent of the previous **QuerySet** but carries forward the filter criteria built so far. Each refinement creates a separate and distinct QuerySet that can be stored, used and reused.

.. code-block:: python

    >>> query1 = Customer.query.filter(firstname='John')
    >>> query2 = query1.filter(date_of_birth__gte=datetime.date.today() - relativedelta(years=35))
    >>> query3 = query2.exclude(countrycode='US')
    >>> assert query1 != query2 != query3
    >>> young_johns_outside_us = query3.all()

Lazy Evaluation
^^^^^^^^^^^^^^^

Querysets are not evaluated on creation. You can refine criteria in multiple passes, stacking up filters in the final queryset object, before calling for an evaluation and fetching results. 

You can evaluate a **QuerySet** in the following ways:

* Iteration: A **QuerySet** is iterable, and it executes its database query the first time you iterate over it.

.. code-block:: python

    for customer in Customer.query.all():
        print(customer.firstname)

* Slicing: A **QuerySet** can be sliced, using Python's array-slicing syntax. Slicing an unevaluated **QuerySet** usually returns another unevaluated QuerySet, but the database query will be executed if you use the "step" parameter of slice syntax, and will return a list. Slicing a QuerySet that has been evaluated also returns a list.

* **len()**: A **QuerySet** is evaluated when you call len() on it, returning the length of the result set.

* list(): Explicitly calling **list()** on a **QuerySet** object forces its evaluation:

.. code-block:: python

    johns = list(Customer.query.filter(firstname='John'))

* bool(): Testing a **QuerySet** in a boolean context, such as using **bool()**, **or**, **and** or an **if** statement will cause it to be executed. If there is at least one result, the **QuerySet** is **True**, otherwise **False**.

.. code-block:: python

    if Customer.query.filter(firstname='John'):
        print("Customers with Firstname `John` found")

You get the same effect if you were calling :ref:`api-entity-exists` on the Entity with filter criteria.

Raw Queries
~~~~~~~~~~~

*<TO BE DOCUMENTED>*
