"""Generic atomic transaction tests for providers with real database-level atomicity.

These tests verify rollback undoes changes, concurrent version conflicts are
handled atomically, and failure recovery works. They require real database-level
atomicity (not simulated).
"""

from datetime import datetime

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.fields import DateTime, Integer, String


class Person(BaseAggregate):
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    age: Integer(default=21)
    created_at: DateTime(default=datetime.now())


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.init(traverse=False)


@pytest.mark.atomic_transactions
class TestAtomicTransactions:
    """Tests that require real database-level atomicity (SQL only)."""

    def test_transaction_rollback(self, test_domain):
        """Test transaction rollback on exception"""
        person = Person(first_name="Jane", last_name="Doe", age=30)

        with pytest.raises(Exception):
            with UnitOfWork():
                test_domain.repository_for(Person).add(person)
                # Force a rollback by raising an exception
                raise ValueError("Forced rollback")

        # Verify the person was not saved
        all_persons = test_domain.repository_for(Person).query.all()
        assert len(all_persons) == 0

    def test_partial_transaction_rollback(self, test_domain):
        """Test that rollback undoes all operations in a failed transaction"""
        person1 = Person(first_name="Alice", last_name="Smith", age=28)
        person2 = Person(first_name="Bob", last_name="Jones", age=32)

        with pytest.raises(Exception):
            with UnitOfWork():
                test_domain.repository_for(Person).add(person1)
                test_domain.repository_for(Person).add(person2)
                raise ValueError("Forced rollback after multiple adds")

        # Verify neither person was saved
        all_persons = test_domain.repository_for(Person).query.all()
        assert len(all_persons) == 0

    def test_successful_transaction_after_failed_one(self, test_domain):
        """Test that a successful transaction works after a failed one"""
        # First, a failed transaction
        with pytest.raises(Exception):
            with UnitOfWork():
                test_domain.repository_for(Person).add(
                    Person(first_name="Failed", last_name="Person", age=99)
                )
                raise ValueError("Forced rollback")

        # Then a successful transaction
        person = Person(first_name="Success", last_name="Person", age=25)
        with UnitOfWork():
            test_domain.repository_for(Person).add(person)

        # Verify only the successful person exists
        all_persons = test_domain.repository_for(Person).query.all()
        assert len(all_persons) == 1
        assert all_persons.first.first_name == "Success"
