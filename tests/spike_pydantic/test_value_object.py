"""PoC tests for ProteanValueObject (Pydantic native).

Validates:
- Frozen model blocks mutation
- Field validation works (types, constraints)
- Nested VOs work as Pydantic nested models
- @invariant.post runs after init
- model_dump() serialization
- model_json_schema() generation
- Equality by value (Pydantic default for frozen)
- Extra fields rejected
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import Field, ValidationError

from tests.spike_pydantic.base_classes import (
    Options,
    ProteanValueObject,
    invariant,
)


# ---------------------------------------------------------------------------
# Test VOs
# ---------------------------------------------------------------------------
class Email(ProteanValueObject):
    address: str

    @invariant.post
    def must_contain_at(self):
        if "@" not in self.address:
            from protean.exceptions import ValidationError as PValidationError

            raise PValidationError({"address": ["must contain @"]})


class Address(ProteanValueObject):
    street: str
    city: str
    zip_code: Annotated[str, Field(max_length=10)]
    country: str = "US"


class Money(ProteanValueObject):
    amount: float = Field(ge=0)
    currency: str = Field(max_length=3, min_length=3)


class NestedVO(ProteanValueObject):
    """A VO containing another VO."""

    email: Email
    address: Address


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestFrozenModel:
    """ProteanValueObject must be immutable after creation."""

    def test_creation(self):
        addr = Address(street="123 Main", city="NYC", zip_code="10001")
        assert addr.street == "123 Main"
        assert addr.city == "NYC"
        assert addr.zip_code == "10001"
        assert addr.country == "US"

    def test_frozen_blocks_mutation(self):
        addr = Address(street="123 Main", city="NYC", zip_code="10001")
        with pytest.raises(ValidationError):
            addr.street = "456 Oak"

    def test_frozen_blocks_deletion(self):
        addr = Address(street="123 Main", city="NYC", zip_code="10001")
        with pytest.raises(ValidationError):
            del addr.street

    def test_default_values(self):
        addr = Address(street="123 Main", city="NYC", zip_code="10001")
        assert addr.country == "US"

    def test_override_default(self):
        addr = Address(street="123 Main", city="NYC", zip_code="10001", country="UK")
        assert addr.country == "UK"


class TestFieldValidation:
    """Pydantic field validation for VOs."""

    def test_max_length(self):
        with pytest.raises(ValidationError) as exc_info:
            Address(street="123 Main", city="NYC", zip_code="12345678901")  # > 10
        assert "zip_code" in str(exc_info.value)

    def test_min_value(self):
        with pytest.raises(ValidationError) as exc_info:
            Money(amount=-5.0, currency="USD")
        assert "amount" in str(exc_info.value)

    def test_min_length(self):
        with pytest.raises(ValidationError) as exc_info:
            Money(amount=10.0, currency="US")  # < 3
        assert "currency" in str(exc_info.value)

    def test_type_coercion(self):
        """Pydantic coerces compatible types by default."""
        m = Money(amount=10, currency="USD")  # int → float
        assert isinstance(m.amount, (int, float))
        assert m.amount == 10.0

    def test_type_rejection(self):
        with pytest.raises(ValidationError):
            Money(amount="not_a_number", currency="USD")

    def test_missing_required(self):
        with pytest.raises(ValidationError) as exc_info:
            Address(city="NYC", zip_code="10001")  # missing street
        assert "street" in str(exc_info.value)


class TestExtraFieldsRejected:
    """extra='forbid' rejects unknown attributes."""

    def test_extra_field_in_init(self):
        with pytest.raises(ValidationError) as exc_info:
            Address(
                street="123 Main", city="NYC", zip_code="10001", unknown_field="oops"
            )
        assert "extra" in str(exc_info.value).lower()


class TestInvariants:
    """@invariant.post runs after init."""

    def test_invariant_passes(self):
        email = Email(address="user@example.com")
        assert email.address == "user@example.com"

    def test_invariant_fails(self):
        from protean.exceptions import ValidationError as PValidationError

        with pytest.raises(PValidationError) as exc_info:
            Email(address="invalid-email")
        assert "address" in exc_info.value.messages


class TestSerialization:
    """model_dump() and related serialization."""

    def test_model_dump(self):
        addr = Address(street="123 Main", city="NYC", zip_code="10001", country="US")
        data = addr.model_dump()
        assert data == {
            "street": "123 Main",
            "city": "NYC",
            "zip_code": "10001",
            "country": "US",
        }

    def test_model_dump_json(self):
        addr = Address(street="123 Main", city="NYC", zip_code="10001")
        json_str = addr.model_dump_json()
        assert '"street":"123 Main"' in json_str or '"street": "123 Main"' in json_str

    def test_round_trip(self):
        """Create from dict, dump back, should be identical."""
        data = {
            "street": "123 Main",
            "city": "NYC",
            "zip_code": "10001",
            "country": "US",
        }
        addr = Address(**data)
        assert addr.model_dump() == data


class TestNestedVO:
    """VO containing another VO (Pydantic nested model)."""

    def test_nested_creation(self):
        nested = NestedVO(
            email=Email(address="user@example.com"),
            address=Address(street="123 Main", city="NYC", zip_code="10001"),
        )
        assert nested.email.address == "user@example.com"
        assert nested.address.city == "NYC"

    def test_nested_from_dict(self):
        """Pydantic should construct nested models from dicts."""
        nested = NestedVO(
            email={"address": "user@example.com"},
            address={"street": "123 Main", "city": "NYC", "zip_code": "10001"},
        )
        assert isinstance(nested.email, Email)
        assert isinstance(nested.address, Address)
        assert nested.email.address == "user@example.com"

    def test_nested_model_dump(self):
        nested = NestedVO(
            email=Email(address="user@example.com"),
            address=Address(street="123 Main", city="NYC", zip_code="10001"),
        )
        data = nested.model_dump()
        assert data["email"]["address"] == "user@example.com"
        assert data["address"]["street"] == "123 Main"
        assert data["address"]["country"] == "US"

    def test_nested_invariant_runs(self):
        """Invariants on nested VO should still run."""
        from protean.exceptions import ValidationError as PValidationError

        with pytest.raises(PValidationError):
            NestedVO(
                email=Email(address="invalid"),  # triggers Email invariant
                address=Address(street="123 Main", city="NYC", zip_code="10001"),
            )

    def test_nested_validation_from_dict(self):
        """Validation on nested VO from dict should still work."""
        from protean.exceptions import ValidationError as PValidationError

        with pytest.raises((ValidationError, PValidationError)):
            NestedVO(
                email={"address": "invalid"},  # should trigger Email invariant
                address={"street": "123 Main", "city": "NYC", "zip_code": "10001"},
            )


class TestEqualityByValue:
    """Frozen Pydantic models use value-based equality."""

    def test_equal_values(self):
        a1 = Address(street="123 Main", city="NYC", zip_code="10001")
        a2 = Address(street="123 Main", city="NYC", zip_code="10001")
        assert a1 == a2

    def test_different_values(self):
        a1 = Address(street="123 Main", city="NYC", zip_code="10001")
        a2 = Address(street="456 Oak", city="NYC", zip_code="10001")
        assert a1 != a2

    def test_hashable(self):
        """Frozen models should be hashable."""
        a1 = Address(street="123 Main", city="NYC", zip_code="10001")
        a2 = Address(street="123 Main", city="NYC", zip_code="10001")
        assert hash(a1) == hash(a2)
        # Can be used in sets
        s = {a1, a2}
        assert len(s) == 1

    def test_can_be_dict_key(self):
        addr = Address(street="123 Main", city="NYC", zip_code="10001")
        d = {addr: "some value"}
        assert d[addr] == "some value"


class TestJsonSchema:
    """model_json_schema() generates correct JSON Schema."""

    def test_basic_schema(self):
        schema = Address.model_json_schema()
        assert schema["type"] == "object"
        assert "street" in schema["properties"]
        assert "city" in schema["properties"]
        assert "zip_code" in schema["properties"]
        assert "country" in schema["properties"]

    def test_required_fields(self):
        schema = Address.model_json_schema()
        required = schema.get("required", [])
        assert "street" in required
        assert "city" in required
        assert "zip_code" in required
        # country has default, so not required
        assert "country" not in required

    def test_constraints_in_schema(self):
        schema = Address.model_json_schema()
        zip_props = schema["properties"]["zip_code"]
        assert zip_props.get("maxLength") == 10

    def test_money_schema_constraints(self):
        schema = Money.model_json_schema()
        amount_props = schema["properties"]["amount"]
        assert amount_props.get("minimum") == 0
        currency_props = schema["properties"]["currency"]
        assert currency_props.get("maxLength") == 3
        assert currency_props.get("minLength") == 3

    def test_nested_schema(self):
        schema = NestedVO.model_json_schema()
        # Nested schemas appear in $defs
        assert "$defs" in schema
        assert "Email" in schema["$defs"]
        assert "Address" in schema["$defs"]

    def test_schema_title(self):
        schema = Address.model_json_schema()
        assert schema["title"] == "Address"


class TestPrivateAttrs:
    """PrivateAttr (_meta, _invariants) should be accessible but not in schema."""

    def test_meta_accessible(self):
        addr = Address(street="123 Main", city="NYC", zip_code="10001")
        assert isinstance(addr._meta, Options)

    def test_meta_not_in_dump(self):
        addr = Address(street="123 Main", city="NYC", zip_code="10001")
        data = addr.model_dump()
        assert "_meta" not in data
        assert "_invariants" not in data

    def test_meta_not_in_schema(self):
        schema = Address.model_json_schema()
        assert "_meta" not in schema.get("properties", {})
        assert "_invariants" not in schema.get("properties", {})

    def test_meta_mutable_on_frozen(self):
        """PrivateAttrs should be mutable even on frozen models."""
        addr = Address(street="123 Main", city="NYC", zip_code="10001")
        addr._meta["custom_key"] = "custom_value"
        assert addr._meta["custom_key"] == "custom_value"
