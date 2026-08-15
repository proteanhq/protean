"""A failed runtime invariant carries a coded diagnostic on its ValidationError.

Covers the entity/aggregate `_run_invariants` raise path: the default codes per
stage, the `@invariant.pre/post(code=...)` override, the merged multi-code case,
the child-entity recursion, and that a passing invariant carries no code.
"""

import pickle

import pytest

from protean.core.aggregate import BaseAggregate, atomic_change
from protean.core.entity import BaseEntity, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, HasMany, Identifier, Integer, String
from protean.ir.diagnostics import DiagnosticCode, resolve

POST = DiagnosticCode.INVARIANT_POST_FAILED.value
PRE = DiagnosticCode.INVARIANT_PRE_FAILED.value


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

    def withdraw(self, amount):
        self.balance -= amount


class Order(BaseAggregate):
    order_id: Identifier(identifier=True)
    total: Float(default=0.0)
    status: String(default="PENDING")

    @invariant.post(code="ORDER_TOTAL_NEGATIVE")
    def total_non_negative(self):
        if self.total < 0:
            raise ValidationError({"total": ["Total must be >= 0"]})

    @invariant.post(code="ORDER_STATUS_UNKNOWN")
    def status_is_known(self):
        if self.status not in ("PENDING", "CONFIRMED"):
            raise ValidationError({"status": ["Unknown status"]})


class Widget(BaseAggregate):
    widget_id: Identifier(identifier=True)
    a: Integer(default=0)
    b: Integer(default=0)

    @invariant.post
    def a_non_negative(self):
        if self.a < 0:
            raise ValidationError({"a": ["a must be >= 0"]})

    @invariant.post
    def b_non_negative(self):
        if self.b < 0:
            raise ValidationError({"b": ["b must be >= 0"]})


class Inventory(BaseAggregate):
    name: String(max_length=50)
    products = HasMany("Product")

    @invariant.post(code="INV_NAME_RESERVED")
    def name_is_not_reserved(self):
        if self.name == "RESERVED":
            raise ValidationError({"name": ["Name is reserved"]})


class Product(BaseEntity):
    name: String(max_length=50, required=True)
    price: Float(required=True)

    @invariant.post
    def price_must_be_positive(self):
        if self.price <= 0:
            raise ValidationError({"price": ["Price must be positive"]})


class Gadget(BaseAggregate):
    gadget_id: Identifier(identifier=True)
    value: Integer(default=0)
    status: String(choices=["ON", "OFF"], default="ON")

    @invariant.pre(code="GADGET_OFF")
    def must_be_on_to_change(self):
        if self.status == "OFF":
            raise ValidationError({"_entity": ["Gadget is off"]})

    @invariant.post(code=DiagnosticCode.INVARIANT_POST_FAILED)
    def value_must_be_non_negative(self):
        if self.value < 0:
            raise ValidationError({"value": ["value must be >= 0"]})

    def bump(self, delta):
        self.value += delta


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account)
    test_domain.register(Order)
    test_domain.register(Widget)
    test_domain.register(Inventory)
    test_domain.register(Product, part_of=Inventory)
    test_domain.register(Gadget)
    test_domain.init(traverse=False)


class TestDefaultCodes:
    def test_post_invariant_failure_on_init_carries_the_post_code(self):
        with pytest.raises(ValidationError) as exc:
            Account(account_number="1", balance=-5.0)

        assert exc.value.code == POST
        assert exc.value.codes == [POST]
        assert exc.value.location == "Account"
        # The errors dict is unchanged by the code.
        assert exc.value.messages == {"balance": ["Insufficient funds"]}

    def test_post_invariant_failure_on_mutation_carries_the_post_code(self):
        account = Account(account_number="2", balance=50.0, status="ACTIVE")

        with pytest.raises(ValidationError) as exc:
            account.withdraw(100.0)

        assert exc.value.code == POST
        assert exc.value.codes == [POST]

    def test_pre_invariant_failure_on_mutation_carries_the_pre_code(self):
        account = Account(account_number="3", balance=100.0, status="FROZEN")

        with pytest.raises(ValidationError) as exc:
            account.withdraw(10.0)

        assert exc.value.code == PRE
        assert exc.value.codes == [PRE]
        assert "_entity" in exc.value.messages

    def test_rationale_and_fix_resolve_from_the_registry(self):
        with pytest.raises(ValidationError) as exc:
            Account(account_number="4", balance=-5.0)

        meta = resolve(DiagnosticCode.INVARIANT_POST_FAILED)
        assert exc.value.rationale == meta.rationale
        assert exc.value.fix == meta.fix

    def test_a_valid_aggregate_constructs_without_a_coded_error(self):
        # The negative case: valid input raises nothing, so no code is produced.
        account = Account(account_number="5", balance=10.0, status="ACTIVE")
        assert account.balance == 10.0


class TestAuthorSuppliedCode:
    def test_custom_code_is_carried(self):
        with pytest.raises(ValidationError) as exc:
            Order(order_id="1", total=-5.0, status="PENDING")

        assert exc.value.code == "ORDER_TOTAL_NEGATIVE"
        assert exc.value.codes == ["ORDER_TOTAL_NEGATIVE"]
        assert exc.value.messages == {"total": ["Total must be >= 0"]}

    def test_a_custom_code_outside_the_registry_has_no_rationale_or_fix(self):
        with pytest.raises(ValidationError) as exc:
            Order(order_id="2", total=-5.0, status="PENDING")

        assert exc.value.rationale is None
        assert exc.value.fix is None

    def test_only_the_failing_invariant_contributes_its_code(self):
        # status_is_known passes here, so its code must be absent from codes.
        with pytest.raises(ValidationError) as exc:
            Order(order_id="5", total=-5.0, status="PENDING")

        assert exc.value.codes == ["ORDER_TOTAL_NEGATIVE"]
        assert "ORDER_STATUS_UNKNOWN" not in exc.value.codes

    def test_a_diagnostic_code_member_is_carried_as_its_value(self):
        # Gadget declares code=DiagnosticCode.INVARIANT_POST_FAILED (a member).
        with pytest.raises(ValidationError) as exc:
            Gadget(gadget_id="1", value=-1)

        assert exc.value.codes == [POST]
        assert type(exc.value.codes[0]) is str

    def test_custom_pre_code_rides_through_a_mutation_raise(self):
        gadget = Gadget(gadget_id="2", value=0, status="OFF")

        with pytest.raises(ValidationError) as exc:
            gadget.bump(1)

        assert exc.value.code == "GADGET_OFF"
        assert exc.value.codes == ["GADGET_OFF"]


class TestMultipleInvariantsFailingTogether:
    def test_two_distinct_codes_are_both_carried(self):
        with pytest.raises(ValidationError) as exc:
            Order(order_id="3", total=-5.0, status="BOGUS")

        # Both invariants fired; both codes ride on ``codes``.
        assert exc.value.codes == ["ORDER_TOTAL_NEGATIVE", "ORDER_STATUS_UNKNOWN"]
        # No single code names the failure, so ``code`` is None.
        assert exc.value.code is None
        # The merged errors dict is unchanged.
        assert exc.value.messages == {
            "total": ["Total must be >= 0"],
            "status": ["Unknown status"],
        }

    def test_two_default_coded_invariants_dedupe_to_one_code(self):
        with pytest.raises(ValidationError) as exc:
            Widget(widget_id="1", a=-1, b=-1)

        # Both default post failures share INVARIANT_POST_FAILED; carried once.
        assert exc.value.codes == [POST]
        assert exc.value.code == POST
        # Both violations are still reported.
        assert set(exc.value.messages) == {"a", "b"}


class TestChildEntityRecursion:
    def test_child_invariant_failure_carries_a_code_at_the_root(self):
        inventory = Inventory(name="Store")
        inventory.add_products(Product(name="Widget", price=10.0))
        product = inventory.products[0]

        with pytest.raises(ValidationError) as exc:
            product.price = -5.0

        assert exc.value.code == POST
        assert exc.value.codes == [POST]
        # The raise happens at the aggregate root, so the location is the root.
        assert exc.value.location == "Inventory"
        assert "price" in exc.value.messages

    def test_parent_and_child_invariants_failing_together_carry_both_codes(self):
        inventory = Inventory(name="Store")
        inventory.add_products(Product(name="Widget", price=10.0))
        product = inventory.products[0]

        # Batch both mutations so the checks run once, on exit, at the root: the
        # parent's own invariant and the child's both fail in one raise.
        with pytest.raises(ValidationError) as exc:
            with atomic_change(inventory):
                inventory.name = "RESERVED"
                product.price = -5.0

        # Parent's own invariant fires first, then the child's via recursion.
        assert exc.value.codes == ["INV_NAME_RESERVED", POST]
        assert exc.value.code is None
        assert exc.value.location == "Inventory"
        assert set(exc.value.messages) == {"name", "price"}


class TestPickleRoundTrip:
    def test_codes_survive_a_pickle_round_trip(self):
        with pytest.raises(ValidationError) as exc:
            Order(order_id="4", total=-5.0, status="BOGUS")

        restored = pickle.loads(pickle.dumps(exc.value))

        assert type(restored) is ValidationError
        assert restored.codes == ["ORDER_TOTAL_NEGATIVE", "ORDER_STATUS_UNKNOWN"]
        assert restored.code is None
        assert restored.location == "Order"
        assert restored.messages == {
            "total": ["Total must be >= 0"],
            "status": ["Unknown status"],
        }


class TestInvariantDecorator:
    def test_bare_pre_and_post_still_mark_the_stage(self):
        assert Account.balance_must_not_be_negative._invariant == "post"
        assert Account.account_must_be_active_to_transact._invariant == "pre"

    def test_bare_invariant_declares_no_code(self):
        assert not hasattr(Account.balance_must_not_be_negative, "_invariant_code")

    def test_code_argument_is_recorded_on_the_method(self):
        assert Order.total_non_negative._invariant == "post"
        assert Order.total_non_negative._invariant_code == "ORDER_TOTAL_NEGATIVE"

    def test_empty_parens_form_marks_the_stage_with_no_code(self):
        @invariant.post()
        def check(self): ...

        assert check._invariant == "post"
        assert not hasattr(check, "_invariant_code")

    def test_code_can_be_a_diagnostic_code_member(self):
        @invariant.pre(code=DiagnosticCode.INVARIANT_PRE_FAILED)
        def check(self): ...

        assert check._invariant == "pre"
        assert check._invariant_code == DiagnosticCode.INVARIANT_PRE_FAILED
