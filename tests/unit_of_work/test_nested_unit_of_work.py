"""Nested Unit-of-Work semantics.

A `UnitOfWork` started while another is already active on the same context is a
participant in the outer transaction, not a new one. There are no savepoints, so
it joins the outer: it does not push onto the context stack (writes keep resolving
to the outermost UoW), and only the outermost UoW commits or rolls back the real
transaction.

Without this, a nested UoW shared the outer's session and its commit durably
persisted the outer's still-pending writes while its rollback discarded them,
silently breaking atomicity. These tests pin the joined behavior; each fails on the
pre-flatten model.
"""

import pytest

from protean import UnitOfWork
from protean.exceptions import TransactionError
from protean.utils.globals import _uow_context_stack

from .elements import Person, PersonRepository


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonRepository, part_of=Person)
    test_domain.init(traverse=False)


def _count(test_domain):
    return len(test_domain.repository_for(Person)._dao.query.all().items)


class TestNestedUnitOfWork:
    def test_nested_is_transparent_active_uow_stays_the_outer(self, test_domain):
        with UnitOfWork() as outer:
            with UnitOfWork() as inner:
                assert inner._nested is True
                # The active UoW inside the nested block is still the outer: the
                # nested UoW did not push itself onto the context stack.
                assert _uow_context_stack.top is outer
            # Leaving the inner block does not end the outer.
            assert outer.in_progress is True

    def test_nested_commit_persists_all(self, test_domain):
        repo = test_domain.repository_for(Person)
        with UnitOfWork():
            repo.add(Person(first_name="A", last_name="X"))
            with UnitOfWork():
                repo.add(Person(first_name="B", last_name="X"))
            repo.add(Person(first_name="C", last_name="X"))
        assert _count(test_domain) == 3

    def test_outer_rollback_after_inner_commit_persists_nothing(self, test_domain):
        """The corruption repro: an inner UoW 'commits', then the outer rolls back.
        Nothing must persist, because the inner commit did not durably write."""
        repo = test_domain.repository_for(Person)
        with pytest.raises(RuntimeError):
            with UnitOfWork():
                repo.add(Person(first_name="A", last_name="X"))
                with UnitOfWork():
                    repo.add(Person(first_name="B", last_name="X"))
                repo.add(Person(first_name="C", last_name="X"))
                raise RuntimeError("force outer rollback")
        assert _count(test_domain) == 0

    def test_exception_inside_inner_rolls_back_all(self, test_domain):
        repo = test_domain.repository_for(Person)
        with pytest.raises(RuntimeError):
            with UnitOfWork():
                repo.add(Person(first_name="A", last_name="X"))
                with UnitOfWork():
                    repo.add(Person(first_name="B", last_name="X"))
                    raise RuntimeError("boom in inner")
        assert _count(test_domain) == 0

    def test_explicit_inner_rollback_dooms_the_transaction(self, test_domain):
        """A nested rollback rolls back the whole transaction (no savepoints), so
        the outermost commit persists nothing and raises TransactionError."""
        repo = test_domain.repository_for(Person)
        with pytest.raises(TransactionError, match="rollback-only"):
            with UnitOfWork():
                repo.add(Person(first_name="A", last_name="X"))
                inner = UnitOfWork()
                inner.start()
                repo.add(Person(first_name="B", last_name="X"))
                inner.rollback()
                repo.add(Person(first_name="C", last_name="X"))
        assert _count(test_domain) == 0
        assert _uow_context_stack.top is None

    def test_reused_instance_is_not_stuck_nested(self, test_domain):
        """A UnitOfWork instance reused after being nested must behave as a normal
        outermost UoW. ``start()`` recomputes nesting, so a stale ``_nested`` from
        the earlier nested use cannot make the reused commit a silent no-op (which
        would lose the write and leave the instance poisoning the context stack)."""
        repo = test_domain.repository_for(Person)
        u = UnitOfWork()
        with UnitOfWork():
            u.start()  # used as a nested participant
            u.commit()

        # Reuse the same instance as the outermost UoW.
        u.start()
        assert u._nested is False  # recomputed: the stack was empty this time
        repo.add(Person(first_name="KEPT", last_name="X"))
        u.commit()

        assert _uow_context_stack.top is None  # u popped itself, no poisoning
        assert _count(test_domain) == 1  # the write persisted


class TestOuterCommitOfADoomedTransaction:
    """The outermost commit raises when a nested UnitOfWork failed and the
    failure was caught before the outer block ended."""

    def test_outer_commit_of_a_doomed_transaction_raises(self, test_domain):
        repo = test_domain.repository_for(Person)
        err = RuntimeError("boom")
        with pytest.raises(RuntimeError) as excinfo:
            with UnitOfWork():
                repo.add(Person(first_name="A", last_name="X"))
                try:
                    with UnitOfWork():
                        raise err
                except RuntimeError:
                    pass
        assert excinfo.value is err
        assert _count(test_domain) == 0
        assert _uow_context_stack.top is None

    def test_direct_commit_raises_the_cause_and_rolls_back(self, test_domain):
        repo = test_domain.repository_for(Person)
        err = ValueError("inner failure")
        uow = UnitOfWork()
        uow.start()
        repo.add(Person(first_name="A", last_name="X"))
        try:
            with UnitOfWork():
                raise err
        except ValueError:
            pass

        with pytest.raises(ValueError) as excinfo:
            uow.commit()

        assert excinfo.value is err
        assert uow.in_progress is False
        assert _uow_context_stack.top is None
        assert _count(test_domain) == 0

    def test_the_first_nested_failure_is_raised(self, test_domain):
        first = RuntimeError("first")
        with pytest.raises(RuntimeError) as excinfo:
            with UnitOfWork():
                try:
                    with UnitOfWork():
                        raise first
                except RuntimeError:
                    pass
                try:
                    with UnitOfWork():
                        raise KeyError("second")
                except KeyError:
                    pass
        assert excinfo.value is first

    def test_the_cause_is_not_replaced_by_a_second_rollback(self, test_domain):
        """``__exit__`` must not roll back the already rolled-back transaction
        again, which would raise InvalidOperationError instead of the cause."""
        caught: list[BaseException] = []
        try:
            with UnitOfWork():
                try:
                    with UnitOfWork():
                        raise LookupError("cause")
                except LookupError:
                    pass
        except Exception as exc:
            caught.append(exc)

        assert len(caught) == 1
        assert type(caught[0]) is LookupError
        assert caught[0].args == ("cause",)

    def test_a_doomed_instance_commits_normally_when_reused(self, test_domain):
        repo = test_domain.repository_for(Person)
        uow = UnitOfWork()
        with pytest.raises(RuntimeError):
            with uow:
                try:
                    with UnitOfWork():
                        raise RuntimeError("boom")
                except RuntimeError:
                    pass

        with uow:
            repo.add(Person(first_name="KEPT", last_name="X"))

        assert _count(test_domain) == 1
        assert _uow_context_stack.top is None

    def test_the_cause_is_dropped_when_the_outer_block_raises(self, test_domain):
        uow = UnitOfWork()
        with pytest.raises(KeyError):
            with uow:
                try:
                    with UnitOfWork():
                        raise RuntimeError("inner")
                except RuntimeError:
                    pass
                assert isinstance(uow._rollback_cause, RuntimeError)
                raise KeyError("outer")

        assert uow._rollback_cause is None
        assert uow.in_progress is False

    def test_the_cause_is_dropped_by_a_manual_rollback(self, test_domain):
        uow = UnitOfWork()
        uow.start()
        try:
            with UnitOfWork():
                raise RuntimeError("inner")
        except RuntimeError:
            pass
        assert isinstance(uow._rollback_cause, RuntimeError)

        uow.rollback()

        assert uow._rollback_cause is None
        assert uow.in_progress is False
