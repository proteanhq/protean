.. _community-adapters:

Building Adapters
=================

Database Adapters
-----------------

Protean comes pre-packaged with out-of-the-box support for most popular databases:

* All databases supported by SQL Alchemy (See the section |sql-alchemy-dialects| on SQLAlchemy.org for information on the various backends available)
* Elasticsearch
* MongoDB (TBD)
* Redis (TBD)
* Cassandra (TBD)

.. note:: If you don't see your database, you can still build one by yourself! To be more awesome, open source your adapter and raise a pull request to add your adapter to the list above.

A Protean-compliant DB adapter typically has two parts to it:

* **Standard mechanism** to discover, initialize and handle database connections
* **Concrete implementations** of lifecycle methods required to interact with the database

To support initiation and handling of database connections, you subclass `BaseConnectionHandler` and implement the abstract methods:

.. code-block:: python

    from protean.core.repository import BaseConnectionHandler

    class ConnectionHandler(BaseConnectionHandler):
        """Manage connections to the Sqlalchemy ORM"""

        def __init__(self, conn_name: str, conn_info: dict):
            """Discover Connection settings and initialize if necessary
            ...

        def get_connection(self):
            """ Create and return connection to the Database instance"""
            ...

        def close_connection(self, conn):
            """ Close the connection to the Database instance """
            conn.close()

And then add concrete implementations of lifecycle methods after subclassing `BaseAdapter`:

.. code-block:: python

    from protean.core.repository import BaseAdapter

    class Adapter(BaseAdapter):
        """ An Adapter for persisting data in <Your Database> """

        def _filter_objects(
            self, page: int = 1, per_page: int = 10,
            order_by: list = (), excludes_: dict = None,
            **filters) -> Pagination:
            """
            Filter objects from the repository. Method must return a `Pagination`
            object
            """
            ...

        def _create_object(self, model_obj: Any):
            """Create a new model object from the entity"""
            ...

        def _update_object(self, model_obj: Any):
            """Update a model object in the repository and return it"""
            ...

        def _delete_objects(self, **filters):
            """Delete a Record from the Repository"""
            ...

Note that the class **HAS** to be named `Adapter` for Protean to discover it and initialize it properly.

A simple, yet fully functioning implementation of a Database Adapter can be seen in `protean.impl.repository.dict_repo`. You can use this implementation as an example for your own adapter.

Framework Adapters
------------------

More info to come.

.. |sql-alchemy-dialects| raw:: html

    <a href="https://docs.sqlalchemy.org/en/latest/dialects/index.html" target="_blank">Dialects</a>
