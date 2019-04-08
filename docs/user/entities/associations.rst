.. _entity-associations:

Associations
------------

Protean requires that relationships between Entities be explicitly defined, including their direction. It has three available options as of now: ``Reference``, ``HasOne`` and ``HasMany``.

``Reference``
~~~~~~~~~~~~~

When you have a **Foriegn Key** type of relationship to be established on an Entity, which translates to having a concrete attribute within the Entity, use a **Reference** field. You use it just like any other Field type: by including it as a class attribute of your model.

Reference requires a positional argument: the other Entity to be linked to.

or example, if a Booking has an Airline – that is, an Airline can have multiple Bookings but each Booking only has one Airline – use the following definitions:

.. code-block:: python

    from protean.core.entity import Entity
    from protean.core import field

    class Airline(Entity):
        ...

    class Booking(Entity):
        airline = field.Reference(Airline)
        ...

You should preferably name the Reference field (`airline` in the example above) be the name of the linked entity, lowercase. But you can call the field whatever you want. For example:

.. code-block:: python

    class Booking(Entity):
        air_service = field.Reference(Airline)
        ...

``HasMany``
~~~~~~~~~~~

A ``HasMany`` relationship is the exact opposite of a ``Reference``. So from the example above, since Airlines can have multiple Bookings:

.. code-block:: python

    from protean.core.entity import Entity
    from protean.core.field import Reference
    from protean.core.field.association import HasMany

    class Airline(Entity):
        ...
        bookings = HasMany(Booking)

    class Booking(Entity):
        airline = Reference(Airline)
        ...

Note that ``HasMany`` is a soft relationship, meaning that there are no attributes stored as part of the Airline Entity. The data in the attribute is populated Just-In-Time on access, and cached for further access.

``HasOne``
~~~~~~~~~~

A ``HasOne`` relationship is similar to ``HasMany`` except that the relationship is a one on one relationship. In the same line as previous examples, let's say each booking is associated with a single payment record. You would then define the relationship thus:

.. code-block:: python

    from protean.core.entity import Entity
    from protean.core.field import Reference
    from protean.core.field.association import HasMany

    class Booking(Entity):
        airline = Reference(Airline)
        payment = HasOne(Payment)
        ...

    class Payment(Entity):
        ...
        airline = Reference(Airline)

Just like ``HasMany``, ``HasOne`` is a soft relationship.
