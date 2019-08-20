.. _repository:

============
Repositories
============

Repositories are responsible for loading and persisting aggregates, including all elements in the aggregate's composition. Generally, every persistent Aggregate type will have a Repository, and there is a one-to-one relationship between an Aggregate type and a Repository.

Repositories in Protean behave like collections. Each Repository is equipped with default `add` and `remove` mechanisms, that can take care of aggregate persistence automatically. You can override them with explicit definitions in your repository class, if necessary.

When there is an active Unit of Work in progress, changes performed by repositories are preserved as part of a session, and committed as an ACID transaction at the end of a process. The entire transaction is rolled back on error. This transactional functionality is supported at the level of Protean, but Protean in turn uses session and ACID abilities of the underlying persistence store, whenever available.

On the query side, a repository is capable of querying by the aggregate's primary identifier automatically with the `get` method. It also supports a ``filter`` method that accepts a :ref:`specification` object and can filter aggregate data automatically.

A repository uses Data Access Objects (DAO) to access the persistency layer. See :ref:`dao` for more information on using DAOs.

Strictly speaking, only Aggregates have Repositories. If you are not using Aggregates in a given Bounded Context for whatever reason, the Repository pattern may not be useful to you.


Usage
=====

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
