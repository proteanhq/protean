Persisting Data
===============

To keep the application technology agnostic, persistence in Protean is handled with the help of repositories that abstract all database interactions. The repository layer encapsulates all the logic required to access data sources. Modeled after the Repository Pattern, repositories are responsible for loading and persisting aggregates.

Repositories represent domain concepts that are present in the database. For example, say you have a requirement of fetching adult users (over the age of 21) from the database. The user repository would then have a function called `get_adults` which would use underlying Data Transfer Objects to make a query for `age >= 21`.

.. code-block:: python

    @domain.repository(aggregate_cls='User')
    class UserRepository:
        @classmethod
        def get_adults(cls, age: int = 21) -> List:
            user_dao = current_domain.get_dao(User)
            return user_dao.filter(age__gte=age).all()

Saving to Database
------------------

You can obtain a repository associated with your aggregate with ``domain.repository_for`` method:

.. code-block:: python

    from protean.globals import current_domain

    current_domain.repository_for(Post)

Protean's repositories are collection-oriented. They are designed to closely mimic how a collection data type, like `list`, `dictionary` and `set`, would work. The Repository interface does not expose the underlying persistence mechanism, avoiding any notion of saving or persisting data to a store from leaking into the Application Service or Domain Model.

There is a one-to-one relationship between an Aggregate and a Repository: Every Aggregate has a repository. Also, Aggregates alone have Repositories.

Yoy can persist an aggregate with the help of ``add`` method. The ``add`` method places the new aggregate in a transaction.

.. code-block:: python

    post_repo = current_domain.repository_for(Post)
    post = Post(title="A catchy post title")

    post_repo.add(post)

The `post` record will be persisted into the data store immediately, or when the :ref:`unit-of-work` is committed if the transaction is running under an active UoW.

Persisted data can be removed by its unique identifier:

.. code-block:: python

    post_repo = current_domain.repository_for(Post)
    post = post_repo.get(1)

    post_repo.remove(post)

.. note:: It is generally recommended that data never be permanently deleted from the system. It is better to use soft deletes or archiving functionalities to mark data as archived or defunct. The ``remove`` method should be primarily used for testing purposes.

Retrieving Data
---------------

The ``get`` method retrieves the object with the specified key from the persistence store.

.. code-block:: python

    post_repo = current_domain.repository_for(Post)
    post = post_repo.get(1234)

You can also fetch all records of an Aggregate with the ``all`` method:

.. code-block:: python

    post_repo = current_domain.repository_for(Post)
    posts = post_repo.all()

Beware that the ``all`` method returns **all** records of an Aggregate type from the database as it stands today. It is meant to be used for testing purposes. Application queries should preferably be implemented outside the Domain as close as possible to the database for performance reasons. Aggregate and Repository patterns are meant to serve the write-side of the application. It is left to the application to organize the read-side to be as efficient as possible.

.. // FIXME Add documentation for DAO API

All other querying capabilities are performed through the DAO `filter` method.

.. code-block:: python

    @domain.repository(aggregate_cls='User')
    class UserRepository:
        @classmethod
        def fetch_residents(cls, zipcode: str) -> List:
            user_dao = current_domain.get_dao(User)

            return user_dao.filter(zipcode=zipcode).all()


Custom Repositories
-------------------

You would often want to add custom methods to your repository to aid database interactions. You can do so by defining and registering your own custom repository.

A Repository can be defined and registered with the help of ``@domain.repository`` decorator:

.. code-block:: python

    @domain.repository(aggregate_cls='app.User')
    class UserRepository:
        @classmethod
        def get_by_email(cls, email: str) -> User:
            user_dao = current_domain.get_dao(User)
            return user_dao.find_by(email=email)

A Repository is linked to its aggregate with the `aggregate_cls` meta attribute. The value of `aggregate_cls` can be the Aggregate class itself, or in the form of a weak reference - a string with the the fully-qualified aggregate class name.

Database-specific Repositories
------------------------------

A repository can be locked to a specific database implementation. This feature comes handy if you ever use different databases with the same aggregate, for example, in testing and production environments. A repository locked to a specific database is picked up only when the aggregate's provider database matches the value specified.

.. code-block:: python

    @domain.aggregate
    class User:
        first_name = String()
        last_name = String()

        class Meta:
            provider = 'sqlite'

    @domain.repository(aggregate_cls='app.User')
    class UserRepository:
        class Meta:
            database = Database.SQLITE.value

This feature also allows multiple repositories to be defined and linked per database to the aggregate. The full list of supported databases can be found :ref:`here<supported-databases>`. Refer to :doc:`config` documentation to understand how providers are defined.

Data Access Objects
-------------------

Protean repositories internally use Data Access Objects (DAO) to access the persistency layer. See :ref:`adapters-dao` for more information on using Data Access Objects.

.. code-block:: python

    user_dao = current_domain.get_dao(User)
    users = user_dao.filter(state='CA')

Data Access Objects (DAOs) can be accessed throughout the application, but it is recommended that you access them only within the repositories, in line with the pattern of placing all data access operations in the repository layer.

At first glance, repositories and Data Access Objects may seem similar. But a repository leans towards the domain in its functionality. It contains methods and implementations that clearly identify what the domain is trying to ask/do with the persistence store. Data Access Objects, on the other hand, talk the language of the database. A repository works in conjunction with the DAO layer to access and manipulate on the persistence store.

This separation is necessary because we want the domain layer to be agnostic to the underlying persistence store implementation. DAO are concrete implementations, one per persistence store, and are built as adapters to the Repository Port in Protean. You can switch between them without having to touch your domain functionality just by replacing plugins in your application configuration. Refer to :ref:`adapters-dao` for more information.

Working with Application Services
---------------------------------

A repository's methods are typically used by :ref:`application-service` to perform lifecycle operations.

.. code-block:: python

    @domain.application_service(aggregate_cls='User')
    class SignupService:
        """ Application Service that contains methods to help users register and sign up"""
        @classmethod
        def register(cls, request_object: UserRegistration):
            # Fetch the repository configured for `User` Aggregate
            repo = domain.repository_for(User)

            # Invoke the domain function to register a new User
            user = User.register(request_object)

            # Persist the new user
            repo.add(user)

Unit of Work
------------

When there is an active Unit of Work in progress, changes performed by repositories are preserved as part of a session, and committed as an ACID transaction at the end. The entire transaction can be committed on success, or rolled back on error.

.. code-block:: python

    from protean.core.unit_of_work import UnitOfWork

    @domain.application_service(aggregate_cls='User')
    class SignupService:

        @classmethod
        def register(cls, request_object: UserRegistration):
            # Initialize a Unit of Work for controlling transactions
            with UnitOfWork():
                repo = domain.repository_for(User)  # The repository is now within a UoW
                user = User.register(request_object)
                repo.add(user)  # User is not added to the persistence store yet

            # The Unit of Work transaction would have been committed by this point

Note that Protean still depends on the capabilities of the underlying database to support transactional functionality. While changes are flushed as a single unit, it is left to the database implementation to construct and manage sessions and commit transactions atomically.
