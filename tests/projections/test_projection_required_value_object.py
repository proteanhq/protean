"""Tests that a projection enforces its required ValueObject fields at construction."""

import pytest

from protean.core.projection import BaseProjection, _projection_init_context
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String, ValueObject


class Money(BaseValueObject):
    amount = Float()


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


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Money)
    test_domain.register(Price)
    test_domain.register(OptionalPrice)
    test_domain.register(NamedPrice)
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
        outer = {"descriptor_kwargs": {}, "shadow_kwargs": {}}
        stack.append(outer)
        try:
            with pytest.raises(ValidationError):
                NamedPrice(pid="p")

            assert _projection_init_context.stack[-1] is outer
        finally:
            stack.remove(outer)
