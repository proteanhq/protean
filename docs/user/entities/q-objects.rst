.. _entity-queryset-q-objects:

Complex lookups with Q objects
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Keyword argument queries supplied to methods like :ref:`api-queryset-filter` and :ref:`api-queryset-exclude` are combined together, meaning all criteria need to fulfilled for an item to match. If you need to execute more complex queries, like either one or more of the conditions are satisfied, you can use **Q** objects.

A **Q** object is an object used to combine one or more collections of keyword arguments in different ways. These keyword arguments are specified as in :ref:`entity-queryset-field-lookups`.

For example, this Q object encapsulates an **in** query:

.. code-block:: python

    >>> from protean.utils.query import Q
    >>> Q(id__in=[234234, 253345, 211234])

Q objects can be combined using the & and | operators. When an operator is used on two Q objects, it yields a new Q object.

For example, this statement yields a single Q object that represents the "OR" of two queries:

.. code-block:: python

    >>> from protean.utils.query import Q
    >>> Q(id__in=[234234, 253345, 211234]) | Q(firstname__icontains='John')

You can compose statements of arbitrary complexity by combining Q objects with the & and | operators and use parenthetical grouping. Also, Q objects can be negated using the ~ operator, allowing for combined lookups that combine both a normal query and a negated (NOT) query:

.. code-block:: python

    >>> from protean.utils.query import Q
    >>> (Q(id__in=[234234, 253345, 211234]) | Q(firstname__icontains='John')) & Q(date_of_birth__gte=datetime.date.today() - relativedelta(years=35))

The above query translates to fetching all Customer objects that have their id among 234234, 253345 and 211234, have firstname that contains 'john' (case-insensitive) and who have been born in the last 35 years.

Each lookup function that takes keyword-arguments can also be passed one or more Q objects as positional (not-named) arguments. If you provide multiple Q object arguments to a lookup function, the arguments will be combined together. 

.. code-block:: python

    Customer.query.filter(
        Q(id__in=[234234, 253345, 211234]) | Q(firstname__icontains='John'),
        Q(date_of_birth__gte=datetime.date.today() - relativedelta(years=35))
    )

Lookup functions can mix the use of Q objects and keyword arguments. All arguments provided to a lookup function (be they keyword arguments or Q objects) are “AND”ed together. However, if a Q object is provided, it must precede the definition of any keyword arguments. 

.. code-block:: python

    Customer.query.filter(
        Q(id__in=[234234, 253345, 211234]) | Q(firstname__icontains='John'),
        date_of_birth__gte=datetime.date.today() - relativedelta(years=35)
    )

Note that this query would be equivalent to the example earlier.