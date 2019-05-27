import pytest

from protean.core.unit_of_work import UnitOfWork


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
    @pytest.mark.skip
    def test_uow_new_object_registration(self):
        pass

    @pytest.mark.skip
    def test_uow_update_object_registration(self):
        pass

    @pytest.mark.skip
    def test_uow_delete_object_registration(self):
        pass


class TestUnitOfWorkTransactions:
    @pytest.mark.skip
    def test_changes_to_be_committed(self):
        pass

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
