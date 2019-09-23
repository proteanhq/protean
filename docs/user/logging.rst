.. _logging:

=======
Logging
=======

Protean uses Python’s builtin logging module to perform system logging. The usage of this module is discussed in detail in Python’s own documentation.

By default, the LOGLEVEL in Protean is set to INFO. But it's straightforward to customize as per your application's needs. A typical logging config would look like this:

.. code-block::

    LOGGING_CONFIG = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'console': {
                'format': '%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
            }
        },
        'handlers': {
            'console': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
                'formatter': 'console',
            }
        },
        'loggers': {
            'protean': {
                'handlers': ['console'],
                'level': 'DEBUG',
            },
            'vfc': {
                'handlers': ['console'],
                'level': 'DEBUG',
            }
        }
    }

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
