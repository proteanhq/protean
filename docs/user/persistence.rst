.. _user-persistence:

===========
Persistence
===========

Once your Entities and Use cases have been defined, and thoroughly tested with the help of in memory databases available out-of-the-box in Protean, you are ready to start mapping entities to underlying data stores. Protean connects these data stores, that are part of the infrastructure, as repositories that back Entities, effectively enabling them to behave like Active Records.

Repositories are defined in the standard configuration file with the following structure:

.. code-block:: python

    DATABASES = {
        'default': {
            'PROVIDER': 'protean.impl.repository.dict_repo.DictProvider'
        }
    }

``DATABASES`` is a dictionary containing the mapping of unique names to underlying repository providers. The example above shows the database definition in a typical Protean application, using ``DictProvider`` - a simply Python Dictionary based data store - as the default provider.

Protean comes with built-in for RDBMS databases supported by the venerable SQLAlchemy ORM are made available with ``protean-sqlalchemy`` plugin. The configuration to use SQLAlchemy plugin would be:

.. code-block:: python

    DATABASES = {
        'default': {
            'PROVIDER': 'protean_sqlalchemy.provider.SAProvider'
        }
    }

.. //FIXME Link to protean-sqlalchemy plugin

You can also specify multiple repositories, when you are persisting your data into different databases, or even different kinds of databases:

.. code-block:: python

    DATABASES = {
        'default': {
            'PROVIDER': 'protean.impl.repository.dict_repo.DictProvider'
        },
        'postgres': {
            'PROVIDER': 'protean_sqlalchemy.provider.SAProvider'
        }
    }

Connection details specific to each type of repository provider can be provided in the configuration as well. For example, to specify a custom connection URL for Postgres, you would define the details as required by SQLAlchemy plugin, like so:

.. code-block:: python

    DATABASES = {
        'default': {
            'PROVIDER': 'protean_sqlalchemy.provider.SAProvider',
            'DATABASE_URI': 'postgresql://master:password@localhost:5432/custom_app'
        }
    }

In case of the default ``DictProvider``, there is no customization of connection necessary, so the configuration entry will simply have nothing other than the ``PROVIDER`` definition.

Note that there should be atleast one repository definition present in the ``DATABASES`` key, with the key as ``default``, otherwise Protean will complain.

Registering Entities
--------------------

You can register an Entity against a specific Provider with the help of ``register`` method:

.. code-block:: python

    from protean.core.repository import repo_factory

    class Account(Entity):
        username = field.String(required=True, unique=True, max_length=50)
        email = field.String(required=True)
        password = field.StringLong(required=True, min_length=6)

    repo_factory.register(Account)

When no specific provider is given, the provider with name ``default`` will be picked automatically.

To specify a specific provider, pass the key that it has been defined with:

.. code-block:: python

    DATABASES = {
        'default': {
            'PROVIDER': 'protean.impl.repository.dict_repo.DictProvider'
        },
        'postgres': {
            'PROVIDER': 'protean_sqlalchemy.provider.SAProvider',
            'DATABASE_URI': 'postgresql://master:password@localhost:5432/custom_app'
        }
    }

.. code-block:: python

    repo_factory.register(Account, 'postgres')

This also means you can have multiple repository definitions for the same kind of database:

To specify a specific provider, pass the key that it has been defined with:

.. code-block:: python

    DATABASES = {
        'default': {
            'PROVIDER': 'protean.impl.repository.dict_repo.DictProvider'
        },
        'primary': {
            'PROVIDER': 'protean_sqlalchemy.provider.SAProvider',
            'DATABASE_URI': 'postgresql://master:password@primary.com:5432/custom_app'
        },
        'secondary': {
            'PROVIDER': 'protean_sqlalchemy.provider.SAProvider',
            'DATABASE_URI': 'postgresql://master:password@secondary.com:5432/reporting'
        }
    }

.. code-block:: python

    from datetime import datetime
    from protean.core.repository import repo_factory

    class Account(Entity):
        username = field.String(required=True, unique=True, max_length=50)
        email = field.String(required=True)
        password = field.StringLong(required=True, min_length=6)

    class AccountHistory(Entity):
        ...

        version = field.Integer(required=True)
        archived_on = field.DateTime(default=datetime.now())

    repo_factory.register(Account, 'primary')
    repo_factory.register(Account, 'secondary')

Defining Custom Schemas
-----------------------

Schemas, which are object representations of Entities as your underlying data store would understand, are generated on-the-fly by your repository provider. You do not have explicitly define them by hand. But if you want to override the default definitions, for example to specify a column name to store an entity's attribute, you can define them in the ``Meta`` section of an entity.

<TO BE DOCUMENTED>

.. //FIXME Add documentation on customization of attributes in ``Meta`` class
