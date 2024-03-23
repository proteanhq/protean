Event Sourcing
==============

You can choose to store all application data in the form of events. Event sourcing persists the state of a business entity such an Order or a Customer as a sequence of state-changing events. Whenever the state of a business entity changes, a new event is appended to the list of events.

You can use Event-Sourced Aggregates to represent such business entities that are backed by an event store.

Event-Sourced Aggregates
------------------------

Event-Sourced Aggregates are defined with the :meth:`~protean.Domain.event_sourced_aggregate` decorator:

.. code-block:: python

    from protean.domain import Domain
    from protean.fields import Date, String

    identity = Domain(__name__)

    @identity.event_sourced_aggregate
    class User:
        first_name = String(max_length=50)
        email = String(required=True)
        joined_on = Date()

Similar to Aggregates, an Identifier field named `id` is made available in the aggregate if no identifier fields are explicitly provided.

Storing Events
--------------

Event-Sourced Aggregates raise events as part of their processing, with the `raise_` method:

.. code-block:: python
    :emphasize-lines: 12

    from my_app.domain import identity

    @identity.event_sourced_aggregate
    class User:
        first_name = String(max_length=50)
        email = String(required=True)
        joined_on = Date()

        @classmethod
        def register(cls, email, password):
            user = cls(email=email, password=password)
            user.raise_(Registered(email=email, password=password))

            return user

Protean provides an In-Memory Event Store for testing purposes, but supports |MessageDB| for development and production environments.

.. // FIXME Add documentation on MessageDB specific characteristics like format of streams, snapshots, etc.

You can configure MessageDB as the Event Store in config:

.. code-block:: python

    EVENT_STORE = {
        "PROVIDER": "protean.adapters.event_store.message_db.MessageDBStore",
        "DATABASE_URI": "postgresql://message_store@localhost:5433/message_store",
    }

You can retrieve the repository for an Event-Sourced Aggregate with `repository_for`:

.. code-block:: python

    >>> from protean.globals import current_domain

    >>> current_domain.repository_for(User)

But unlike Aggregates, there is no way to query records because all data is stored purely in the form of events. The only methods supported by an Event-Sourced Repository are:

#. ``add``

    `add` persists new events to the event store, typically on committing the Unit of Work.

#. ``get``

    `get` rehydrates the aggregate by its ID from the event store and returns the latest snapshot of the aggregate object.

Snapshots
---------

Protean stores regular snapshots of event-sourced aggregates to optimize re-hydration performance. These snapshots are automatically used when repositories retrieve aggregates from the event store.

By default, Protean is configured to store a snapshot after every 10 events. You can customize this interval with the ``SNAPSHOT_THRESHOLD`` config flag:

.. code-block:: python

    # config.py
    class Config:
        SNAPSHOT_THRESHOLD = 25

Optimistic Concurrency
----------------------

All Event-Sourced Aggregates hold a ``_version`` attribute that is used to implement optimistic concurrency controls. The version number is incremented on every new event in the aggregate stream. An aggregate loaded from the event store will hold the latest version number in its ``_version`` attribute.

Each event carries an ``expected_version`` that should match the ``_version`` of the loaded aggregate. If there is a mismatch in the versions, the event is discarded with a ``ExpectedVersionError``.

.. // FIXME Add image depicting Optimistic concurrency at work.

.. |MessageDB| raw:: html

    <a href="http://docs.eventide-project.org/user-guide/message-db/" target="_blank">MessageDB</a>
