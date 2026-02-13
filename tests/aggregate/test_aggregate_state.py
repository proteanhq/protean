import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.core.value_object import _LegacyBaseValueObject as BaseValueObject
from protean.exceptions import DatabaseError
from protean.fields import Float, Identifier, String, ValueObject

from .elements import Person, PersonRepository


class Balance(BaseValueObject):
    currency = String(max_length=3)
    amount = Float()


class BalanceUpdated(BaseEvent):
    account_id = Identifier(required=True)
    old_amount = Float()
    new_amount = Float()


class Account(BaseAggregate):
    name = String(max_length=50, required=True)
    balance = ValueObject(Balance)

    def update_balance(self, new_balance: Balance) -> None:
        old_amount = self.balance.amount if self.balance else 0.0
        self.balance = new_balance
        self.raise_(
            BalanceUpdated(
                account_id=self.id,
                old_amount=old_amount,
                new_amount=new_balance.amount,
            )
        )


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonRepository, part_of=Person)
    test_domain.init(traverse=False)


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestState:
    """Class that holds tests for Entity State Management"""

    def test_that_a_default_state_is_available_when_the_entity_instantiated(self):
        person = Person(first_name="John", last_name="Doe")
        assert person.state_ is not None
        assert person.state_._new
        assert person.state_.is_new
        assert not person.state_.is_persisted

    def test_that_retrieved_objects_are_not_marked_as_new(self, test_domain):
        person = test_domain.repository_for(Person)._dao.create(
            first_name="John", last_name="Doe"
        )
        db_person = test_domain.repository_for(Person)._dao.get(person.id)

        assert not db_person.state_.is_new

    def test_that_entity_is_marked_as_saved_after_successful_persistence(
        self, test_domain
    ):
        person = Person(first_name="John", last_name="Doe")
        assert person.state_.is_new

        test_domain.repository_for(Person)._dao.save(person)
        assert person.state_.is_persisted

    def test_that_a_new_entity_still_shows_as_new_if_persistence_failed(
        self, test_domain
    ):
        person = Person(first_name="John", last_name="Doe")
        try:
            del person.first_name
            test_domain.repository_for(Person)._dao.save(person)
        except DatabaseError:
            assert person.state_.is_new

    def test_that_a_changed_entity_still_shows_as_changed_if_persistence_failed(
        self, test_domain
    ):
        person = test_domain.repository_for(Person)._dao.create(
            first_name="John", last_name="Doe"
        )

        person.first_name = "Jane"
        assert person.state_.is_changed

        try:
            del person.first_name
            test_domain.repository_for(Person)._dao.save(person)
        except DatabaseError:
            assert person.state_.is_changed

    def test_that_entity_is_marked_as_not_new_after_successful_persistence(
        self, test_domain
    ):
        person = test_domain.repository_for(Person)._dao.create(
            first_name="John", last_name="Doe"
        )
        assert not person.state_.is_new

    def test_that_entity_marked_as_changed_if_attributes_are_updated(self, test_domain):
        person = test_domain.repository_for(Person)._dao.create(
            first_name="John", last_name="Doe"
        )
        assert not person.state_.is_changed

        person.first_name = "Jane"
        assert person.state_.is_changed

    def test_that_entity_is_not_marked_as_changed_upon_attr_change_if_still_new(self):
        person = Person(first_name="John", last_name="Doe")
        assert not person.state_.is_changed

        person.first_name = "Jane Doe"
        assert not person.state_.is_changed

    def test_that_aggregate_is_marked_as_not_changed_after_save(self, test_domain):
        person = test_domain.repository_for(Person)._dao.create(
            first_name="John", last_name="Doe"
        )
        person.first_name = "Jane"
        assert person.state_.is_changed

        test_domain.repository_for(Person)._dao.save(person)
        assert not person.state_.is_changed

    def test_that_an_entity_is_marked_as_destroyed_after_delete(self, test_domain):
        person = test_domain.repository_for(Person)._dao.create(
            first_name="John", last_name="Doe"
        )
        assert not person.state_.is_destroyed

        test_domain.repository_for(Person)._dao.delete(person)
        assert person.state_.is_destroyed


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestValueObjectFieldState:
    """Tests that ValueObject field changes correctly mark the aggregate as dirty"""

    @pytest.fixture(autouse=True)
    def register_vo_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(Balance, part_of=Account)
        test_domain.register(BalanceUpdated, part_of=Account)
        test_domain.init(traverse=False)

    def test_aggregate_marked_changed_on_value_object_update(self, test_domain):
        account = test_domain.repository_for(Account)._dao.create(
            name="Savings", balance=Balance(currency="USD", amount=100.0)
        )
        assert not account.state_.is_changed

        account.balance = Balance(currency="USD", amount=200.0)
        assert account.state_.is_changed

    def test_new_aggregate_not_marked_changed_on_value_object_update(self):
        account = Account(name="Savings", balance=Balance(currency="USD", amount=100.0))
        assert not account.state_.is_changed

        account.balance = Balance(currency="USD", amount=200.0)
        assert not account.state_.is_changed

    def test_vo_field_update_is_persisted_via_repo_add(self, test_domain):
        """Regression: repo.add() must save the aggregate when only a VO field changed."""
        repo = test_domain.repository_for(Account)
        account = repo.add(
            Account(name="Savings", balance=Balance(currency="USD", amount=100.0))
        )
        original_id = account.id

        account.balance = Balance(currency="USD", amount=200.0)
        repo.add(account)

        refreshed = repo.get(original_id)
        assert refreshed.balance.amount == 200.0

    def test_events_dispatched_after_vo_field_mutation(self, test_domain):
        """Regression: events raised alongside a VO mutation must not be lost."""
        repo = test_domain.repository_for(Account)
        account = repo.add(
            Account(name="Savings", balance=Balance(currency="USD", amount=100.0))
        )

        account.update_balance(Balance(currency="USD", amount=250.0))
        assert len(account._events) == 1

        repo.add(account)

        # Events should be cleared after successful commit (dispatched)
        assert len(account._events) == 0

        # Verify the value was also persisted
        refreshed = repo.get(account.id)
        assert refreshed.balance.amount == 250.0
