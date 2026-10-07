"""Check what docs/guides/change-state/unit-of-work.md says about the Unit of Work.

The page's examples work on an ``Order`` with a ``total`` and a ``status``.
``Order.confirm()`` sets the status to ``CONFIRMED`` and then raises
``ValidationError`` when the total is zero, so a failed confirm leaves a
changed object behind that must not reach the database. Each test loads the
example fresh, so every test gets its own domain and its own memory store.
"""

import threading

import pytest

from protean import UnitOfWork, current_uow
from protean.exceptions import ObjectNotFoundError, ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def activate(module):
    module.domain.init(traverse=False)
    return module.domain.domain_context()


@pytest.fixture
def example():
    module = load_example("guides/change-state/unit-of-work/001.py")
    with activate(module):
        yield module


@pytest.fixture
def rollback_example():
    module = load_example("guides/change-state/unit-of-work/002.py")
    with activate(module):
        yield module


def saved_order(module, total):
    order = module.Order(total=total)
    module.domain.repository_for(module.Order).add(order)
    return order.id


def status_of(module, order_id):
    return module.domain.repository_for(module.Order).get(order_id).status


class AddFails(Exception):
    """The failure a repository raises after it has stored the order."""


class RepositoryThatFailsAfterAdd:
    """Stores the aggregate, then raises, as a flush that fails part-way would.

    Without a Unit of Work around the call, the real ``add()`` commits at once,
    so the change survives the error. Inside one, the error rolls it back.
    """

    def __init__(self, repository, fail_on=None):
        self._repository = repository
        self._fail_on = fail_on

    def add(self, item):
        self._repository.add(item)
        if self._fail_on is None or item is self._fail_on:
            raise AddFails()
        return item

    def __getattr__(self, name):
        return getattr(self._repository, name)


@pytest.fixture
def add_fails(monkeypatch):
    """Make the example's ``repository_for`` hand out a repository whose
    ``add()`` stores the order and then raises."""

    def install(module):
        real = module.domain.repository_for
        monkeypatch.setattr(
            module.domain,
            "repository_for",
            lambda cls: RepositoryThatFailsAfterAdd(real(cls)),
        )

    return install


class TestContextManagerForm:
    def test_commits_the_change_when_the_block_exits(self, example):
        order_id = saved_order(example, 25.0)

        example.confirm_order(order_id)

        assert status_of(example, order_id) == "CONFIRMED"

    def test_persists_nothing_when_the_block_raises(self, example):
        order_id = saved_order(example, 0.0)

        with pytest.raises(ValidationError):
            example.confirm_order(order_id)

        assert status_of(example, order_id) == "PENDING"

    def test_rolls_back_a_change_already_added_when_add_raises(
        self, example, add_fails
    ):
        order_id = saved_order(example, 25.0)
        add_fails(example)

        with pytest.raises(AddFails):
            example.confirm_order(order_id)

        assert not current_uow
        assert status_of(example, order_id) == "PENDING"


class TestImperativeForm:
    def test_commit_saves_the_change(self, example):
        order_id = saved_order(example, 25.0)

        example.confirm_order_step_by_step(order_id)

        # commit() closes the unit of work, so no transaction is left open.
        assert not current_uow
        assert status_of(example, order_id) == "CONFIRMED"

    def test_rollback_discards_the_change_and_reraises(self, example):
        order_id = saved_order(example, 0.0)

        with pytest.raises(ValidationError):
            example.confirm_order_step_by_step(order_id)

        assert not current_uow
        assert status_of(example, order_id) == "PENDING"

    def test_rollback_discards_a_change_already_added(self, example, add_fails):
        order_id = saved_order(example, 25.0)
        add_fails(example)

        with pytest.raises(AddFails):
            example.confirm_order_step_by_step(order_id)

        assert not current_uow
        assert status_of(example, order_id) == "PENDING"


class TestRollbackExample:
    def test_confirms_a_valid_order(self, rollback_example):
        order_id = saved_order(rollback_example, 25.0)

        rollback_example.try_to_confirm_order(order_id)

        assert status_of(rollback_example, order_id) == "CONFIRMED"

    def test_catches_the_error_and_keeps_the_old_state(self, rollback_example):
        order_id = saved_order(rollback_example, 0.0)

        # The example catches ValidationError, so the call returns normally.
        assert rollback_example.try_to_confirm_order(order_id) is None
        assert status_of(rollback_example, order_id) == "PENDING"

    def test_rolls_back_when_add_raises(self, rollback_example, add_fails):
        order_id = saved_order(rollback_example, 25.0)
        add_fails(rollback_example)

        # Only ValidationError is caught, so the add() failure propagates.
        with pytest.raises(AddFails):
            rollback_example.try_to_confirm_order(order_id)

        assert not current_uow
        assert status_of(rollback_example, order_id) == "PENDING"


class TestNestedUnitsOfWork:
    def test_all_three_orders_commit_together(self, example):
        repo = example.domain.repository_for(example.Order)
        a, b, c = (example.Order(total=total) for total in (1.0, 2.0, 3.0))

        example.save_together(repo, a, b, c)

        assert [repo.get(o.id).total for o in (a, b, c)] == [1.0, 2.0, 3.0]

    def test_a_failure_on_c_rolls_back_a_and_b(self, example):
        repo = example.domain.repository_for(example.Order)
        a, b, c = (example.Order(total=total) for total in (1.0, 2.0, 3.0))

        # No outer UnitOfWork here: save_together's own blocks are the whole
        # transaction, so adding c failing must undo a and b as well.
        with pytest.raises(AddFails):
            example.save_together(RepositoryThatFailsAfterAdd(repo, c), a, b, c)

        assert not current_uow
        for order in (a, b, c):
            with pytest.raises(ObjectNotFoundError):
                repo.get(order.id)

    def test_nested_work_is_not_visible_until_the_outermost_exits(self, example):
        repo = example.domain.repository_for(example.Order)
        a, b, c = (example.Order(total=total) for total in (1.0, 2.0, 3.0))
        seen_from_another_thread = []

        def look_up_b():
            with example.domain.domain_context():
                try:
                    example.domain.repository_for(example.Order).get(b.id)
                    seen_from_another_thread.append(True)
                except ObjectNotFoundError:
                    seen_from_another_thread.append(False)

        def look_from_another_thread():
            reader = threading.Thread(target=look_up_b)
            reader.start()
            reader.join()

        with UnitOfWork():
            # save_together's own UnitOfWork blocks are both nested here.
            example.save_together(repo, a, b, c)
            look_from_another_thread()
        look_from_another_thread()

        assert seen_from_another_thread == [False, True]

    def test_rolling_back_the_outermost_discards_the_nested_work(self, example):
        repo = example.domain.repository_for(example.Order)
        a, b, c = (example.Order(total=total) for total in (1.0, 2.0, 3.0))

        with pytest.raises(RuntimeError):
            with UnitOfWork():
                example.save_together(repo, a, b, c)
                raise RuntimeError("fail after the nested blocks exited")

        for order in (a, b, c):
            with pytest.raises(ObjectNotFoundError):
                repo.get(order.id)
