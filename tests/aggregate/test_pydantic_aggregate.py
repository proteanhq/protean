"""Tests for the new Pydantic-based BaseAggregate.

Validates:
- Creation with annotated fields
- Field mutation with Pydantic validate_assignment
- _initialized flag lifecycle
- _EntityState tracking (new/changed/persisted/destroyed)
- Invariant pre/post checks
- Identity-based equality and hashing
- Root/owner hierarchy setup
- Version tracking
- Template dict initialization
- Serialization via to_dict()
- Extra fields rejected
"""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity, invariant
from protean.exceptions import NotSupportedError, ValidationError


# ---------------------------------------------------------------------------
# Test domain elements (Pydantic syntax)
# ---------------------------------------------------------------------------
class Person(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    first_name: str
    last_name: str
    age: int = 21


class Role(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: Annotated[str, Field(max_length=15)]


class Account(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: Annotated[str, Field(max_length=50)]
    balance: float = 0.0

    @invariant.post
    def balance_must_not_be_negative(self):
        if self.balance < 0:
            raise ValidationError({"balance": ["Balance must not be negative"]})

    @invariant.pre
    def cannot_modify_frozen_account(self):
        if getattr(self, "_frozen", False):
            raise ValidationError({"_entity": ["Cannot modify a frozen account"]})


class Item(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: Annotated[str, Field(max_length=50)]
    price: float = Field(ge=0)

    @invariant.post
    def price_must_be_positive(self):
        if self.price <= 0:
            raise ValidationError({"price": ["Price must be positive"]})


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(Role)
    test_domain.register(Account)
    test_domain.register(Item, part_of=Account)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Tests: Structure
# ---------------------------------------------------------------------------
class TestPydanticAggregateStructure:
    def test_base_aggregate_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError) as exc:
            BaseAggregate()
        assert "cannot be instantiated" in str(exc.value)

    def test_aggregate_has_container_fields(self):
        from protean.utils.reflection import _FIELDS

        cf = getattr(Role, _FIELDS, {})
        assert "id" in cf
        assert "name" in cf

    def test_aggregate_tracks_id_field(self):
        from protean.utils.reflection import _ID_FIELD_NAME

        assert getattr(Role, _ID_FIELD_NAME) == "id"

    def test_field_definitions(self):
        from protean.utils.reflection import _FIELDS

        cf = getattr(Person, _FIELDS, {})
        assert set(cf.keys()) == {"id", "first_name", "last_name", "age"}


# ---------------------------------------------------------------------------
# Tests: Initialization
# ---------------------------------------------------------------------------
class TestPydanticAggregateInitialization:
    def test_successful_creation(self):
        role = Role(name="ADMIN")
        assert role.name == "ADMIN"
        assert role.id is not None

    def test_initialized_flag_is_true(self):
        role = Role(name="ADMIN")
        assert role._initialized is True

    def test_default_values_applied(self):
        person = Person(first_name="John", last_name="Doe")
        assert person.age == 21

    def test_explicit_default_override(self):
        person = Person(first_name="John", last_name="Doe", age=35)
        assert person.age == 35

    def test_individuality(self):
        r1 = Role(name="ADMIN")
        r2 = Role(name="USER")
        assert r1.name == "ADMIN"
        assert r2.name == "USER"
        assert r1.id != r2.id

    def test_template_dict_initialization(self):
        person = Person({"first_name": "John", "last_name": "Doe", "age": 23})
        assert person.first_name == "John"
        assert person.last_name == "Doe"
        assert person.age == 23

    def test_template_must_be_dict(self):
        with pytest.raises(AssertionError) as exc:
            Person(["John", "Doe", 23])
        assert "must be a dict" in str(exc.value)

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            Role(name="ADMIN", unknown="bad")


# ---------------------------------------------------------------------------
# Tests: Validation
# ---------------------------------------------------------------------------
class TestPydanticAggregateValidation:
    def test_max_length_constraint(self):
        with pytest.raises(ValidationError):
            Role(name="THIS_IS_A_VERY_LONG_ROLE_NAME")

    def test_type_rejection(self):
        with pytest.raises(ValidationError):
            Person(first_name="John", last_name="Doe", age="old")

    def test_post_invariant_on_init(self):
        with pytest.raises(ValidationError) as exc_info:
            Account(name="Savings", balance=-100.0)
        assert "balance" in exc_info.value.messages


# ---------------------------------------------------------------------------
# Tests: Root and Owner
# ---------------------------------------------------------------------------
class TestPydanticAggregateRootOwner:
    def test_root_is_self(self):
        account = Account(name="Savings")
        assert account._root is account

    def test_owner_is_self(self):
        account = Account(name="Savings")
        assert account._owner is account


# ---------------------------------------------------------------------------
# Tests: Mutation
# ---------------------------------------------------------------------------
class TestPydanticAggregateMutation:
    def test_mutate_field(self):
        person = Person(first_name="John", last_name="Doe")
        person.first_name = "Jane"
        assert person.first_name == "Jane"

    def test_mutation_validates_assignment(self):
        role = Role(name="ADMIN")
        with pytest.raises(ValidationError):
            role.name = "X" * 16  # max_length=15 violation

    def test_mutation_type_check(self):
        person = Person(first_name="John", last_name="Doe")
        with pytest.raises(ValidationError):
            person.age = "not_a_number"

    def test_post_invariant_on_mutation(self):
        account = Account(name="Savings", balance=100.0)
        with pytest.raises(ValidationError) as exc_info:
            account.balance = -50.0
        assert "balance" in exc_info.value.messages

    def test_pre_invariant_on_mutation(self):
        account = Account(name="Savings", balance=100.0)
        account._frozen = True

        with pytest.raises(ValidationError) as exc_info:
            account.balance = 200.0
        assert "_entity" in exc_info.value.messages


# ---------------------------------------------------------------------------
# Tests: State tracking
# ---------------------------------------------------------------------------
class TestPydanticAggregateState:
    def test_new_aggregate_is_new(self):
        person = Person(first_name="John", last_name="Doe")
        assert person.state_ is not None
        assert person.state_.is_new is True
        assert person.state_.is_changed is False
        assert person.state_.is_persisted is False

    def test_mark_saved(self):
        person = Person(first_name="John", last_name="Doe")
        person.state_.mark_saved()
        assert person.state_.is_new is False
        assert person.state_.is_persisted is True

    def test_new_aggregate_not_marked_changed_on_mutation(self):
        """A new aggregate remains 'new' — not 'changed' — when mutated."""
        person = Person(first_name="John", last_name="Doe")
        assert person.state_.is_changed is False
        person.first_name = "Jane"
        assert person.state_.is_changed is False  # still new, not changed
        assert person.state_.is_new is True

    def test_persisted_aggregate_marked_changed_on_mutation(self):
        """After being persisted (mark_saved), mutations mark aggregate as changed."""
        person = Person(first_name="John", last_name="Doe")
        person.state_.mark_saved()
        assert person.state_.is_changed is False

        person.first_name = "Jane"
        assert person.state_.is_changed is True

    def test_mark_destroyed(self):
        person = Person(first_name="John", last_name="Doe")
        person.state_.mark_destroyed()
        assert person.state_.is_destroyed is True


# ---------------------------------------------------------------------------
# Tests: Version tracking
# ---------------------------------------------------------------------------
class TestPydanticAggregateVersioning:
    def test_initial_version(self):
        role = Role(name="ADMIN")
        assert role._version == -1
        assert role._next_version == 0

    def test_event_position_starts_at_negative_one(self):
        role = Role(name="ADMIN")
        assert role._event_position == -1


# ---------------------------------------------------------------------------
# Tests: Identity-based equality
# ---------------------------------------------------------------------------
class TestPydanticAggregateEquality:
    def test_same_id_equal(self):
        uid = str(uuid4())
        r1 = Role(id=uid, name="ADMIN")
        r2 = Role(id=uid, name="USER")
        assert r1 == r2

    def test_different_id_not_equal(self):
        r1 = Role(name="ADMIN")
        r2 = Role(name="ADMIN")
        assert r1 != r2

    def test_different_type_not_equal(self):
        uid = str(uuid4())
        r = Role(id=uid, name="ADMIN")
        p = Person(id=uid, first_name="John", last_name="Doe")
        assert r != p

    def test_hashable(self):
        uid = str(uuid4())
        r1 = Role(id=uid, name="ADMIN")
        r2 = Role(id=uid, name="USER")
        assert hash(r1) == hash(r2)
        s = {r1, r2}
        assert len(s) == 1


# ---------------------------------------------------------------------------
# Tests: Serialization
# ---------------------------------------------------------------------------
class TestPydanticAggregateSerialization:
    def test_to_dict(self):
        uid = str(uuid4())
        person = Person(id=uid, first_name="John", last_name="Doe", age=30)
        data = person.to_dict()
        assert data["id"] == uid
        assert data["first_name"] == "John"
        assert data["last_name"] == "Doe"
        assert data["age"] == 30

    def test_to_dict_excludes_private(self):
        person = Person(first_name="John", last_name="Doe")
        data = person.to_dict()
        assert "_state" not in data
        assert "_root" not in data
        assert "_owner" not in data
        assert "_events" not in data
        assert "_version" not in data
        assert "_next_version" not in data
        assert "_event_position" not in data

    def test_model_dump(self):
        uid = str(uuid4())
        person = Person(id=uid, first_name="John", last_name="Doe", age=30)
        data = person.model_dump()
        assert data["id"] == uid
        assert data["first_name"] == "John"

    def test_model_dump_excludes_private(self):
        person = Person(first_name="John", last_name="Doe")
        data = person.model_dump()
        assert "_state" not in data
        assert "_root" not in data
        assert "_version" not in data


# ---------------------------------------------------------------------------
# Tests: Invariant registration
# ---------------------------------------------------------------------------
class TestPydanticAggregateInvariants:
    def test_post_invariants_discovered(self):
        account = Account(name="Savings", balance=100.0)
        assert "balance_must_not_be_negative" in account._invariants.get("post", {})

    def test_pre_invariants_discovered(self):
        account = Account(name="Savings", balance=100.0)
        assert "cannot_modify_frozen_account" in account._invariants.get("pre", {})

    def test_entity_invariants_discovered(self):
        item = Item(name="Widget", price=10.0)
        assert "price_must_be_positive" in item._invariants.get("post", {})


# ---------------------------------------------------------------------------
# Tests: Entity within aggregate context
# ---------------------------------------------------------------------------
class TestPydanticEntityInAggregate:
    def test_entity_creation(self):
        item = Item(name="Widget", price=10.0)
        assert item.name == "Widget"
        assert item.price == 10.0
        assert item.id is not None

    def test_entity_mutation_validates(self):
        item = Item(name="Widget", price=10.0)
        with pytest.raises(ValidationError):
            item.price = -5.0  # ge=0 violation

    def test_entity_post_invariant(self):
        with pytest.raises(ValidationError) as exc_info:
            Item(name="Widget", price=0.0)
        assert "price" in exc_info.value.messages
