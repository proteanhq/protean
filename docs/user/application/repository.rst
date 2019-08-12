.. _repository:

============
Repositories
============

These collection-like objects are all about persistence. Every persistent Aggregate type will have a Repository. Generally speaking, there is a one-to-one relationship between an Aggregate type and a Repository.

A Repository is responsible for persisting and loading an aggregate as well as all elements in the aggregate's composition.

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

Each Repository is equipped with default `add` and `remove` mechanisms, that can take care of aggregate persistence automatically. You can override them with explicit definitions in your repository class, if necessary.

On the query side, a repository is capable of querying by the aggregate's primary identifier automatically with the `get` method. It also supports a ``filter`` method that accepts a :ref:`specification` object and can filter aggregate data automatically.

A repository uses Data Access Objects (DAO) to access the persistency layer. See :ref:`dao` for more information on using DAOs.
