.. _logging:

=======
Logging
=======

Loggers
=======

Protean provides several built-in loggers.

.. _logging-protean:

``protean``
^^^^^^^^^^^

The catch-all logger for messages in the protean hierarchy. No messages are posted using this name but instead using one of the loggers below.

.. _logging-protean-domain:

``protean.domain``
^^^^^^^^^^^^^^^^^^

Log messages related to the core domain functionality defined as part of Aggregates, Entities, Value Objects, Domain Services or Domain Events.

.. _logging-protean-application:

``protean.application``
^^^^^^^^^^^^^^^^^^^^^^^

Log messages related to the code in application layer, defined as part of Application Services.

.. _logging-protean-repository:

``protean.repository``
^^^^^^^^^^^^^^^^^^^^^^

Log messages related to the repository layer. If `DEBUG` is set to True, log messages with metrics related to queries are logged.

.. _logging-protean-domain-event:

``protean.event``
^^^^^^^^^^^^^^^^^^^^^^^^

Log messages related to publishing, subscribing and processing of Domain Events.
