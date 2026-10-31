import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, HasMany, Identifier, Integer, String
from protean.ir.diagnostics import DiagnosticCode

POST = DiagnosticCode.INVARIANT_POST_FAILED.value
PRE = DiagnosticCode.INVARIANT_PRE_FAILED.value


class Inventory(BaseAggregate):
    name: String(max_length=50)
    products = HasMany("Product")


class Product(BaseEntity):
    name: String(max_length=10, required=True)
    price: Float(required=True)
    quantity: Integer(required=True)

    @invariant.post
    def check_price_is_positive(self):
        if self.price <= 0:
            raise ValidationError({"price": ["Price must be positive"]})


class Account(BaseAggregate):
    account_number: Identifier(identifier=True)
    balance: Float(default=0.0)
    status: String(choices=["ACTIVE", "FROZEN"], default="ACTIVE")

    @invariant.pre
    def account_must_be_active_to_transact(self):
        if self.status == "FROZEN":
            raise ValidationError({"_entity": ["Cannot modify a frozen account"]})

    @invariant.post
    def balance_must_not_be_negative(self):
        if self.balance < 0:
            raise ValidationError({"balance": ["Insufficient funds"]})


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account)
    test_domain.register(Inventory)
    test_domain.register(Product, part_of=Inventory)
    test_domain.init(traverse=False)


def test_entity_invariant_raises_error_on_initialization():
    with pytest.raises(ValidationError) as exc:
        Product(name="Widget", price=-10.0, quantity=5)

    assert "price" in exc.value.messages
    assert "must be positive" in exc.value.messages["price"][0]


class TestFieldValidationsBeforeInvariants:
    """Test that field-level validations are checked first,
    and invariants are only run when field validations pass."""

    def test_field_validation_errors_prevent_invariant_checks(self):
        """When field-level validations fail, invariants should not be run.

        Name exceeds max_length (10), and price is negative which would
        fail the invariant - but since field validation fails first,
        invariant should not run.
        """
        # Name too long (max_length=10) with data that would fail invariant
        with pytest.raises(ValidationError) as exc:
            Product(name="this_name_is_way_too_long", price=-10.0, quantity=5)

        # Only field validation error should be raised, not invariant error
        assert "name" in exc.value.messages
        assert "price" not in exc.value.messages

    def test_required_field_missing_prevents_invariant_checks(self):
        """When required fields are missing, invariants should not be run."""
        # Missing required price field
        with pytest.raises(ValidationError) as exc:
            Product(name="Widget", quantity=5)

        # Required field error should be raised (not invariant error)
        assert "price" in exc.value.messages
        assert "is required" in exc.value.messages["price"][0]
        assert "must be positive" not in str(exc.value.messages)

    def test_invalid_field_type_prevents_invariant_checks(self):
        """When field type validation fails, invariants should not be run."""
        # Invalid type for float field
        with pytest.raises(ValidationError) as exc:
            Product(name="Widget", price="not_a_number", quantity=5)

        # Type validation error should be raised, not invariant error
        assert "price" in exc.value.messages
        assert "must be positive" not in str(exc.value.messages)

    def test_invariants_run_when_field_validations_pass(self):
        """Invariants should be run when all field validations pass."""
        # Valid fields but fails invariant
        with pytest.raises(ValidationError) as exc:
            Product(name="Widget", price=-10.0, quantity=5)

        # Invariant error should be raised
        assert "price" in exc.value.messages
        assert "must be positive" in exc.value.messages["price"][0]

    def test_multiple_field_errors_collected_before_invariant_check(self):
        """Multiple field validation errors should be collected,
        and invariants should not run.
        """
        # Multiple fields have validation errors
        with pytest.raises(ValidationError) as exc:
            Product(name="this_name_is_way_too_long", price="invalid", quantity="bad")

        # Field errors should be present, not invariant error
        assert "name" in exc.value.messages
        assert "price" in exc.value.messages
        assert "quantity" in exc.value.messages
        assert "must be positive" not in str(exc.value.messages)


class TestInvariantErrorMessagesArePlainDicts:
    """A failed invariant raises ``messages`` as a plain ``dict`` on every path.

    The checks use ``type(...) is dict`` because a ``defaultdict`` is a ``dict``
    subclass and would pass ``isinstance``.
    """

    def test_post_invariant_failure_on_construction(self):
        with pytest.raises(ValidationError) as exc:
            Account(account_number="1", balance=-5.0)

        assert type(exc.value.messages) is dict
        assert exc.value.messages == {"balance": ["Insufficient funds"]}
        assert exc.value.codes == [POST]

    def test_post_invariant_failure_on_update(self):
        account = Account(account_number="2", balance=50.0)

        with pytest.raises(ValidationError) as exc:
            account.balance = -5.0

        assert type(exc.value.messages) is dict
        assert exc.value.messages == {"balance": ["Insufficient funds"]}
        assert exc.value.codes == [POST]

    def test_pre_invariant_failure_on_update(self):
        account = Account(account_number="3", balance=50.0, status="FROZEN")

        with pytest.raises(ValidationError) as exc:
            account.balance = 10.0

        assert type(exc.value.messages) is dict
        assert exc.value.messages == {"_entity": ["Cannot modify a frozen account"]}
        assert exc.value.codes == [PRE]

    def test_missing_key_raises_key_error_on_update(self):
        account = Account(account_number="4", balance=50.0)

        with pytest.raises(ValidationError) as exc:
            account.balance = -5.0

        with pytest.raises(KeyError):
            exc.value.messages["absent"]
        # The failed lookup does not add the key.
        assert exc.value.messages == {"balance": ["Insufficient funds"]}

    def test_child_entity_failure_reaching_the_root_on_update(self):
        inventory = Inventory(name="Store")
        inventory.add_products(Product(name="Widget", price=10.0, quantity=1))
        product = inventory.products[0]

        with pytest.raises(ValidationError) as exc:
            product.price = -5.0

        assert type(exc.value.messages) is dict
        assert exc.value.messages == {"price": ["Price must be positive"]}
        assert exc.value.codes == [POST]
        assert exc.value.location == "Inventory"
