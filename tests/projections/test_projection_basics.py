"""Tests for BaseProjection basics.

Validates:
- Creation with annotated fields
- Field mutation with validate_assignment
- _EntityState tracking (new/persisted)
- Identity-based equality and hashing
- Template dict initialization
- Serialization via to_dict() and model_dump()
- Meta options (abstract, schema_name, provider, cache, order_by, limit)
- Defaults hook
- Extra fields rejected
- Registration with domain
"""

from enum import Enum
from typing import Annotated

import pytest
from pydantic import Field

from protean.core.projection import BaseProjection
from protean.exceptions import (
    IncorrectUsageError,
    NotSupportedError,
    ValidationError,
)
from protean.utils import fully_qualified_name
from protean.utils.reflection import _FIELDS, _ID_FIELD_NAME


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class Person(BaseProjection):
    person_id: str = Field(json_schema_extra={"identifier": True})
    first_name: str
    last_name: str | None = None
    age: int = 21


class PersonExplicitID(BaseProjection):
    ssn: Annotated[str, Field(max_length=36)] = Field(
        json_schema_extra={"identifier": True},
    )
    first_name: str
    last_name: str | None = None
    age: int = 21


class AbstractPerson(BaseProjection):
    age: int = 5


class BuildingStatus(str, Enum):
    WIP = "WIP"
    DONE = "DONE"


class Building(BaseProjection):
    building_id: str = Field(json_schema_extra={"identifier": True})
    name: Annotated[str, Field(max_length=50)] | None = None
    floors: int | None = None
    status: str | None = None

    def defaults(self):
        if not self.status:
            if self.floors == 4:
                self.status = BuildingStatus.DONE.value
            else:
                self.status = BuildingStatus.WIP.value


class OrderedPerson(BaseProjection):
    person_id: str = Field(json_schema_extra={"identifier": True})
    first_name: str
    last_name: str | None = None
    age: int = 21


class PersonWithoutId(BaseProjection):
    first_name: str
    last_name: str | None = None


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonExplicitID)
    test_domain.register(AbstractPerson, abstract=True)
    test_domain.register(Building)
    test_domain.register(OrderedPerson, order_by="first_name")
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Tests: Structure
# ---------------------------------------------------------------------------
class TestProjectionStructure:
    def test_base_projection_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError) as exc:
            BaseProjection()
        assert "cannot be instantiated" in str(exc.value)

    def test_projection_has_container_fields(self):
        cf = getattr(Person, _FIELDS, {})
        assert "person_id" in cf
        assert "first_name" in cf
        assert "last_name" in cf
        assert "age" in cf

    def test_projection_tracks_id_field(self):
        assert getattr(Person, _ID_FIELD_NAME) == "person_id"

    def test_explicit_id_field_tracked(self):
        assert getattr(PersonExplicitID, _ID_FIELD_NAME) == "ssn"


# ---------------------------------------------------------------------------
# Tests: Registration
# ---------------------------------------------------------------------------
class TestProjectionRegistration:
    def test_manual_registration(self, test_domain):
        assert fully_qualified_name(Person) in test_domain.registry.projections

    def test_id_field_mandatory(self, test_domain):
        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(PersonWithoutId)
        assert "needs to have at least one identifier" in str(exc.value)

    def test_abstract_flag(self, test_domain):
        assert AbstractPerson.meta_.abstract is True

    def test_abstract_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError) as exc:
            AbstractPerson(age=30)
        assert "has been marked abstract" in str(exc.value)

    def test_concrete_projection_inheriting_abstract_base_tracks_id(self, test_domain):
        """Concrete projection registered via domain.register() after inheriting
        from an abstract base should correctly track its identifier field.

        Regression test: __pydantic_init_subclass__ skipped __track_id_field()
        because the inherited meta_.abstract was True at class-creation time.
        derive_element_class must re-trigger id tracking when clearing the flag.
        """

        @test_domain.projection(abstract=True)
        class AbstractBase:
            age: int = 0

        class ConcreteView(AbstractBase):
            view_id: str = Field(json_schema_extra={"identifier": True})
            name: str | None = None

        test_domain.register(ConcreteView)
        test_domain.init(traverse=False)

        assert ConcreteView.meta_.abstract is False
        assert hasattr(ConcreteView, _ID_FIELD_NAME)
        assert getattr(ConcreteView, _ID_FIELD_NAME) == "view_id"

        # Verify the projection can be instantiated and used
        view = ConcreteView(view_id="V-001", name="Test", age=25)
        assert view.view_id == "V-001"
        assert view.name == "Test"
        assert view.age == 25


# ---------------------------------------------------------------------------
# Tests: Initialization
# ---------------------------------------------------------------------------
class TestProjectionInitialization:
    def test_successful_creation(self):
        person = Person(person_id="123", first_name="John", last_name="Doe")
        assert person.person_id == "123"
        assert person.first_name == "John"
        assert person.last_name == "Doe"
        assert person.age == 21

    def test_default_values(self):
        person = Person(person_id="123", first_name="John")
        assert person.last_name is None
        assert person.age == 21

    def test_template_dict_initialization(self):
        person = Person({"person_id": "123", "first_name": "John", "age": 30})
        assert person.person_id == "123"
        assert person.first_name == "John"
        assert person.age == 30

    def test_template_must_be_dict(self):
        with pytest.raises(AssertionError) as exc:
            Person(["123", "John", "Doe"])
        assert "must be a dict" in str(exc.value)

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            Person(person_id="123", first_name="John", unknown="bad")

    def test_type_validation(self):
        with pytest.raises(ValidationError):
            Person(person_id="123", first_name="John", age="old")


# ---------------------------------------------------------------------------
# Tests: Defaults hook
# ---------------------------------------------------------------------------
class TestProjectionDefaults:
    def test_defaults_method_called(self):
        building = Building(building_id="B1", name="Tower", floors=4)
        assert building.status == BuildingStatus.DONE.value

    def test_defaults_with_different_value(self):
        building = Building(building_id="B2", name="House", floors=2)
        assert building.status == BuildingStatus.WIP.value


# ---------------------------------------------------------------------------
# Tests: Mutation
# ---------------------------------------------------------------------------
class TestProjectionMutation:
    def test_mutate_field(self):
        person = Person(person_id="123", first_name="John")
        person.first_name = "Jane"
        assert person.first_name == "Jane"

    def test_identifier_immutability(self):
        from protean.exceptions import InvalidOperationError

        person = PersonExplicitID(ssn="ABC", first_name="John")
        with pytest.raises(InvalidOperationError):
            person.ssn = "XYZ"  # identifier cannot be changed once set

    def test_mutation_type_check(self):
        person = Person(person_id="123", first_name="John")
        with pytest.raises(ValidationError):
            person.age = "not_a_number"


# ---------------------------------------------------------------------------
# Tests: State tracking
# ---------------------------------------------------------------------------
class TestProjectionState:
    def test_new_projection_has_state(self):
        person = Person(person_id="123", first_name="John")
        assert person.state_ is not None
        assert person.state_.is_new is True

    def test_mark_saved(self):
        person = Person(person_id="123", first_name="John")
        person.state_.mark_saved()
        assert person.state_.is_new is False
        assert person.state_.is_persisted is True

    def test_mark_destroyed(self):
        person = Person(person_id="123", first_name="John")
        person.state_.mark_destroyed()
        assert person.state_.is_destroyed is True

    def test_state_setter(self):
        """state_ property setter sets _state."""
        proj = Person(person_id="p-1", first_name="Alice")
        original_state = proj.state_
        proj.state_ = original_state
        assert proj.state_ is original_state


# ---------------------------------------------------------------------------
# Tests: Identity-based equality
# ---------------------------------------------------------------------------
class TestProjectionEquality:
    def test_same_id_equal(self):
        p1 = Person(person_id="123", first_name="John")
        p2 = Person(person_id="123", first_name="Jane")
        assert p1 == p2

    def test_different_id_not_equal(self):
        p1 = Person(person_id="123", first_name="John")
        p2 = Person(person_id="456", first_name="John")
        assert p1 != p2

    def test_different_type_not_equal(self):
        p = Person(person_id="123", first_name="John")
        pe = PersonExplicitID(ssn="123", first_name="John")
        assert p != pe

    def test_hashable(self):
        p1 = Person(person_id="123", first_name="John")
        p2 = Person(person_id="123", first_name="Jane")
        assert hash(p1) == hash(p2)
        s = {p1, p2}
        assert len(s) == 1

    def test_not_equal_to_non_projection(self):
        p = Person(person_id="123", first_name="John")
        assert p != "not a projection"

    def test_eq_without_id_field(self):
        """__eq__ returns False when _ID_FIELD_NAME is missing."""
        p1 = Person(person_id="123", first_name="John")
        p2 = Person(person_id="123", first_name="John")
        saved = getattr(Person, _ID_FIELD_NAME, None)
        try:
            delattr(Person, _ID_FIELD_NAME)
            assert p1 != p2
        finally:
            if saved is not None:
                setattr(Person, _ID_FIELD_NAME, saved)

    def test_hash_without_id_field(self):
        """__hash__ falls back to id(self) when no id field."""
        proj = Person(person_id="123", first_name="John")
        saved = getattr(Person, _ID_FIELD_NAME, None)
        try:
            delattr(Person, _ID_FIELD_NAME)
            assert hash(proj) == id(proj)
        finally:
            if saved is not None:
                setattr(Person, _ID_FIELD_NAME, saved)


# ---------------------------------------------------------------------------
# Tests: Serialization
# ---------------------------------------------------------------------------
class TestProjectionSerialization:
    def test_to_dict(self):
        person = Person(person_id="123", first_name="John", last_name="Doe", age=30)
        data = person.to_dict()
        assert data == {
            "person_id": "123",
            "first_name": "John",
            "last_name": "Doe",
            "age": 30,
        }

    def test_to_dict_with_none(self):
        person = Person(person_id="123", first_name="John")
        data = person.to_dict()
        assert data["last_name"] is None
        assert data["age"] == 21

    def test_to_dict_excludes_private(self):
        person = Person(person_id="123", first_name="John")
        data = person.to_dict()
        assert "_state" not in data

    def test_model_dump(self):
        person = Person(person_id="123", first_name="John", last_name="Doe", age=30)
        data = person.model_dump()
        assert data["person_id"] == "123"
        assert data["first_name"] == "John"

    def test_model_dump_excludes_private(self):
        person = Person(person_id="123", first_name="John")
        data = person.model_dump()
        assert "_state" not in data

    def test_str_output(self):
        person = Person(person_id="123", first_name="John")
        s = str(person)
        assert "Person object" in s
        assert "person_id" in s

    def test_repr_output(self):
        person = Person(person_id="123", first_name="John")
        r = repr(person)
        assert r.startswith("<Person:")
        assert r.endswith(">")


# ---------------------------------------------------------------------------
# Tests: Meta options
# ---------------------------------------------------------------------------
class TestProjectionMeta:
    def test_default_schema_name(self):
        assert Person.meta_.schema_name == "person"

    def test_default_provider(self):
        assert Person.meta_.provider == "default"

    def test_default_order_by(self):
        assert Person.meta_.order_by == ()

    def test_overridden_order_by(self):
        assert OrderedPerson.meta_.order_by == "first_name"

    def test_default_limit(self):
        assert Person.meta_.limit == 100

    def test_default_cache(self):
        assert Person.meta_.cache is None

    def test_cache_overrides_provider(self, test_domain):
        class CachedPerson(BaseProjection):
            person_id: str = Field(json_schema_extra={"identifier": True})
            first_name: str

        test_domain.register(CachedPerson, cache="default")
        assert CachedPerson.meta_.provider is None

    def test_error_without_provider_or_cache(self, test_domain):
        class NoProviderPerson(BaseProjection):
            person_id: str = Field(json_schema_extra={"identifier": True})
            first_name: str

        with pytest.raises(NotSupportedError):
            test_domain.register(NoProviderPerson, provider=None, cache=None)
