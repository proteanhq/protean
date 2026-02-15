"""Tests for BaseEntity basics.

Validates:
- Creation with annotated fields
- Field mutation with validate_assignment
- _initialized flag lifecycle
- _EntityState tracking (new/changed/persisted/destroyed)
- Invariant pre/post checks
- Identity-based equality and hashing
- Template dict initialization
- Serialization via to_dict()
- Extra fields rejected
"""

from typing import Annotated
from uuid import uuid4

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity, invariant
from protean.exceptions import NotSupportedError, ValidationError


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class Warehouse(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: Annotated[str, Field(max_length=50)]


class Product(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: Annotated[str, Field(max_length=50)]
    price: float = Field(ge=0)
    quantity: int = 0

    @invariant.post
    def price_must_be_positive(self):
        if self.price <= 0:
            raise ValidationError({"price": ["Price must be positive"]})


class StrictProduct(BaseEntity):
    """Entity with both pre and post invariants."""

    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: str
    status: str = "active"
    price: float = 0.0

    @invariant.pre
    def cannot_modify_if_discontinued(self):
        if self.status == "discontinued":
            raise ValidationError({"_entity": ["Cannot modify a discontinued product"]})

    @invariant.post
    def price_must_not_be_negative(self):
        if self.price < 0:
            raise ValidationError({"price": ["Price must not be negative"]})


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Warehouse)
    test_domain.register(Product, part_of=Warehouse)
    test_domain.register(StrictProduct, part_of=Warehouse)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Tests: Structure
# ---------------------------------------------------------------------------
class TestEntityStructure:
    def test_base_entity_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError) as exc:
            BaseEntity()
        assert "cannot be instantiated" in str(exc.value)

    def test_entity_has_container_fields(self):
        from protean.utils.reflection import _FIELDS

        cf = getattr(Product, _FIELDS, {})
        assert "id" in cf
        assert "name" in cf
        assert "price" in cf
        assert "quantity" in cf

    def test_entity_tracks_id_field(self):
        from protean.utils.reflection import _ID_FIELD_NAME

        assert getattr(Product, _ID_FIELD_NAME) == "id"


# ---------------------------------------------------------------------------
# Tests: Initialization
# ---------------------------------------------------------------------------
class TestEntityInitialization:
    def test_successful_creation(self):
        product = Product(name="Widget", price=10.0, quantity=5)
        assert product.name == "Widget"
        assert product.price == 10.0
        assert product.quantity == 5
        assert product.id is not None

    def test_initialized_flag_is_true(self):
        product = Product(name="Widget", price=10.0)
        assert product._initialized is True

    def test_default_values_applied(self):
        product = Product(name="Widget", price=10.0)
        assert product.quantity == 0

    def test_explicit_id(self):
        uid = str(uuid4())
        product = Product(id=uid, name="Widget", price=10.0)
        assert product.id == uid

    def test_individuality(self):
        p1 = Product(name="Widget", price=10.0)
        p2 = Product(name="Gadget", price=20.0)
        assert p1.name == "Widget"
        assert p2.name == "Gadget"
        assert p1.id != p2.id

    def test_template_dict_initialization(self):
        product = Product({"name": "Widget", "price": 10.0, "quantity": 3})
        assert product.name == "Widget"
        assert product.price == 10.0
        assert product.quantity == 3

    def test_template_must_be_dict(self):
        with pytest.raises(AssertionError) as exc:
            Product(["Widget", 10.0, 3])
        assert "must be a dict" in str(exc.value)

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            Product(name="Widget", price=10.0, unknown_field="bad")


# ---------------------------------------------------------------------------
# Tests: Validation
# ---------------------------------------------------------------------------
class TestEntityValidation:
    def test_field_constraint_on_init(self):
        """Field(ge=0) prevents negative price at init."""
        with pytest.raises(ValidationError):
            Product(name="Widget", price=-1.0)

    def test_max_length_constraint(self):
        with pytest.raises(ValidationError):
            Product(name="X" * 51, price=10.0)

    def test_type_coercion_or_rejection(self):
        """Incompatible types are rejected."""
        with pytest.raises(ValidationError):
            Product(name="Widget", price="not_a_number")

    def test_post_invariant_on_init(self):
        """Post-invariant fires during model_post_init."""
        with pytest.raises(ValidationError) as exc_info:
            Product(name="Widget", price=0.0)  # price <= 0
        assert "price" in exc_info.value.messages


# ---------------------------------------------------------------------------
# Tests: Mutation
# ---------------------------------------------------------------------------
class TestEntityMutation:
    def test_mutate_field(self):
        product = Product(name="Widget", price=10.0)
        product.name = "Gadget"
        assert product.name == "Gadget"

    def test_mutation_validates_assignment(self):
        """validate_assignment=True enforces constraints on mutation."""
        product = Product(name="Widget", price=10.0)
        with pytest.raises(ValidationError):
            product.price = -5.0  # ge=0 violation

    def test_mutation_type_check(self):
        product = Product(name="Widget", price=10.0)
        with pytest.raises(ValidationError):
            product.quantity = "not_a_number"

    def test_post_invariant_on_mutation(self):
        """Post-invariant fires after field mutation via __setattr__."""
        product = Product(name="Widget", price=10.0)
        with pytest.raises(ValidationError) as exc_info:
            product.price = 0.0  # triggers post-invariant
        assert "price" in exc_info.value.messages

    def test_pre_invariant_on_mutation(self):
        """Pre-invariant fires before field mutation via __setattr__."""
        sp = StrictProduct(name="Widget", price=10.0)
        sp.status = "discontinued"

        with pytest.raises(ValidationError) as exc_info:
            sp.price = 20.0  # triggers pre-invariant
        assert "_entity" in exc_info.value.messages


# ---------------------------------------------------------------------------
# Tests: State tracking
# ---------------------------------------------------------------------------
class TestEntityState:
    def test_new_entity_is_new(self):
        product = Product(name="Widget", price=10.0)
        assert product.state_.is_new is True
        assert product.state_.is_changed is False
        assert product.state_.is_persisted is False
        assert product.state_.is_destroyed is False

    def test_initialized_with_default_values(self):
        product = Product(name="Widget", price=10.0)
        assert product._initialized is True
        assert product.quantity == 0

    def test_mark_saved(self):
        product = Product(name="Widget", price=10.0)
        product.state_.mark_saved()
        assert product.state_.is_new is False
        assert product.state_.is_persisted is True

    def test_new_entity_not_marked_changed_on_mutation(self):
        """A new entity remains 'new' — not 'changed' — when mutated."""
        product = Product(name="Widget", price=10.0)
        assert product.state_.is_changed is False
        product.quantity = 5
        assert product.state_.is_changed is False  # still new, not changed

    def test_persisted_entity_marked_changed_on_mutation(self):
        """After being persisted (mark_saved), mutations mark entity as changed."""
        product = Product(name="Widget", price=10.0)
        product.state_.mark_saved()
        assert product.state_.is_changed is False

        product.quantity = 5
        assert product.state_.is_changed is True

    def test_mark_destroyed(self):
        product = Product(name="Widget", price=10.0)
        product.state_.mark_destroyed()
        assert product.state_.is_destroyed is True


# ---------------------------------------------------------------------------
# Tests: Identity-based equality
# ---------------------------------------------------------------------------
class TestEntityEquality:
    def test_same_id_equal(self):
        uid = str(uuid4())
        p1 = Product(id=uid, name="one", price=10.0)
        p2 = Product(id=uid, name="two", price=20.0)
        assert p1 == p2

    def test_different_id_not_equal(self):
        p1 = Product(name="same", price=10.0)
        p2 = Product(name="same", price=10.0)
        assert p1 != p2  # Different auto-generated IDs

    def test_different_type_not_equal(self):
        uid = str(uuid4())
        p = Product(id=uid, name="test", price=10.0)
        sp = StrictProduct(id=uid, name="test", price=10.0)
        assert p != sp

    def test_hashable(self):
        uid = str(uuid4())
        p1 = Product(id=uid, name="test", price=10.0)
        p2 = Product(id=uid, name="test", price=10.0)
        assert hash(p1) == hash(p2)
        s = {p1, p2}
        assert len(s) == 1


# ---------------------------------------------------------------------------
# Tests: Serialization
# ---------------------------------------------------------------------------
class TestEntitySerialization:
    def test_to_dict(self):
        uid = str(uuid4())
        product = Product(id=uid, name="Widget", price=10.0, quantity=5)
        data = product.to_dict()
        assert data["id"] == uid
        assert data["name"] == "Widget"
        assert data["price"] == 10.0
        assert data["quantity"] == 5

    def test_to_dict_excludes_private_attrs(self):
        product = Product(name="Widget", price=10.0)
        data = product.to_dict()
        assert "_state" not in data
        assert "_root" not in data
        assert "_owner" not in data
        assert "_events" not in data
        assert "_initialized" not in data

    def test_model_dump(self):
        uid = str(uuid4())
        product = Product(id=uid, name="Widget", price=10.0, quantity=5)
        data = product.model_dump()
        assert data["id"] == uid
        assert data["name"] == "Widget"
        assert data["price"] == 10.0
        assert data["quantity"] == 5

    def test_model_dump_excludes_private(self):
        product = Product(name="Widget", price=10.0)
        data = product.model_dump()
        assert "_state" not in data
        assert "_root" not in data
        assert "_events" not in data


# ---------------------------------------------------------------------------
# Tests: Invariant registration
# ---------------------------------------------------------------------------
class TestEntityInvariants:
    def test_post_invariants_discovered(self):
        product = Product(name="Widget", price=10.0)
        assert "price_must_be_positive" in product._invariants.get("post", {})

    def test_pre_and_post_invariants_discovered(self):
        sp = StrictProduct(name="Widget", price=10.0)
        assert "cannot_modify_if_discontinued" in sp._invariants.get("pre", {})
        assert "price_must_not_be_negative" in sp._invariants.get("post", {})
