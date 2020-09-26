.. _block-repository:

============
Repositories
============

A **Repository** simply refers to a storage location of pre-existing domain objects.

Repositories are typically associated with Domain Aggregates.

Repositories and DAO
--------------------

There are multiple ways of organizing repositories in DDD projects in order to be database-agnostic in the domain layer. One way is to define a repository interface and consume the interface in persistence calls in the domain layer. Concrete implementations that satisfy to this interface are provided for different databases. Another way is to implement repositories as two layers: An outer repository layer that is close to the domain and contains domain concepts, and an inner DAO layer that talks to the persistence store. Protean adopts the latter approach.

The Repository Layer does not know how a persistence store is queried or how the data is stored. It does care about representing domain concepts. For example, if you want to query all users over the age of 21, the repository layer would contain a method called `find_adults`, while the underlying DAO layer would contain the actual definition of an adult (`age >= 18`).

The DAO layer would understand how to map a filter to the language of the underlying database. For example, if you specify `.filter(age >= 21)` as the criteria to the DAO and you are using an SQL-Compliant RDBMS, the DAO would translate it to something that the database can understand, like `SELECT * FROM users WHERE age >= 21`.

Collection-oriented repositories
--------------------------------

Repositories can either be Collection-oriented, or Persistence-oriented.

A collection-oriented design closely mimics how a collection data type, like `list`, `dictionary` and `set`, would work. The Repository interface does not hint in any way that there is an underlying persistence mechanism, avoiding any notion of saving or persisting data to a store.

To be specific, a Repository mimics a `set` collection. Whatever the implementation, the repository will not allow instances of the same object to be added twice. Also, when retrieving objects from a Repository and modifying them, you don’t need to “re-save” them to the Repository. The task of syncing the data back into the persistence store is handled automatically.

A persistence-oriented repository, on the other hand, requires that you handle the persistence explicitly. You must explicitly persist both new and changed objects into the store. A persistence-oriented repository may be a good choice when you are dealing with a database for which Protean does not have a plugin yet. Using these kinds of data stores can also simplify the basic writes and reads of Aggregates.

Protean has in-built support for collection-oriented repositories. By separating the DAO layer from the repository layer, Protean gives you the advantage of not having to worry about handling persistence explicitly, but also keeps you agnostic to the database so that you can switch to a different database if necessary.

True to its nature, Protean's repositories come with two methods to just 3 methods to handle the object life-cycle:

* `add(element)`: which places the element in a transaction and commits when appropriate
* `remove(element)`: which marks the object to the be deleted from the database and commits as part of a transaction when appropriate
* `get(key)`: which retrieves the object with the specified key from the persistence store.

.. note:: Additionally, in the near future, you will also have a `filter()` method that accepts a `Specification` and returns objects matching the specification's criteria.

Beyond these, you can write your custom methods to retrieve data from the persistence store. See :ref:`api-dao` for abstracted methods that you could use to query the database in different ways. Such custom query methods in the repository would typically be named to be domain-relevant, like `find_adults()`, `find_residents_of_latvia()`, and so on.

Transactions in Repositories
----------------------------

By default, method calls to repositories persist data to the store immediately. This may not be safe when you are executing complex business logic, so Protean supports an explicit initiation of a transaction with the help of `UnitOfWork` object (see :ref:`example <repository-add>`).

You should be safe most of the time if you stick to the principle of restricting changes to one single aggregate per transaction. Other changes (across aggregates or domains) are to be performed in separate transactions, so that the system becomes eventually consistent.

    Any rule that spans AGGREGATES will not be expected to be up-to-date at all times. Through event processing, batch processing, or other update mechanisms, other dependencies can be resolved within some specific time. [Evans, p. 128]

.. note:: In the near future, Protean will provide you the ability to choose between explicit and implicit transaction management. With implicit transaction management, you would not have to worry about handling transactions. Protean would begin and commit (or rollback) transactions for each Application Service method automatically. With explicit transaction management, you will need to follow the current mechanism of manually beginning a `Unit of Work` for the set of changes you want to group into a transaction.

On the other end of the spectrum, it is recommended that you don't handle changes to different providers as part of the same transaction. There is no guarantee that transactions can be committed or rolled back atomically across different providers, which usually translates to different disparate databases.

Data Access Objects (DAO)
-------------------------

This discussion would not be complete without an introduction to the DAO layer of Protean.

Data Access Objects in Protean are made available as plugins, and activated with the help of configuration flags. Each Persistence Store implementation will have a corresponding DAO implementation of its own. For example, there would be two different plugins for Mongo and Elasticsearch. There are also cases where the DAO would make use of an ORM to support connections to multiple databases at one go, like SQLAlchemy.

You can check different available implementations :ref:`here <plugin-database>`, and read about configuring Data Access Objects in the :ref:`user-persistence` section.
