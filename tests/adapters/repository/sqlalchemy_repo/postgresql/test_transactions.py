import random
import string

import pytest

from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ObjectNotFoundError

from .elements import Person, PersonRepository


@pytest.mark.postgresql
class TestTransactions:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, aggregate_cls=Person)

    def random_name(self):
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=15))

    def persisted_person(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name=self.random_name(), last_name=self.random_name())
        repo.add(person)

        return person

    def test_new_objects_are_committed_as_part_of_one_transaction(self, test_domain):
        # Add a Person the database
        repo = test_domain.repository_for(Person)
        repo.add(self.persisted_person(test_domain))

        person_dao = test_domain.get_dao(Person)

        # Initiate a UnitOfWork Session
        with UnitOfWork():
            repo = test_domain.repository_for(Person)
            person2 = Person(first_name="Jane", last_name="Doe")
            repo.add(person2)

            # Test that the underlying database is untouched

            assert len(person_dao.outside_uow().query.all().items) == 1

        assert len(person_dao.query.all().items) == 2

    def test_updated_objects_are_committed_as_part_of_one_transaction(
        self, test_domain
    ):
        # Add a Person the database
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        person_dao = test_domain.get_dao(Person)

        # Initiate a UnitOfWork Session
        with UnitOfWork():
            repo = test_domain.repository_for(Person)
            persisted_person = repo.get(person.id)

            persisted_person.last_name = "Dane"
            repo.add(persisted_person)

            # Test that the underlying database is untouched
            assert person_dao.outside_uow().find_by(id=person.id).last_name == "Doe"

        assert person_dao.get(person.id).last_name == "Dane"

    def test_deleted_objects_are_committed_as_part_of_one_transaction(
        self, test_domain
    ):
        # Add a Person the database
        repo = test_domain.repository_for(Person)
        person_to_be_added = self.persisted_person(test_domain)
        repo.add(person_to_be_added)

        person_dao = test_domain.get_dao(Person)

        # Initiate a UnitOfWork Session
        with UnitOfWork():
            repo = test_domain.repository_for(Person)
            persisted_person = repo.get(person_to_be_added.id)
            repo.remove(persisted_person)

            # Test that the underlying database is untouched
            assert len(person_dao.outside_uow().query.all().items) == 1

        assert len(person_dao.query.all().items) == 0

    def test_changed_objects_are_committed_as_part_of_one_transaction(
        self, test_domain
    ):
        # Add a Person the database
        repo = test_domain.repository_for(Person)
        person_to_be_updated = self.persisted_person(test_domain)
        person_to_be_deleted = self.persisted_person(test_domain)
        repo.add(person_to_be_updated)
        repo.add(person_to_be_deleted)

        person_dao = test_domain.get_dao(Person)

        # Initiate a UnitOfWork Session
        with UnitOfWork():
            repo_with_uow = test_domain.repository_for(Person)

            # Create a new person object to be added
            person_to_be_added = Person(first_name="John", last_name="Doe")
            repo_with_uow.add(person_to_be_added)

            # Update an existing Person record
            person_to_be_updated.last_name = "FooBar"
            repo_with_uow.add(person_to_be_updated)

            # Remove an existing Person record
            repo_with_uow.remove(person_to_be_deleted)

            # Test that the underlying database is untouched
            assert len(person_dao.query.all().items) == 2
            assert (
                person_dao.outside_uow().get(person_to_be_updated.id).last_name
                != "FooBar"
            )
            assert person_dao.get(person_to_be_deleted.id) is not None

        assert len(person_dao.query.all().items) == 2
        assert person_dao.get(person_to_be_added.id) is not None
        assert person_dao.get(person_to_be_updated.id).last_name == "FooBar"
        with pytest.raises(ObjectNotFoundError):
            person_dao.get(person_to_be_deleted.id)

    def test_changed_objects_are_committed_as_part_of_one_transaction_on_explict_commit(
        self, test_domain
    ):
        # Add a Person the database
        repo = test_domain.repository_for(Person)
        person_to_be_updated = self.persisted_person(test_domain)
        person_to_be_deleted = self.persisted_person(test_domain)
        repo.add(person_to_be_updated)
        repo.add(person_to_be_deleted)

        person_dao = test_domain.get_dao(Person)

        # Initiate a UnitOfWork Session
        uow = UnitOfWork()
        uow.start()

        repo_with_uow = test_domain.repository_for(Person)

        # Create a new person object to be added
        person_to_be_added = Person(first_name="John", last_name="Doe")
        repo_with_uow.add(person_to_be_added)

        # Update an existing Person record
        person_to_be_updated.last_name = "FooBar"
        repo_with_uow.add(person_to_be_updated)

        # Remove an existing Person record
        repo_with_uow.remove(person_to_be_deleted)

        # Test that the underlying database is untouched
        assert len(person_dao.query.all().items) == 2
        assert (
            person_dao.outside_uow().get(person_to_be_updated.id).last_name != "FooBar"
        )
        assert person_dao.get(person_to_be_deleted.id) is not None

        uow.commit()

        assert uow.in_progress is False
        assert len(person_dao.query.all().items) == 2
        assert person_dao.get(person_to_be_added.id) is not None
        assert person_dao.get(person_to_be_updated.id).last_name == "FooBar"
        with pytest.raises(ObjectNotFoundError):
            person_dao.get(person_to_be_deleted.id)

    def test_all_changes_are_discarded_on_rollback(self, test_domain):
        repo = test_domain.repository_for(Person)
        person_to_be_updated = self.persisted_person(test_domain)
        person_to_be_deleted = self.persisted_person(test_domain)
        repo.add(person_to_be_updated)
        repo.add(person_to_be_deleted)

        person_dao = test_domain.get_dao(Person)

        # Initiate a UnitOfWork Session
        uow = UnitOfWork()
        uow.start()

        repo_with_uow = test_domain.repository_for(Person)

        # Create a new person object to be added
        person_to_be_added = Person(first_name="John", last_name="Doe")
        repo_with_uow.add(person_to_be_added)

        # Update an existing Person record
        person_to_be_updated.last_name = "FooBar"
        repo_with_uow.add(person_to_be_updated)

        # Remove an existing Person record
        repo_with_uow.remove(person_to_be_deleted)

        # Test that the underlying database is untouched
        assert len(person_dao.query.all().items) == 2
        assert (
            person_dao.outside_uow().get(person_to_be_updated.id).last_name != "FooBar"
        )
        assert person_dao.get(person_to_be_deleted.id) is not None

        uow.rollback()

        assert uow.in_progress is False
        assert len(person_dao.query.all().items) == 2
        assert person_dao.get(person_to_be_updated.id).last_name != "FooBar"
        assert person_dao.get(person_to_be_deleted.id) is not None

    def test_session_is_destroyed_after_commit(self, test_domain):
        uow = UnitOfWork()
        uow.start()

        uow.commit()
        assert uow._sessions == {}
        assert uow.in_progress is False

    def test_session_is_destroyed_after_rollback(self, test_domain):
        uow = UnitOfWork()
        uow.start()

        uow.rollback()
        assert uow._sessions == {}
        assert uow.in_progress is False
