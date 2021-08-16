Configuration Handling
======================

Protean provides a plethora of knobs to control your application behavior in runtime. They range from application
internals, like choosing an Identity Type (UUID, Integer, or Database-supplied), to technology components, like
database to use. You specify these options as configuration settings.

You would typically supply the configuration when the application starts up. The configuration can be provided in
multiple formats as we will see below. You can even hard-code the configuration in your application code, though
it is not recommended for obvious reasons.

Independent of how you load your config, there is a config object available which holds the loaded configuration
values: The :attr:`~protean.Domain.config` attribute of the :class:`~protean.Domain` object.  This is the place
where Protean itself puts certain configuration values and also where adapters can put their configuration values.

Configuration Basics
--------------------

The :attr:`~protean.Domain.config` is actually a subclass of a dictionary and
can be modified just like any dictionary::

    domain = Domain(__name__)
    domain.config['TESTING'] = True

Certain configuration values are also forwarded to the
:attr:`~protean.Domain` object so you can read and write them from there::

    app.testing = True

To update multiple keys at once you can use the :meth:`dict.update` method::

    app.config.update(
        TESTING=True,
        SECRET_KEY=b'6@BGQz^i6bpa3dA'
    )

Builtin Configuration Values
----------------------------

The following configuration values are used internally by Protean:

.. py:data:: ENV

    What environment the app is running in. Protean and extensions may
    enable behaviors based on the environment, such as enabling debug
    mode. The :attr:`~protean.domain.Domain.env` attribute maps to this config
    key. This is set by the :envvar:`PROTEAN_ENV` environment variable and
    may not behave as expected if set in code.

    **Do not enable development when deploying in production.**

    Default: ``'production'``

.. py:data:: DEBUG

    Whether debug mode is enabled. This is enabled when ENV is ``development``
    and is overridden by the ``PROTEAN_DEBUG`` environment variable.
    It may not behave as expected if set in code.

    ***Do not enable debug mode when deploying in production.***

    Default: ``True``

.. py:data:: IDENTITY_STRATEGY

    What Strategy to use generate Unique Identifiers.

    Options:

    * ``UUID``: Use ``UUID4`` generated identifiers. This is the preferred strategy.
    * ``DATABASE``: Use a database sequence to gather unique identifiers. The Database Sequence is specified as part of the Entity's ``Meta`` information.
    * ``FUNCTION``: Use a function to generate a unique identifier. The function name needs to be supplied to the ``IDENTITY_FUNCTION`` parameter.

    Options are defined in :ref:`identity`.

    Default: ``UUID``

.. py:data:: IDENTITY_TYPE

    The type of value acting as the identifier for the domain. Can be among ``INTEGER``, ``STRING``, or ``UUID``.

.. py:data:: DATABASES

    Protean allows you to specify the database provider for your application. By virtue of using a Ports and Adapters architecture, you can switch between databases at any time, and your application should work seamlessly.

    By default, Protean is packaged with a :ref:`implementation-in-memory-database` that works perfectly well in testing environments, within a single bounded context. But it is recommended to use durable database providers in production and for large scale deployments. Protean comes with built-in support for SQLAlchemy and Elasticsearch, but you can easily extend the mechanism to support your :ref:`own provider<adapter-database>`.

    Default:

    .. code-block:: json

        {
            "default": {
                "PROVIDER": "protean.impl.repository.dict_repo.DictProvider"
            }
        }

.. py:data:: BROKERS

    Protean uses Message Brokers for publishing and propagating events within and across Bounded Contexts.

    By default, Protean is packaged with a :ref:`inline-broker` that is sufficient in a development environment, within a single bounded context. But it is recommended to use full-fledged message brokers in production and for large scale deployments. Protean comes with built-in support Redis, but you can easily extend the mechanism to support your :ref:`own broker<adapter-broker>`.

    Options:

    * ``INLINE``: default. Use Protean's in-built message broker for development and testing purposes.
    * ``REDIS``: Use Redis PubSub infrastructure as the message broker

    Options are defined in :ref:`api-brokers`.

    Default:

    .. code-block:: json

        {
            "default": {
                "PROVIDER": "protean.adapters.InlineBroker"
            }
        }

.. py:data:: EVENT_STRATEGY

    The event processing strategy to use. Read :ref:`event-processing-strategies` for a detailed discussion.

Configuring from Python Files
-----------------------------

You can supply configuration as separate files, ideally located outside the actual application package. This makes
packaging and distributing the application possible via various package handling tools (:doc:`/patterns/distribute`).

So a common pattern is this::

    domain = Domain(__name__)
    domain.config.from_object('mydomain.default_settings')
    domain.config.from_envvar('MYDOMAIN_SETTINGS')

This first loads the configuration from the `mydomain.default_settings` module and then overrides the values
with the contents of the file the :envvar:`MYDOMAIN_SETTINGS` environment variable points to. This environment
variable can be set in the shell before starting the server:

The configuration files themselves are actual Python files.  Only values in uppercase are actually stored in the
config object later on.  So make sure to use uppercase letters for your config keys.

Here is an example of a configuration file::

    # Example configuration
    SECRET_KEY = b'secret-key'

Make sure to load the configuration very early on, so that both the domain and its adapters have the ability to access the configuration when starting up.  There are other methods on the config object as well to load from individual files.  For a complete reference, read the :class:`~protean.Config` object's documentation.

Configuring from Data Files
---------------------------

It is also possible to load configuration from a file in a format of your choice using
:meth:`~protean.Config.from_file`. For example to load from a TOML file:

.. code-block:: python

    import toml
    domain.config.from_file("config.toml", load=toml.load)

Or from a JSON file:

.. code-block:: python

    import json
    domain.config.from_file("config.json", load=json.load)

Configuring from Environment Variables
--------------------------------------

In addition to pointing to configuration files using environment variables, you may find it useful (or necessary) to
control your configuration values directly from the environment.

Environment variables can be set in the shell before starting the server.

.. tabs::

   .. group-tab:: Bash

      .. code-block:: text

         $ export SECRET_KEY="secret-key"
         $ protean server
          * Server started

   .. group-tab:: CMD

      .. code-block:: text

         > set SECRET_KEY="secret-key"
         > protean server
          * Server started

   .. group-tab:: Powershell

      .. code-block:: text

         > $env:SECRET_KEY = "secret-key"
         > protean server
          * Server started

While this approach is straightforward to use, it is important to remember that environment variables are strings --
they are not automatically deserialized into Python types.

Here is an example of a configuration file that uses environment variables::

    import os

    _mail_enabled = os.environ.get("MAIL_ENABLED", default="true")
    MAIL_ENABLED = _mail_enabled.lower() in {"1", "t", "true"}

    SECRET_KEY = os.environ.get("SECRET_KEY")

    if not SECRET_KEY:
        raise ValueError("No SECRET_KEY set supplied")


Notice that any value besides an empty string will be interpreted as a boolean ``True`` value in Python, which
requires care if an environment explicitly sets values intended to be ``False``.

There are other methods on the config object as well to load from individual files.  For a complete
reference, read the :class:`~protean.Config` class documentation.


Development / Production
------------------------

Most applications need more than one configuration.  There should be at least separate configurations for the
production server and the one used during development.  The easiest way to handle this is to use a default
configuration that is always loaded and part of the version control, and a separate configuration that overrides the
values as necessary as mentioned in the example above::

    domain = Domain(__name__)
    domain.config.from_object('mydomain.default_settings')
    domain.config.from_envvar('MYDOMAIN_SETTINGS')

Then you just have to add a separate :file:`config.py` file and export ``MYDOMAIN_SETTINGS=/path/to/config.py`` and
you are done.  However there are alternative ways as well.  For example you could use imports or subclassing.

What is very popular in the Django world is to make the import explicit in the config file by adding ``from mydomain.
default_settings import *`` to the top of the file and then overriding the changes by hand. You could also inspect
an environment variable like ``MYDOMAIN_MODE`` and set that to `production`, `development` etc. and import different
hard-coded files based on that.

An interesting pattern is also to use classes and inheritance for configuration::

    class Config(object):
        TESTING = False

    class ProductionConfig(Config):
        MAIL_ENABLED = True

    class DevelopmentConfig(Config):
        MAIL_ENABLED = False

    class TestingConfig(Config):
        MAIL_ENABLED = False
        TESTING = True

To enable such a config you just have to call into :meth:`~domain.Config.from_object`::

    domain.config.from_object('config.ProductionConfig')

Note that :meth:`~protean.Config.from_object` does not instantiate the class object. If you need to instantiate the
class, such as to access a property, then you must do so before calling :meth:`~protean.Config.from_object`::

    from config import ProductionConfig
    domain.config.from_object(ProductionConfig())

    # Alternatively, import via string:
    from werkzeug.utils import import_string
    cfg = import_string('config.ProductionConfig')()
    domain.config.from_object(cfg)

Instantiating the configuration object allows you to use ``@property`` in your configuration classes::

    class Config(object):
        """Base config, uses staging database server."""
        TESTING = False
        POSTGRES_SERVER = 'example.com'

        @property
        def DATABASE_URI(self):  # Note: all caps
            return f"postgresql://postgres:postgres@{self.POSTGRES_SERVER}:5432/postgres"

    class ProductionConfig(Config):
        """Uses production database server."""
        POSTGRES_SERVER = 'mydomain.com'

    class DevelopmentConfig(Config):
        POSTGRES_SERVER = 'localhost'

    class TestingConfig(Config):
        POSTGRES_SERVER = 'test.dev'
        DATABASE_URI = 'sqlite:///:memory:'

There are many different ways and it's up to you how you want to manage your configuration files.  However here are a
few good recommendations:

-   Keep a default configuration in version control.  Either populate the config with this default configuration or
    import it in your own configuration files before overriding values.
-   Use an environment variable to switch between the configurations.
    This can be done from outside the Python interpreter and makes development and deployment much easier because
    you can quickly and easily switch between different configs without having to touch the code at all.  If you are
    working often on different projects you can even create your own script for sourcing that activates a virtualenv
    and exports the development configuration for you.
