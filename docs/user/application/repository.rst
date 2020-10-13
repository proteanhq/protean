.. _repository:

============
Repositories
============

The repository layer encapsulates all the logic required to access data sources. Modeled after the Repository Pattern, repositories are responsible for loading and persisting aggregates.

You can obtain a repository associated with your aggregate with ``domain.repository_for`` method::

    from protean.globals import current_domain

    current_domain.repository_for(Post)

Protean's repositories are collection-oriented. They are designed to closely mimic how a collection data type, like `list`, `dictionary` and `set`, would work. The Repository interface does not expose the underlying persistence mechanism, avoiding any notion of saving or persisting data to a store from leaking into the Application Service or Domain Model.

There is a one-to-one relationship between an Aggregate and a Repository: Every Aggregate has a repository. Also, Aggregates alone have Repositories.

Default Methods
---------------

Protean's repository comes with two in-built methods:

1. **add**

The `add` method places the new aggregate in a transaction and commits when appropriate.

.. code-block:: python

    post_repo = current_domain.repository_for(Post)
    post = Post(title="A catchy post title")

    post_repo.add(post)

The `post` record will be persisted into the data store immediately, or when the :ref:`unit-of-work` is committed if the transaction is running under an active UoW.

2. **get**

The `get` method retrieves the object with the specified key from the persistence store.

.. code-block:: python

    post_repo = current_domain.repository_for(Post)
    post = post_repo.get(1234)

.. note:: There is no `remove` method in Protean repositories by default. Though it is easy to add one, it is generally recommended that data never be deleted from the system. If you really want to, use soft deletes or archiving functionalities to mark data as defunct.

Custom Repositories
-------------------

You would often want to add custom methods to your repository apart from the default `add` and `get`. You can do so by defining and registering your own custom repository.

A Repository can be defined and registered with the help of ``@domain.repository`` decorator:

.. code-block:: python

    @domain.repository(aggregate_cls='app.User')
    class UserRepository:
        @classmethod
        def get_by_email(cls, email: str) -> User:
            user_dao = current_domain.get_dao(User)
            return user_dao.find_by(email=email)

A Repository is linked to its aggregate with the `aggregate_cls` meta attribute. The value of `aggregate_cls` can be the Aggregate class, or the fully-qualified aggregate class name as a string. It can also be declared as an Meta class attribute.

In config.py:

.. code-block:: python

    DATABASES = {
        "default": {
            "PROVIDER": "protean.adapters.repository.sqlalchemy.SAProvider",
            "DATABASE": Database.SQLITE.value,
            "DATABASE_URI": "sqlite:///test.db",
        },
    }

In Domain Model:

.. code-block:: python

    @domain.repository
    class UserRepository:
        class Meta:
            aggregate_cls = 'app.User'

        @classmethod
        def get_by_email(cls, email: str) -> User:
            user_dao = current_domain.get_dao(User)
            return user_dao.find_by(email=email)

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

This feature also allows multiple repositories to be defined and linked per database to the aggregate. The full list of supported databases can be found :ref:`here<supported-databases>`. Refer to :ref:`aggregate` documentation to understand how providers are defined.

Repositories and Data Access Objects
------------------------------------

Protean repositories can internally use Data Access Objects (DAO) to access the persistency layer. See :ref:`dao` for more information on using Data Access Objects.

.. code-block:: python

    user_dao = current_domain.get_dao(User)
    users = user_dao.filter(state='CA')

Data Access Objects (DAOs) can be accessed throughout the application, but it is recommended that you access them only within the repositories, in line with the pattern of placing all data access operations in the repository layer.

At first glance, repositories and Data Access Objects may seem similar. But a repository leans towards the domain in its functionality. It contains methods and implementations that clearly identify what the domain is trying to ask/do with the persistence store. Data Access Objects, on the other hand, talk the language of the database. A repository works in conjunction with the DAO layer to access and manipulate on the persistence store.

This separation is necessary because we want the domain layer to be agnostic to the underlying persistence store implementation. DAO are concrete implementations, one per persistence store, and are built as adapters to the Repository Port in Protean. You can switch between them without having to touch your domain functionality just by replacing plugins in your application configuration. Refer to :ref:`adapters-dao` for more information.

Repositories and Domain concepts
--------------------------------

Repositories represent domain concepts that are present in the database. For example, say you have a requirement of fetching adult users (over the age of 21) from the database. The user repository would then have a function called `get_adults` which would use underlying Data Transfer Objects to make a query for `age >= 21`.

.. code-block:: python

    @domain.repository(aggregate_cls='User')
    class UserRepository:
        @classmethod
        def get_adults(cls, age: int = 21) -> List:
            user_dao = current_domain.get_dao(User)
            return user_dao.filter(age__gte=age).all()

Repositories and Application Services
-------------------------------------

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

Repositories and Unit of Work
-----------------------------

When there is an active Unit of Work in progress, changes performed by repositories are preserved as part of a session, and committed as an ACID transaction at the end. The entire transaction can be committed on success, or rolled back on error. Though Protean supports transactional functionality, it internally uses session and ACID capabilities of the underlying persistence store, wherever available.

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

Querying with Repositories
--------------------------

On the query side, a repository is capable of querying by the aggregate's primary identifier automatically with the `get` method.

.. code-block:: python

    @domain.application_service(aggregate_cls='User')
    class FetchUserService:
        """ Application Service that retrieves existing application users """
        @classmethod
        def fetch(cls, request_object: UserDetail):
            # Fetch the repository configured for `User` Aggregate
            repo = domain.repository_for(User)

            # Fetch the user by her primary key
            return repo.get(request_object.user_id)

All other querying capabilities are accessible through the DAO `filter` method.

.. code-block:: python

    @domain.application_service(aggregate_cls='User')
    class UserService:
        """ Application Service that retrieves existing application users """
        @classmethod
        def residents_of_zipcode(cls, request_object: FetchResidents):
            # Fetch the repository configured for `User` Aggregate
            repo = domain.repository_for(User)

            # Fetch the users belonging to zip code
            return repo.fetch_residents(request_object.zipcode)

    @domain.repository(aggregate_cls='User')
    class UserRepository:
        @classmethod
        def fetch_residents(cls, zipcode: str) -> List:
            user_dao = current_domain.get_dao(User)

            return user_dao.filter(zipcode=zipcode).all()
