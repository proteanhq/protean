.. _unit-of-work:

============
Unit of Work
============

A `Unit of Work` (UoW) keeps track of object changes for you during a business transaction. When the business transaction is complete, the UoW takes care of syncing changes to the database automatically and atomically. If the changes cannot be synced in entirety, all changes are rolled back, ensuring the database remains sacrosanct.

A `Unit of Work` is initialized manually when you want to fold a set of tasks into one single business transaction:

.. testsetup:: *

    import os
    from protean.domain import Domain

    domain = Domain('Test')

    ctx = domain.domain_context()
    ctx.push()

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

Events that are plublished as part of the business transaction are only dispatched on successful sync of the database. They are lost if the transaction is rolled back, or business validations fail, ensuring that data sanctity is maintained throughout the system at all time.

While a `Unit of Work` provides a mechanism to atomically commit changes to the database, it is recommended that Domain transactions are limited to one single Aggregate per Application Service method call. Changes outside the aggregate's transaction boundary should be done with eventual consistency, with the help of domain events.

Working outside UoWs
--------------------

When necessary, you can still ignore any `Unit of Work` in progress by explicitly marking the DAO to work outside UoW. This is a rare case scenario, and a scenario where it can be useful is in writing tests.

.. doctest::
    ...
    # Initiate a UnitOfWork Session
    with UnitOfWork():
        repo = test_domain.repository_for(Person)
        persisted_person = repo.get(person.id)

        persisted_person.last_name = 'Dane'
        repo.add(persisted_person)

        # Test that the underlying database is untouched
        assert person_dao.outside_uow().find_by(id=person.id).last_name == 'Doe'

    assert person_dao.get(person.id).last_name == 'Dane'

    ...
