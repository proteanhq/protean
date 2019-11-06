.. _repository:

============
Repositories
============

Repositories are responsible for loading and persisting aggregates, including all elements in the aggregate's composition. A repository uses Data Access Objects (DAO) to access the persistency layer. See :ref:`dao` for more information on using Data Access Objects.

At first glance, repositories and Data Access Objects seem similar and to be doing the same function. But a repository leans towards the domain in its functionality. It contains methods and implementations that clearly identify what the domain is trying to ask/do with the persistence store. DAO, on the other hand, talk the language of the database. A repository works in conjunction with the DAO layer to operate on the persistence store.

This separation is necessary because we want the domain layer to be agnostic to the underlying persistence store implementation. DAO are concrete implementations, one per persistence store, and are built as plugins to Protean. You can switch between them without having to touch your domain functionality just by replacing plugins in your application configuration.

A Repository can be defined and registered with the help of ``@domain.repository`` decorator:

.. testsetup:: *

    import os
    from protean.domain import Domain

    domain = Domain('Test')

    ctx = domain.domain_context()
    ctx.push()

.. doctest::

    @domain.repository(aggregate_cls='User')
    class UserRepository:
        @classmethod
        def get_by_email(cls, email: str) -> User:
            user_dao = current_domain.get_dao(User)
            try:
                return user_dao.find_by(email=email)
            except ObjectNotFoundError:
                return None

        @classmethod
        def get_by_username(cls, username: str) -> User:
            user_dao = current_domain.get_dao(User)
            try:
                return user_dao.find_by(username=username)
            except ObjectNotFoundError:
                return None

Aggregates and Repositories
---------------------------

Generally, every persistent Aggregate type will have a Repository. There is a one-to-one relationship between an Aggregate type and a Repository. Also, Aggregates alone have Repositories. While it is possible to create Repositories connected to Entities, you can simply use a DAO to accomplish the same task.

Repositories and Domain concepts
--------------------------------

Repositories represent domain concepts that are present in the database. For example, say you have a requirement of fetching adult users (over the age of 21) from the database. The user repository could then have a function called `get_adults` which would use underlying Data Transfer Objects to make a query for `age >= 21`.

.. doctest::

    @domain.repository(aggregate_cls='User')
    class UserRepository:
        @classmethod
        def get_adults(cls, age: int = 21) -> List:
            user_dao = current_domain.get_dao(User)

            return user_dao.filter(age__gte=age).all()

Collection-oriented Repositories
--------------------------------

Repositories in Protean behave like collections. Each Repository is equipped with default `add` and `remove` mechanisms, that can take care of aggregate persistence automatically. You can override them with explicit definitions in your repository class, if necessary. These life cycle methods are typically invoked in :ref:`application-service` while performing operations.

.. _repository-add:

.. doctest::

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

When there is an active Unit of Work in progress, changes performed by repositories are preserved as part of a session, and committed as an ACID transaction at the end. The entire transaction can be committed on success, or rolled back on error. Though Protean supports transactional functionality, it internally uses session and ACID capabilities of the underlying persistence store, wherever available.

.. doctest::

    from protean.core.unit_of_work import UnitOfWork

    @domain.application_service(aggregate_cls='User')
    class SignupService:
        """ Application Service that contains methods to help users register and sign up"""
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

.. doctest::

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

.. doctest::

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
