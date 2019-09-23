.. _dao:

===================
Data Access Objects
===================

Data Access Objects, or DAOs, handle the interaction with underlying persistence stores.

Each persistence store or database will have a corresponding DAO implementation made available through a plugin.

Protean come pre-packaged with a DAO for a simple In-Memory Database, implemented with the help of dictionaries. There is also a plugin available that uses SQLAlchemy internally and can integrate with all databases that SQLAlchemy supports. In the near future, there is a plan to add plugins for MongoDB and Elasticsearch. You can learn about configuring different plugins in the :ref:`user-persistence` section.

Take a look at the :ref:`API <api-dao>` of DAOs for information on DAO capabilities and available methods.

Protean does not currently have the ability to specify a database schema explicitly, to be used by the DAO.
