.. _advanced:

Advanced Usage
==============

Retrieving Objects
------------------

Protean supports a rich query syntax to dynamically find and filter objects in a repository. You
can populate the search criteria into a :class:`protean.core.entity.QuerySet` object.

Retrieving all objects
^^^^^^^^^^^^^^^^^^^^^^

It all starts with the `query` object of an Entity. Use the
:func:`protean.core.entity.QuerySet.all` method on a new or empty QuerySet to retrieve all objects
in the repository::

    Dog.query.all()

Retrieving specific Objects with Filters
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The QuerySet returned by all() describes all objects in the database table. But you usually want
to filter and extract a specific subset of objects from the total pool.

To create such a subset, you refine the initial QuerySet, adding filter conditions. The two most
common ways to refine a QuerySet are:

``filter(**kwargs)``
~~~~~~~~~~~~~~~~~~~~

Returns a new QuerySet containing objects that match the given one or more criteria::

    Dog.query.filter(age=3)
    Dog.query.filter(age=3, owner='John')

``exclude(**kwargs)``
~~~~~~~~~~~~~~~~~~~~~

Returns a new QuerySet containing objects that do not match the given parameters::

    Dog.query.exclude(age=4)

Chaining Filters
^^^^^^^^^^^^^^^^

The result of refining a QuerySet is itself a QuerySet, so it’s possible to chain filter method
calls together. For example::

    Dog.query.filter(age=3).exclude(owner='John')

You can also order the result set by one or more columns::

    Dog.query.filter(age=3).order_by('name')
    Dog.query.filter(age=3).order_by(['name', 'owner'])

You can also customize query preferences and specify how many records you want to fetch at a time
or how much you want to offset the search by::

    Dog.query.filter(age=3).order_by('name').paginate(per_page=25)
    Dog.query.filter(age=3).order_by('name').paginate(per_page=25, page=3)

Lazy Fetch
^^^^^^^^^^

Creating a `QuerySet` object does not fire a query immediately on underlying repositories. Results
are lazy-fetched just in time, only when the queryset is evaluated in one of the following ways:

* **iteration**: A QuerySet is iterable, and it executes the database query the first time you iterate over it. For example, this will print the name of all dogs in the repository::

    for dog in Dog.query.all():
        print(dog.name)

* **Slicing**: A QuerySet can be sliced, using Python’s array-slicing syntax. Slicing a QuerySet returns a list of objects in the defined range.

* **len()**: A QuerySet is evaluated when you call len() on it, returning the length of the result set.

* **list()**: Force evaluation of a QuerySet by calling list() on it results in it getting evaluated::

    dog_list = list(Dog.query.all())

* **bool()**: Testing a QuerySet in a boolean context, such as using bool(), or, and or an if statement, will cause the query to be executed. If there is at least one result, the QuerySet is True, otherwise False. 
