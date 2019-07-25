# Standard Library Imports
import random
import string

# Protean
import pytest

from protean.core.exceptions import InvalidOperationError, ObjectNotFoundError
from protean.core.unit_of_work import UnitOfWork

# Local/Relative Imports
from .elements import Person, PersonRepository


class TestUnitOfWorkInitialization:

    def test_uow_can_be_initiated_with_context_manager(self, test_domain):
        with UnitOfWork(test_domain) as uow:
            assert uow is not None
            assert uow.in_progress is True

    def test_uow_can_be_initiated_explicitly(self, test_domain):
        uow = UnitOfWork(test_domain)
        assert uow is not None
        assert uow.in_progress is False

        uow.start()
        assert uow.in_progress is True

    def test_that_session_factories_are_initialized_properly_for_multiple_providers(self, test_domain):
        with UnitOfWork(test_domain) as uow:
            assert uow._sessions is not None
            assert 'default' in uow._sessions

    def test_that_uow_throws_exception_on_commit_or_rollback_without_being_started(self, test_domain):
        uow = UnitOfWork(test_domain)

        with pytest.raises(InvalidOperationError):
            uow.commit()

        with pytest.raises(InvalidOperationError):
            uow.rollback()


class TestUnitOfWorkRegistration:

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, aggregate_cls=Person)

        yield

    @pytest.fixture
    def persisted_person(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name='John', last_name='Doe')
        repo.add(person)

        return person

    def test_new_object_registration_with_uow_passed_on_repository_initialization(self, test_domain):
        with UnitOfWork(test_domain) as uow:
            repo = test_domain.repository_for(Person, uow)
            person = Person(first_name='John', last_name='Doe')
            repo.add(person)

            assert person.id in uow.changes_to_be_committed['default']['ADDED']

    def test_new_object_registration_with_uow_passed_through_repository_within_method(self, test_domain):
        with UnitOfWork(test_domain) as uow:
            repo = test_domain.repository_for(Person).within(uow)
            person = Person(first_name='John', last_name='Doe')
            repo.add(person)

            assert person.id in uow.changes_to_be_committed['default']['ADDED']

    def test_that_there_is_no_update_registration_if_object_is_unchanged(self, test_domain, persisted_person):
        with UnitOfWork(test_domain) as uow:
            repo = test_domain.repository_for(Person).within(uow)
            repo.add(persisted_person)

            assert persisted_person.id not in uow.changes_to_be_committed['default']['UPDATED']

    def test_update_registration_for_changed_object_with_uow(self, test_domain, persisted_person):
        with UnitOfWork(test_domain) as uow:
            repo = test_domain.repository_for(Person).within(uow)
            persisted_person.last_name = 'Dane'
            repo.add(persisted_person)

            assert persisted_person.id in uow.changes_to_be_committed['default']['UPDATED']

    def test_delete_registration_for_object_to_be_removed(self, test_domain, persisted_person):
        with UnitOfWork(test_domain) as uow:
            repo = test_domain.repository_for(Person).within(uow)
            repo.remove(persisted_person)

            assert persisted_person.id in uow.changes_to_be_committed['default']['REMOVED']


class TestUnitOfWorkTransactions:

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, aggregate_cls=Person)

    def random_name(self):
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=15))

    def persisted_person(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name=self.random_name(), last_name=self.random_name())
        repo.add(person)

        return person

    def test_for_changes_recorded_to_be_committed(self, test_domain):
        person2 = self.persisted_person(test_domain)
        person3 = self.persisted_person(test_domain)
        with UnitOfWork(test_domain) as uow:
            repo = test_domain.repository_for(Person, uow)

            person = Person(first_name='John', last_name='Doe')
            repo.add(person)

            person2.last_name = 'Dane'
            repo.add(person2)

            repo.remove(person3)

            assert len(uow.changes_to_be_committed['default']['ADDED']) == 1
            assert len(uow.changes_to_be_committed['default']['UPDATED']) == 1
            assert len(uow.changes_to_be_committed['default']['REMOVED']) == 1

    def test_new_objects_are_committed_as_part_of_one_transaction(self, test_domain):
        # Add a Person the database
        repo = test_domain.repository_for(Person)
        repo.add(self.persisted_person(test_domain))

        person_dao = test_domain.get_dao(Person)

        # Initiate a UnitOfWork Session
        with UnitOfWork(test_domain) as uow:
            repo = test_domain.repository_for(Person, uow)
            person2 = Person(first_name='Jane', last_name='Doe')
            repo.add(person2)

            # Test that the underlying database is untouched

            assert len(person_dao.query.all().items) == 1

        assert len(person_dao.query.all().items) == 2

    def test_updated_objects_are_committed_as_part_of_one_transaction(self, test_domain):
        # Add a Person the database
        repo = test_domain.repository_for(Person)
        person = Person(first_name='John', last_name='Doe')
        repo.add(person)

        person_dao = test_domain.get_dao(Person)

        # Initiate a UnitOfWork Session
        with UnitOfWork(test_domain) as uow:
            repo = test_domain.repository_for(Person, uow)
            persisted_person = repo.get(person.id)

            persisted_person.last_name = 'Dane'
            repo.add(persisted_person)

            # Test that the underlying database is untouched
            assert person_dao.get(person.id).last_name == 'Doe'

        assert person_dao.get(person.id).last_name == 'Dane'

    def test_deleted_objects_are_committed_as_part_of_one_transaction(self, test_domain):
        # Add a Person the database
        repo = test_domain.repository_for(Person)
        person_to_be_added = self.persisted_person(test_domain)
        repo.add(person_to_be_added)

        person_dao = test_domain.get_dao(Person)

        # Initiate a UnitOfWork Session
        with UnitOfWork(test_domain) as uow:
            repo = test_domain.repository_for(Person, uow)
            persisted_person = repo.get(person_to_be_added.id)
            repo.remove(persisted_person)

            # Test that the underlying database is untouched
            assert len(person_dao.query.all().items) == 1

        assert len(person_dao.query.all().items) == 0

    def test_changed_objects_are_committed_as_part_of_one_transaction(self, test_domain):
        # Add a Person the database
        repo = test_domain.repository_for(Person)
        person_to_be_updated = self.persisted_person(test_domain)
        person_to_be_deleted = self.persisted_person(test_domain)
        repo.add(person_to_be_updated)
        repo.add(person_to_be_deleted)

        person_dao = test_domain.get_dao(Person)

        # Initiate a UnitOfWork Session
        with UnitOfWork(test_domain) as uow:
            repo_with_uow = test_domain.repository_for(Person, uow)

            # Create a new person object to be added
            person_to_be_added = Person(first_name='John', last_name='Doe')
            repo_with_uow.add(person_to_be_added)

            # Update an existing Person record
            person_to_be_updated.last_name = 'FooBar'
            repo_with_uow.add(person_to_be_updated)

            # Remove an existing Person record
            repo_with_uow.remove(person_to_be_deleted)

            # Test that the underlying database is untouched
            assert len(person_dao.query.all().items) == 2
            assert person_dao.get(person_to_be_updated.id).last_name != 'FooBar'
            assert person_dao.get(person_to_be_deleted.id) is not None

        assert len(person_dao.query.all().items) == 2
        assert person_dao.get(person_to_be_added.id) is not None
        assert person_dao.get(person_to_be_updated.id).last_name == 'FooBar'
        with pytest.raises(ObjectNotFoundError):
            person_dao.get(person_to_be_deleted.id)

    def test_changed_objects_are_committed_as_part_of_one_transaction_on_explict_commit(self, test_domain):
        # Add a Person the database
        repo = test_domain.repository_for(Person)
        person_to_be_updated = self.persisted_person(test_domain)
        person_to_be_deleted = self.persisted_person(test_domain)
        repo.add(person_to_be_updated)
        repo.add(person_to_be_deleted)

        person_dao = test_domain.get_dao(Person)

        # Initiate a UnitOfWork Session
        uow = UnitOfWork(test_domain)
        uow.start()

        repo_with_uow = test_domain.repository_for(Person, uow)

        # Create a new person object to be added
        person_to_be_added = Person(first_name='John', last_name='Doe')
        repo_with_uow.add(person_to_be_added)

        # Update an existing Person record
        person_to_be_updated.last_name = 'FooBar'
        repo_with_uow.add(person_to_be_updated)

        # Remove an existing Person record
        repo_with_uow.remove(person_to_be_deleted)

        # Test that the underlying database is untouched
        assert len(person_dao.query.all().items) == 2
        assert person_dao.get(person_to_be_updated.id).last_name != 'FooBar'
        assert person_dao.get(person_to_be_deleted.id) is not None

        uow.commit()

        assert uow.in_progress is False
        assert len(person_dao.query.all().items) == 2
        assert person_dao.get(person_to_be_added.id) is not None
        assert person_dao.get(person_to_be_updated.id).last_name == 'FooBar'
        with pytest.raises(ObjectNotFoundError):
            person_dao.get(person_to_be_deleted.id)

    def test_all_changes_are_discard_on_rollback(self, test_domain):
        repo = test_domain.repository_for(Person)
        person_to_be_updated = self.persisted_person(test_domain)
        person_to_be_deleted = self.persisted_person(test_domain)
        repo.add(person_to_be_updated)
        repo.add(person_to_be_deleted)

        person_dao = test_domain.get_dao(Person)

        # Initiate a UnitOfWork Session
        uow = UnitOfWork(test_domain)
        uow.start()

        repo_with_uow = test_domain.repository_for(Person, uow)

        # Create a new person object to be added
        person_to_be_added = Person(first_name='John', last_name='Doe')
        repo_with_uow.add(person_to_be_added)

        # Update an existing Person record
        person_to_be_updated.last_name = 'FooBar'
        repo_with_uow.add(person_to_be_updated)

        # Remove an existing Person record
        repo_with_uow.remove(person_to_be_deleted)

        # Test that the underlying database is untouched
        assert len(person_dao.query.all().items) == 2
        assert person_dao.get(person_to_be_updated.id).last_name != 'FooBar'
        assert person_dao.get(person_to_be_deleted.id) is not None

        uow.rollback()

        assert uow.in_progress is False
        assert len(person_dao.query.all().items) == 2
        assert person_dao.get(person_to_be_updated.id).last_name != 'FooBar'
        assert person_dao.get(person_to_be_deleted.id) is not None

    def test_session_is_destroyed_after_commit(self, test_domain):
        uow = UnitOfWork(test_domain)
        uow.start()

        uow.commit()
        assert uow._sessions == {}
        assert uow.in_progress is False

    def test_session_is_destroyed_after_rollback(self, test_domain):
        uow = UnitOfWork(test_domain)
        uow.start()

        uow.rollback()
        assert uow._sessions == {}
        assert uow.in_progress is False


class TestUnitOfWorkWithMultipleProviders:
    @pytest.mark.skip
    def test_sessions_across_multiple_providers_are_committed_together(self):
        pass

    @pytest.mark.skip
    def test_sessions_across_multiple_providers_are_rolled_back_together(self):
        pass
