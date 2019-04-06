.. _entity-queryset-caching:

Caching
~~~~~~~

Each QuerySet maintains an internal cache that is filled with data from database after evaluation.

When a QuerySet is newly created, the cache is empty. The first time a QuerySet is evaluated, meaning data is fetched from database, query results are saved into QuerySet's cache. The called method then returns the results explicitly requested, like a particular item in the result set or the next item being iterated over. Subsequent evaluations of the QuerySet reuse the cached results.

This behavior becomes important, if you are querying the same datasource multiple times during a process. For example, in the example below, querysets are dynamically created, evaluated and discarded:

.. code-block:: python

    >>> print([customer.firstname for customer in Customer.query.all()])
    >>> print([customer.firstname for customer in Customer.query.all()])

The same database query is executed twice unnecessarily. There is also no guarantee that the same result set was retrieved the second time over, because the underlying data in the database may have changed.

To make use of caching, just use the same QuerySet object:

.. code-block:: python

    >>> query = Customer.query.all()
    >>> print([customer.firstname for customer in query])
    >>> print([customer.lastname for customer in query])

In this case, once the results are fetched after the first evaluation, they are reused during the second iteration.
