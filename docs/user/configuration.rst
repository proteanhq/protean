.. _configuration:

====================
Domain Configuration
====================

Domains eventually will need some kind of configuration. Apart from behavior, you might also want to change settings based on your application environment like toggle the debug mode, specify the database to connect to, set the secret key and assign other environment specific parameters.

You typically supply the configuration as close to your application's entry point, right before when the domain's object graph is constructed. You can start initially by hard coding the configuration in your code, which is fine for small applications, but you will want to maintain a separate configuration file as your application grows.

Independent of how you load your config, there is a config object available which holds the loaded configuration values: The config attribute of the :ref:`api-domain` object. This is the place where Domain itself puts certain configuration values and also where plugins can put their configuration values. But this is also where you can have your own configuration.

.. note:: Protean's configuration module is heavily inspired by the marvelous *Flask application framework*. If you have worked with Flask before, you will feel right at home.

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
        SEND_EMAIL=True
    )

Environment and Debug Features
==============================

The ENV and DEBUG config values are special because they may behave inconsistently if changed after the domain has begun constructing the object graph. In order to set the environment and debug mode reliably, Protean uses environment variables.

The environment is used to indicate to Protean, its extensions, and other programs, what context Protean is running in. It is controlled with the PROTEAN_ENV environment variable and defaults to production.

Setting PROTEAN_ENV to development will enable debug mode. To control this separately from the environment, use the PROTEAN_DEBUG flag.

Builtin Configuration Parameters
================================

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

    Whether debug mode is enabled. This is enabled when ENV is `development`
    and is overridden by the `PROTEAN_DEBUG` environment variable.
    It may not behave as expected if set in code.

    ***Do not enable debug mode when deploying in production.***

    Default: ``True``

.. py:data:: AGGREGATE_CHILDREN_LIMIT

    The default number of entity objects to fetch from the underlying data store
    when loaded via the aggregate.

    Default: ``100``

.. py:data:: IDENTITY_STRATEGY

    What Strategy to use generate Unique Identifiers.

    Options:

    * **UUID**: Use ``UUID4`` generated identifiers. This is the preferred strategy.
    * **DATABASE**: Use a database sequence to gather unique identifiers. The Database Sequence is specified as part of the Entity's ``Meta`` information.
    * **FUNCTION**: Use a function to generate a unique identifier. The function name needs to be supplied to the ``IDENTITY_FUNCTION`` parameter.

    Options are defined in :ref:`identity`.

    Default: ``IdentityStrategy.UUID``

.. py:data:: DATABASES

    Protean allows you to specify the database provider you want to use with your application. By virtue of using a Ports and Adapters architecture, you can switch between databases at any time, and your application should work seamlessly.

    By default, Protean is packaged with a :ref:`implementation-in-memory-database` that works perfectly well in development environments and within a single bounded context. But it is recommended to use full-fledged database providers in production and for large scale deployments. Protean comes with built-in support for SQLAlchemy and Elasticsearch, but you can easily extend the mechanism to support your :ref:`own broker<plugin-database>`.

    Default:

    .. code-block:: json

        {
            "default": {
                "PROVIDER": "protean.impl.repository.dict_repo.DictProvider"
            }
        }

.. py:data:: BROKERS

    Protean uses Message Brokers for publishing and propogating Domain events within and across Bounded Contexts.

    By default, Protean is packaged with a :ref:`in-memory-broker` that works perfectly well in development environments and within a single bounded context. But it is recommended to use full-fledged message brokers in production and for large scale deployments. Protean comes with built-in support for RabbitMQ and Redis, but you can easily extend the mechanism to support your :ref:`own broker<plugin-broker>`.

    Options:

    * **INMEMORY**: default. Use Protean's in-built message broker for development and testing purposes.
    * **RABBITMQ**: Use RabbitMQ as the message broker
    * **REDIS**: Use Redis' PubSub infrastructure as the message broker

    Options are defined in :ref:`api-brokers`.

    Default: ``BaseBroker.INMEMORY``

Configuring from Files
======================

Configuration is easier and more manageable if you can store it in a separate file, ideally located outside the actual application package. This makes packaging and distributing your application possible via various package handling tools and finally modifying the configuration file afterwards.

A common pattern is this:

.. code-block:: python

    domain = Domain(__name__)
    domain.config.from_object('yourapplication.default_settings')
    domain.config.from_envvar('YOURAPPLICATION_SETTINGS')

This first loads the configuration from the *yourapplication.default_settings* module and then overrides the values with the contents of the file the **YOURAPPLICATION_SETTINGS** environment variable points to. This environment variable can be set on Linux or OS X with the export command in the shell before starting the server:

.. code-block:: shell

    $ export YOURAPPLICATION_SETTINGS=/path/to/settings.cfg
    $ python load-domain.py

The configuration files themselves are actual Python files. Only values in uppercase are actually stored in the config object later on. So make sure to use uppercase letters for your config keys.

Here is an example of a configuration file:

.. code-block:: python

    # Example configuration
    DEBUG = False
    SECRET_KEY = b'this-is-a-secret'

Make sure to load the configuration very early on, so that extensions have the ability to access the configuration when starting up. There are other methods on the config object as well to load from individual files. For a complete reference, read the :ref:`api-config` object’s documentation.

You can also use files formatted in `json` for configuration purposes, with the help of `from_json` method:

.. code-block:: python

    domain.config.from_json('root_dir/domain.json')

Or you can use a dictionary object directly using the `from_mapping` method. Not that items with non-upper keys are ignored.

.. code-block:: python

    domain.config.from_mapping({"SECRET_KEY": "Secret123", "DEBUG": True})

Configuring from Environment Variables
======================================

In addition to pointing to configuration files using environment variables, you may find it useful (or necessary) to control your configuration values directly from the environment.

Environment variables can be set on Linux or OS X with the export command in the shell before starting the server:

.. code-block:: shell

    $ export SECRET_KEY='tddmue!3k8DFv^5T'
    $ export ADMIN_EMAIL='admin@mycompany.com'

While this approach is straightforward to use, it is important to remember that environment variables are strings – they are not automatically deserialized into Python types.

Here is an example of a configuration file that uses environment variables:

.. code-block:: python

    import os

    _admin_email = os.environ.get("ADMIN_EMAIL", default="true")
    ADMIN_EMAIL = _admin_email.lower()

    SECRET_KEY = os.environ.get("SECRET_KEY")

    if not SECRET_KEY:
        raise ValueError("No SECRET_KEY configured")

Make sure to load the configuration very early on, so that extensions have the ability to access the configuration when starting up. There are other methods on the config object as well to load from individual files. For a complete reference, read the :ref:`api-config` object’s documentation.

Configuring for Tests
=====================

If you are using Pytest for your test framework, you can create a test domain fixture and reuse it throughout your test base. Typically, such a domain fixture would be a scoped to a `function` so that it can be used in all kinds of test scenarios.

.. code-block:: python

    @pytest.fixture(autouse=True)
    def test_domain(request):
        domain = initialized_domain(request)
        logging.config.dictConfig(domain.config['LOGGING_CONFIG'])

        with domain.domain_context():
            yield domain

.. _config-dev-prod:

Cofigurations for different environments
========================================

Most applications need more than one configuration. At the very minimum, there are separate configurations for the production server and for development. The easiest way to handle this is to use a default configuration that is always loaded and part of the version control, and a separate configuration that overrides the values as necessary as mentioned in the example above:

.. code-block:: python

    domain = Domain(__name__)
    domain.config.from_object('yourapplication.default_settings')
    domain.config.from_envvar('YOURAPPLICATION_SETTINGS')

Then you just have to add a separate `config.py` file and export `YOURAPPLICATION_SETTINGS=/path/to/config.py` and you are done. However there are alternative ways as well. For example, you could use imports or subclassing.

An interesting pattern is also to use classes and inheritance for configuration:

.. code-block:: python

    class Config(object):
        DEBUG = False
        TESTING = False
        DATABASE_URI = 'sqlite:///:memory:'

    class ProductionConfig(Config):
        DATABASE_URI = 'mysql://user@remote.server/foo'

    class DevelopmentConfig(Config):
        DEBUG = True

    class TestingConfig(Config):
        TESTING = True
        DATABASE_URI = 'mysql://user@localhost/foo'

To enable such a config you just have to call into `from_object` method:

.. code-block:: python

    domain.config.from_object('configmodule.ProductionConfig')

Note that from_object() does not instantiate the class object. If you need to instantiate the class, such as to access a property, then you must do so before calling from_object():

.. code-block:: python

    from configmodule import ProductionConfig
    domain.config.from_object(ProductionConfig())

    # Alternatively, import via string:
    from werkzeug.utils import import_string
    cfg = import_string('configmodule.ProductionConfig')()
    domain.config.from_object(cfg)

Instantiating the configuration object allows you to use @property in your configuration classes:

.. code-block:: python

    class Config(object):
        """Base config, uses staging database server."""
        DEBUG = False
        DB_SERVER = '192.168.1.56'

        @property
        def DATABASE_URI(self):         # Note: all caps
            return 'mysql://user@{}/foo'.format(self.DB_SERVER)

    class ProductionConfig(Config):
        """Uses production database server."""
        DB_SERVER = '192.168.19.32'

    class DevelopmentConfig(Config):
        DB_SERVER = 'localhost'
        DEBUG = True

    class TestingConfig(Config):
        DB_SERVER = 'localhost'
        DEBUG = True
        DATABASE_URI = 'sqlite:///:memory:'

There are many different ways and it’s up to you how you want to manage your configuration files. However here's a list of good recommendations:

* Keep a default configuration in version control. Either populate the config with this default configuration or import it in your own configuration files before overriding values.
* Use an environment variable to switch between the configurations. This can be done from outside the Python interpreter and makes development and deployment much easier because you can quickly and easily switch between different configs without having to touch the code at all. If you are working often on different projects, you can even create your own script for sourcing that activates a virtualenv and exports the development configuration for you.
