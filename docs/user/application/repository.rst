.. _repository:

============
Repositories
============

Repositories are responsible for loading and persisting aggregates, including all elements in the aggregate's composition. A repository uses Data Access Objects (DAO) to access the persistency layer. See :ref:`dao` for more information on using DAOs.

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

Generally, every persistent Aggregate type will have a Repository, and there is a one-to-one relationship between an Aggregate type and a Repository. Strictly speaking, only Aggregates have Repositories. If you are not using Aggregates in a given Bounded Context for whatever reason, the Repository pattern may not be useful to you.

Repositories lean towards the domain side and represent domain concepts that are present in the database. For example, say you have a requirement of fetching adult users (over the age of 21) from the database. The user repository will then have a function called `get_adults` which would use underlying DTOs to make a query for `age >= 21`.

.. doctest::

    @domain.repository(aggregate_cls='User')
    class UserRepository:
        @classmethod
        def get_adults(cls, age: int = 21) -> List:
            user_dao = current_domain.get_dao(User)

            return user_dao.filter(age__gte=age).all()

Repositories in Protean behave like collections. Each Repository is equipped with default `add` and `remove` mechanisms, that can take care of aggregate persistence automatically. You can override them with explicit definitions in your repository class, if necessary. These lifecycle methods are typically invoked in :ref:`application-service` while performing operations.

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

When there is an active Unit of Work in progress, changes performed by repositories are preserved as part of a session, and committed as an ACID transaction at the end of a process. The entire transaction is rolled back on error. This transactional functionality is supported at the level of Protean, but Protean in turn uses session and ACID abilities of the underlying persistence store, whenever available.

.. doctest::

    from protean.core.unit_of_work import UnitOfWork

    @domain.application_service(aggregate_cls='User')
    class SignupService:
        """ Application Service that contains methods to help users register and sign up"""
        @classmethod
        def register(cls, request_object: UserRegistration):
            # Initialize a Unit of Work for controlling transactions
            with UnitOfWork():
                repo = domain.repository_for(User)  # Register the repository within the UoW
                user = User.register(request_object)
                repo.add(user)

            # The Unit of Work transaction would have been committed by this point

On the query side, a repository is capable of querying by the aggregate's primary identifier automatically with the `get` method. It also supports a ``filter`` method that accepts a :ref:`specification` object and can filter aggregate data automatically.

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
