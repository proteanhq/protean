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
        the outermost commit persists nothing."""
        repo = test_domain.repository_for(Person)
        with UnitOfWork():
            repo.add(Person(first_name="A", last_name="X"))
            inner = UnitOfWork()
            inner.start()
            repo.add(Person(first_name="B", last_name="X"))
            inner.rollback()
            repo.add(Person(first_name="C", last_name="X"))
        assert _count(test_domain) == 0
