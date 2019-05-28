import pytest

from protean.core.unit_of_work import UnitOfWork

from .elements import Person, PersonRepository


class TestUnitOfWorkInitialization:
    @pytest.fixture
    def test_domain(self):
        from protean.domain import Domain
        domain = Domain('Test', 'tests.unit_of_work.config')

        yield domain

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
            assert uow.sessions is not None
            assert 'default' in uow.sessions


class TestUnitOfWorkRegistration:
    @pytest.fixture
    def test_domain(self):
        from protean.domain import Domain
        domain = Domain('Test', 'tests.unit_of_work.config')

        yield domain

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, aggregate=Person)

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

            assert person.id in uow.objects_to_be_added

    def test_new_object_registration_with_uow_passed_through_repository_within_method(self, test_domain):
        with UnitOfWork(test_domain) as uow:
            repo = test_domain.repository_for(Person).within(uow)
            person = Person(first_name='John', last_name='Doe')
            repo.add(person)

            assert person.id in uow.objects_to_be_added

    def test_that_there_is_no_update_registration_if_object_is_unchanged(self, test_domain, persisted_person):
        with UnitOfWork(test_domain) as uow:
            repo = test_domain.repository_for(Person).within(uow)
            repo.add(persisted_person)

            assert persisted_person.id not in uow.objects_to_be_updated

    def test_update_registration_for_changed_object_with_uow(self, test_domain, persisted_person):
        with UnitOfWork(test_domain) as uow:
            repo = test_domain.repository_for(Person).within(uow)
            persisted_person.last_name = 'Dane'
            repo.add(persisted_person)

            assert persisted_person.id in uow.objects_to_be_updated

    def test_delete_registration_for_object_to_be_removed(self, test_domain, persisted_person):
        with UnitOfWork(test_domain) as uow:
            repo = test_domain.repository_for(Person).within(uow)
            repo.remove(persisted_person)

            assert persisted_person.id in uow.objects_to_be_removed


class TestUnitOfWorkTransactions:
    @pytest.fixture
    def test_domain(self):
        from protean.domain import Domain
        domain = Domain('Test', 'tests.unit_of_work.config')

        yield domain

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, aggregate=Person)

        yield

    def persisted_person(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name='John', last_name='Doe')
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

            assert len(uow.changes_to_be_committed['ADDED']) == 1
            assert len(uow.changes_to_be_committed['UPDATED']) == 1
            assert len(uow.changes_to_be_committed['REMOVED']) == 1

    @pytest.mark.skip
    def test_all_changes_are_committed_as_part_of_one_transaction(self):
        pass

    @pytest.mark.skip
    def test_all_changes_are_rolledback_on_failure(self):
        pass

    @pytest.mark.skip
    def test_session_is_destroyed_after_commit(self):
        pass

    @pytest.mark.skip
    def test_session_is_destroyed_after_rollback(self):
        pass


class TestUnitOfWorkWithMultipleProviders:
    @pytest.mark.skip
    def test_sessions_across_multiple_providers_are_committed_together(self):
        pass

    @pytest.mark.skip
    def test_sessions_across_multiple_providers_are_rolled_back_together(self):
        pass
