.. _entity-queryset-field-lookups:

Field Lookups
-------------

Field lookups are how you specify different comparison operators in criteria supplied to a QuerySet. They’re specified as keyword arguments to the QuerySet methods :ref:`api-queryset-filter` and :ref:`api-queryset-exclude`.

.. // TODO Check if lookups work with `get` method

Basic lookups keyword arguments take the form **fieldname__lookuptype=value**, with a double underscope following the field name. For example:

.. code-block:: python

    >>> Customer.query.filter(date_of_birth__gte=datetime.date.today() - relativedelta(years=35))

This is straightforward for most field lookups, but in the case of :ref:`entity-associations`, you can specify the field name suffixed with the connected key on the other entity. For example, if **airline** is the field defined in **Booking**, connected to **Airline** class **via** the **id** attribute, you can specify **airline_id** as the lookup fieldname.

.. code-block:: python

    >>> Booking.query.filter(airline_id=1)

If a field called **customer** in **Booking** was connected to a **Customer** Entity object via the **email** attribute, then you would specify:

    >>> Booking.query.filter(customer_email='johndoe@domain.com')

Supported Lookups
~~~~~~~~~~~~~~~~~

``exact``
^^^^^^^^^

Exact match (case-sensitive). This is also the default lookup used when no lookup type is provided.

.. // TODO Check if exact works with `None` value

.. code-block:: python

    >>> Customer.query.filter(id__exact=9932)
    >>> Customer.query.filter(lastname__exact='Dorian')
    >>> Customer.query.filter(date_of_birth__exact=None)

``iexact``
^^^^^^^^^^

Case-insensitive exact match.

.. code-block:: python

    >>> Customer.query.filter(lastname__iexact='dorian')
    >>> Customer.query.filter(date_of_birth__iexact=None)

The first query will match 'Dorian', 'dorian', 'DoRiAn', etc.

``contains``
^^^^^^^^^^^^

Case-sensitive containment test.

.. code-block:: python

    >>> Customer.query.filter(firstname__contains='John')

This will match all customers containing the string 'John' in their name, like 'John', 'Johnny', 'Johny' etc., but not 'johny' or 'johnny'.

``icontains``
^^^^^^^^^^^^^

Case-insensitive containment test.

.. code-block:: python

    >>> Customer.query.filter(firstname__icontains='john')

``gt``
^^^^^^

Greater than.

.. code-block:: python

    >>> Customer.query.filter(date_of_birth__gte=datetime.datetime(1985, 10, 5).date())

``gte``
^^^^^^^

Greater than or equal to.

``lt``
^^^^^^

Less than.

.. code-block:: python

    >>> Customer.query.filter(date_of_birth__lte=datetime.datetime.today())

``lte``
^^^^^^^

Less than or equal to.

``in``
^^^^^^

Present in a given iterable, like a list, tuple, and also strings.

.. // TODO Can `in` work with a queryset?
.. // TODO Can `in` work with a string?

.. code-block:: python

    >>> Customer.query.filter(id__in=[234234, 253345, 211234])
