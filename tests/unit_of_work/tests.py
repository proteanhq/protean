import pytest

from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import InvalidOperationError


class TestUnitOfWorkInitialization:
    def test_uow_can_be_initiated_with_context_manager(self, test_domain):
        with UnitOfWork() as uow:
            assert uow is not None
            assert uow.in_progress is True

    def test_uow_can_be_initiated_explicitly(self, test_domain):
        uow = UnitOfWork()
        assert uow is not None
        assert uow.in_progress is False

        uow.start()
        assert uow.in_progress is True

    def test_that_uow_throws_exception_on_commit_or_rollback_without_being_started(
        self, test_domain
    ):
        uow = UnitOfWork()

        with pytest.raises(InvalidOperationError):
            uow.commit()

        with pytest.raises(InvalidOperationError):
            uow.rollback()

    def test_that_uow_can_be_started_manually(self, test_domain):
        uow = UnitOfWork()

        uow.start()
        uow.commit()  # `commit` should not raise exception

        uow.start()
        uow.rollback()  # `rollback` should not raise exception
