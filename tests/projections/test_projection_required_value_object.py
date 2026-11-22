"""Tests that a projection enforces its required ValueObject fields at construction."""

import pytest

from protean.core.projection import BaseProjection, _projection_init_context
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String, ValueObject
from tests.shared import provider_adapter


class Money(BaseValueObject):
    amount = Float()


class Cost(BaseValueObject):
    amount = Float()
    currency = String(max_length=3)


class Price(BaseProjection):
    pid = Identifier(identifier=True)
    price = ValueObject(Money, required=True)


class OptionalPrice(BaseProjection):
    pid = Identifier(identifier=True)
    price = ValueObject(Money)


class CachedPrice(BaseProjection):
    pid = Identifier(identifier=True)
    price = ValueObject(Money, required=True)


class NamedPrice(BaseProjection):
    pid = Identifier(identifier=True)
    name = String(required=True)
    price = ValueObject(Money, required=True)


class CostedItem(BaseProjection):
    pid = Identifier(identifier=True)
    cost = ValueObject(Cost, required=True)


@pytest.fixture(scope="session")
def db_config():
    # The round-trip tests edit the memory adapter's stored records directly.
    return {"provider": "memory"}


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Money)
    test_domain.register(Price)
    test_domain.register(OptionalPrice)
    test_domain.register(NamedPrice)
    test_domain.register(Cost)
    test_domain.register(CostedItem)
    test_domain.register(CachedPrice, cache="default")
    test_domain.init(traverse=False)


def _shadow_names(projection_cls, field_name):
    field_obj = projection_cls.__dict__[field_name]
    names = [sf.attribute_name for sf in field_obj.embedded_fields.values()]
    assert names
    return names


def _stack_depth():
    return len(getattr(_projection_init_context, "stack", []))


class TestRequiredValueObject:
    def test_missing_required_value_object_raises(self):
        with pytest.raises(ValidationError) as exc:
            Price(pid="p")

        assert exc.value.messages == {"price": ["is required"]}

    def test_required_value_object_passed_as_none_raises(self):
        with pytest.raises(ValidationError) as exc:
            Price(pid="p", price=None)

        assert exc.value.messages == {"price": ["is required"]}

    def test_required_value_object_given_as_object_builds(self):
        price = Price(pid="p", price=Money(amount=1.0))

        assert price.price == Money(amount=1.0)

    def test_one_shadow_field_counts_as_given(self):
        shadow_names = _shadow_names(Price, "price")
        assert shadow_names == ["price_amount"]

        price = Price(pid="p", price_amount=1.0)

        assert price.price.amount == 1.0

    def test_one_of_two_shadow_fields_counts_as_given(self):
        shadow_names = _shadow_names(CostedItem, "cost")
        assert sorted(shadow_names) == ["cost_amount", "cost_currency"]

        item = CostedItem(pid="p", cost_amount=1.0)

        assert item.cost.amount == 1.0
        assert item.cost.currency is None

    def test_one_of_two_shadow_keys_present_with_none_counts_as_given(self):
        item = CostedItem(pid="p", cost_amount=None)

        assert item.pid == "p"
        assert item.cost is None

    def test_shadow_keys_present_with_none_count_as_given(self):
        # A field counts as given by key presence, which is how a stored
        # record with empty shadow columns loads back.
        price = Price(pid="p", **dict.fromkeys(_shadow_names(Price, "price")))

        assert price.pid == "p"
        assert price.price is None

    def test_optional_value_object_can_be_omitted(self):
        price = OptionalPrice(pid="p")

        assert price.price is None

    def test_pydantic_and_value_object_errors_are_raised_together(self):
        with pytest.raises(ValidationError) as exc:
            NamedPrice(pid="p")

        assert exc.value.messages == {
            "name": ["is required"],
            "price": ["is required"],
        }


class TestPersistenceRoundTrip:
    def test_required_value_object_round_trip(self, test_domain):
        repo = test_domain.repository_for(Price)
        repo.add(Price(pid="p1", price=Money(amount=2.5)))

        loaded = repo.get("p1")

        assert loaded.price == Money(amount=2.5)

    def test_required_value_object_stored_with_none_shadow_keys_loads(
        self, test_domain
    ):
        # A record whose shadow columns are all empty loads back, because the
        # loader passes every shadow key, ``None`` included.
        repo = test_domain.repository_for(Price)
        repo.add(Price(pid="r1", price=Money(amount=1.0)))
        record = provider_adapter(test_domain)._databases[Price.meta_.schema_name]["r1"]
        record["price_amount"] = None

        loaded = repo.get("r1")

        assert loaded.pid == "r1"
        assert loaded.price is None

    def test_optional_value_object_stored_as_none_round_trip(self, test_domain):
        repo = test_domain.repository_for(OptionalPrice)
        repo.add(OptionalPrice(pid="p2"))

        loaded = repo.get("p2")

        assert loaded.pid == "p2"
        assert loaded.price is None

    def test_required_value_object_cache_round_trip(self, test_domain):
        test_domain.cache_for(CachedPrice).add(
            CachedPrice(pid="p3", price=Money(amount=4.0))
        )

        loaded = test_domain.view_for(CachedPrice).get("p3")

        assert loaded.price == Money(amount=4.0)


class TestInitContextStack:
    def test_stack_balanced_after_successful_build(self):
        before = _stack_depth()

        Price(pid="p", price=Money(amount=1.0))

        assert _stack_depth() == before

    def test_stack_balanced_after_missing_value_object(self):
        before = _stack_depth()

        with pytest.raises(ValidationError):
            Price(pid="p")

        assert _stack_depth() == before

    def test_stack_balanced_after_pydantic_error(self):
        before = _stack_depth()

        with pytest.raises(ValidationError) as exc:
            NamedPrice(pid="p", price=Money(amount=1.0))

        assert exc.value.messages == {"name": ["is required"]}
        assert _stack_depth() == before

    def test_stack_balanced_after_both_errors(self):
        before = _stack_depth()

        with pytest.raises(ValidationError):
            NamedPrice(pid="p")

        assert _stack_depth() == before

    def test_failure_keeps_an_outer_entry_on_the_stack(self):
        stack = getattr(_projection_init_context, "stack", [])
        _projection_init_context.stack = stack
        before = len(stack)
        outer = {"descriptor_kwargs": {}, "shadow_kwargs": {}}
        stack.append(outer)
        try:
            with pytest.raises(ValidationError):
                NamedPrice(pid="p")

            assert len(_projection_init_context.stack) == before + 1
            assert _projection_init_context.stack[-1] is outer
        finally:
            del stack[before:]

    def test_success_keeps_an_outer_entry_on_the_stack(self):
        stack = getattr(_projection_init_context, "stack", [])
        _projection_init_context.stack = stack
        before = len(stack)
        outer = {"descriptor_kwargs": {}, "shadow_kwargs": {}}
        stack.append(outer)
        try:
            Price(pid="p", price=Money(amount=1.0))

            assert len(_projection_init_context.stack) == before + 1
            assert _projection_init_context.stack[-1] is outer
        finally:
            del stack[before:]
