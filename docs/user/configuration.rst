.. _configuration:

====================
Domain Configuration
====================

Domains eventually will need some kind of configuration. Apart from behavior, you might also want to change settings based on your application environment like toggling the debug mode, the database URL to connect to, and other environment specific parameters.

You typically supply the configuration as close to your application's entry point, right before when the domain's object graph is constructed. You can start initially by hard coding the configuration in your code, which is fine for small applications, but will want to maintain a separate configuration file as your application grows.

Independent of how you load your config, there is a config object available which holds the loaded configuration values: The config attribute of the :ref:`api-domain` object. This is the place where Domain itself puts certain configuration values and also where plugins can put their configuration values. But this is also where you can have your own configuration.

Basics
======

The ``config`` is actually a subclass of a dictionary can be modified just like any other dictionary:

.. code-block:: python

    from protean.domain import Domain

    domain = Domain(__name__)
    domain.config['DEBUG'] = True

To update multiple keys at once you can use the dict.update() method:

.. code-block:: python

    domain.config.update(
        DEBUG=True,
        TESTING=True
    )

Builtin Configuration Parameters
================================

The following configuration values are used internally by Protean:

.. py:data:: DEBUG

    Whether debug mode is enabled.

    ***Do not enable debug mode when deploying in production.***

    Default: ``True``

.. py:data:: IDENTITY_STRATEGY

    What Strategy to use generate Unique Identifiers.

    Options:

    * **UUID**: Use ``UUID4`` generated identifiers. This is the preferred strategy.
    * **DATABASE**: Use a database sequence to gather unique identifiers. The Database Sequence is specified as part of the Entity's ``Meta`` information.
    * **FUNCTION**: Use a function to generate a unique identifier. The function name needs to be supplied to the ``IDENTITY_FUNCTION`` parameter.

    Options are defined in :ref:`api-identity-strategy`.

    Default: ``IdentityStrategy.UUID``

.. py:data:: BROKERS

    Protean uses Message Brokers for publishing and propogating Domain events within and across Bounded Contexts.

    By default, Protean is packaged with a :ref:`in-memory-broker` that works perfectly well in development environments and within a single bounded context. But it is recommended to use full-fledged message brokers in production and for large scale deployments. Protean comes with built-in support for RabbitMQ and Redis, but you can easily extend the mechanism to support your :ref:`own broker<plugin-broker>`.

    Options:

    * **INMEMORY**: default. Use Protean's in-built message broker for development and testing purposes.
    * **RABBITMQ**: Use RabbitMQ as the message broker
    * **REDIS**: Use Redis' PubSub infrastructure as the message broker

    Options are defined in :ref:`api-brokers`.

    Default: ``BaseBroker.INMEMORY``
