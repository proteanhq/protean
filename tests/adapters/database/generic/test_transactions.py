"""Generic transaction tests for providers with transaction support (real or simulated).

These tests exercise UoW commit, save, and create-within-uow flows.
They work with both simulated (Memory) and real (SQL) transactions.
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


@pytest.mark.transactional
class TestBasicTransactions:
    """Test basic transaction support across databases"""

    def test_successful_commit(self, test_domain):
        """Test successful transaction commit"""
        person = Person(first_name="John", last_name="Doe", age=25)

        with UnitOfWork():
            test_domain.repository_for(Person).add(person)

        # Verify the person was saved
        retrieved_person = test_domain.repository_for(Person).get(person.id)
        assert retrieved_person.first_name == "John"
        assert retrieved_person.last_name == "Doe"

    def test_multiple_operations_in_transaction(self, test_domain):
        """Test multiple operations within a single transaction"""
        person1 = Person(first_name="Alice", last_name="Smith", age=28)
        person2 = Person(first_name="Bob", last_name="Jones", age=32)

        with UnitOfWork():
            test_domain.repository_for(Person).add(person1)
            test_domain.repository_for(Person).add(person2)

        # Verify both persons were saved
        all_persons = test_domain.repository_for(Person).query.all()
        assert len(all_persons) == 2

        names = [p.first_name for p in all_persons]
        assert "Alice" in names
        assert "Bob" in names
