"""Tests for the three supported field definition styles.

Protean supports three ways to declare fields on domain elements:

1. **Assignment style** (recommended):
       ``name = String(max_length=50, required=True)``
   A FieldSpec is placed in the class namespace (``vars(cls)``).

2. **Annotation style** with FieldSpec:
       ``name: String(max_length=50, required=True)``
   A FieldSpec is placed directly in ``__annotations__``.
   NOTE: This style is **incompatible** with ``from __future__ import annotations``
   because deferred annotations turn the FieldSpec into a string.

3. **Plain annotation** (raw Pydantic):
       ``name: str``
   A bare Python type goes straight to Pydantic; no Protean constraints
   are applied (no max_length, min_value, choices, etc.).

All three styles must produce valid domain objects with correct reflection
metadata (``declared_fields``, ``fields``, ``attributes``).
"""

import enum

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.value_object import BaseValueObject
from protean.fields.resolved import ResolvedField
from protean.exceptions import ValidationError
from protean.fields import (
    Boolean,
    Float,
    Identifier,
    Integer,
    String,
    ValueObject,
)
from protean.utils.reflection import declared_fields


# ---------------------------------------------------------------------------
# Status choices used by several test elements
# ---------------------------------------------------------------------------
class Status(enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


# =========================================================================
# Aggregate definitions — one per style
# =========================================================================
class AggAssign(BaseAggregate):
    name = String(max_length=50, required=True)
    age = Integer(default=21)
    active = Boolean(default=True)


class AggAnnot(BaseAggregate):
    name: String(max_length=50, required=True)
    age: Integer(default=21)
    active: Boolean(default=True)


class AggPlain(BaseAggregate):
    name: str
    age: int = 21
    active: bool = True


# =========================================================================
# Entity definitions — one per style
# =========================================================================
class EntAssign(BaseEntity):
    label = String(max_length=30, required=True)
    weight = Float(default=0.0)


class EntAnnot(BaseEntity):
    label: String(max_length=30, required=True)
    weight: Float(default=0.0)


class EntPlain(BaseEntity):
    label: str
    weight: float = 0.0


# =========================================================================
# ValueObject definitions — one per style
# =========================================================================
class VOAssign(BaseValueObject):
    street = String(max_length=100, required=True)
    zip_code = String(max_length=10)


class VOAnnot(BaseValueObject):
    street: String(max_length=100, required=True)
    zip_code: String(max_length=10)


class VOPlain(BaseValueObject):
    street: str
    zip_code: str | None = None


# =========================================================================
# Command definitions — one per style
# =========================================================================
class CmdAssign(BaseCommand):
    user_id = Identifier(identifier=True)
    email = String(required=True)


class CmdAnnot(BaseCommand):
    user_id: Identifier(identifier=True)
    email: String(required=True)


class CmdPlain(BaseCommand):
    user_id: str
    email: str


# =========================================================================
# Command definitions with ValueObject — assignment and plain styles
# =========================================================================
class CmdVOAssign(BaseCommand):
    user_id = Identifier(identifier=True)
    email = String(required=True)
    address = ValueObject(VOAssign)


class CmdVOPlain(BaseCommand):
    user_id: Identifier(identifier=True)
    email: String(required=True)
    address: VOPlain | None = None


# =========================================================================
# Event definitions — one per style
# =========================================================================
class EvtAssign(BaseEvent):
    user_id = Identifier(identifier=True)
    email = String(required=True)


class EvtAnnot(BaseEvent):
    user_id: Identifier(identifier=True)
    email: String(required=True)


class EvtPlain(BaseEvent):
    user_id: str
    email: str


# =========================================================================
# Event definitions with ValueObject — assignment and plain styles
# =========================================================================
class EvtVOAssign(BaseEvent):
    user_id = Identifier(identifier=True)
    email = String(required=True)
    address = ValueObject(VOAssign)


class EvtVOPlain(BaseEvent):
    user_id: Identifier(identifier=True)
    email: String(required=True)
    address: VOPlain | None = None


# =========================================================================
# Projection definitions — one per style
# =========================================================================
class ProjAssign(BaseProjection):
    proj_id = Identifier(identifier=True)
    title = String(max_length=100, required=True)


class ProjAnnot(BaseProjection):
    proj_id: Identifier(identifier=True)
    title: String(max_length=100, required=True)


class ProjPlain(BaseProjection):
    proj_id: str = Field(json_schema_extra={"identifier": True})
    title: str


# =========================================================================
# Fixture: Register all elements
# =========================================================================
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    # Aggregates
    test_domain.register(AggAssign)
    test_domain.register(AggAnnot)
    test_domain.register(AggPlain)

    # Entities
    test_domain.register(EntAssign, part_of=AggAssign)
    test_domain.register(EntAnnot, part_of=AggAnnot)
    test_domain.register(EntPlain, part_of=AggPlain)

    # ValueObjects
    test_domain.register(VOAssign)
    test_domain.register(VOAnnot)
    test_domain.register(VOPlain)

    # Commands
    test_domain.register(CmdAssign, part_of=AggAssign)
    test_domain.register(CmdAnnot, part_of=AggAnnot)
    test_domain.register(CmdPlain, part_of=AggPlain)
    test_domain.register(CmdVOAssign, part_of=AggAssign)
    test_domain.register(CmdVOPlain, part_of=AggPlain)

    # Events
    test_domain.register(EvtAssign, part_of=AggAssign)
    test_domain.register(EvtAnnot, part_of=AggAnnot)
    test_domain.register(EvtPlain, part_of=AggPlain)
    test_domain.register(EvtVOAssign, part_of=AggAssign)
    test_domain.register(EvtVOPlain, part_of=AggPlain)

    # Projections
    test_domain.register(ProjAssign)
    test_domain.register(ProjAnnot)
    test_domain.register(ProjPlain)

    test_domain.init(traverse=False)


# =========================================================================
# AGGREGATES
# =========================================================================
class TestAggregateFieldStyles:
    """All three styles produce working aggregates with correct metadata."""

    @pytest.mark.parametrize(
        "cls",
        [AggAssign, AggAnnot, AggPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_basic_instantiation(self, cls):
        obj = cls(name="Alice", age=30, active=False)
        assert obj.name == "Alice"
        assert obj.age == 30
        assert obj.active is False

    @pytest.mark.parametrize(
        "cls",
        [AggAssign, AggAnnot, AggPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_default_values(self, cls):
        obj = cls(name="Bob")
        assert obj.age == 21
        assert obj.active is True

    @pytest.mark.parametrize(
        "cls",
        [AggAssign, AggAnnot, AggPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_declared_fields_present(self, cls):
        df = declared_fields(cls)
        assert "name" in df
        assert "age" in df
        assert "active" in df

    @pytest.mark.parametrize(
        "cls",
        [AggAssign, AggAnnot, AggPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_declared_fields_are_field_shims(self, cls):
        df = declared_fields(cls)
        for name in ("name", "age", "active"):
            assert isinstance(df[name], ResolvedField), (
                f"{name} should be a ResolvedField"
            )

    @pytest.mark.parametrize(
        "cls",
        [AggAssign, AggAnnot, AggPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_auto_id_injection(self, cls):
        obj = cls(name="Carol")
        assert obj.id is not None
        assert "id" in declared_fields(cls)

    @pytest.mark.parametrize(
        "cls",
        [AggAssign, AggAnnot, AggPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_to_dict(self, cls):
        obj = cls(name="Dave", age=25)
        d = obj.to_dict()
        assert d["name"] == "Dave"
        assert d["age"] == 25
        assert "id" in d

    @pytest.mark.parametrize(
        "cls",
        [AggAssign, AggAnnot],
        ids=["assign", "annot"],
    )
    def test_max_length_constraint(self, cls):
        """Assignment and annotation styles enforce max_length."""
        with pytest.raises(ValidationError):
            cls(name="X" * 51)  # max_length=50

    def test_plain_style_has_no_max_length(self):
        """Plain annotation style has no Protean constraints."""
        obj = AggPlain(name="X" * 200)
        assert len(obj.name) == 200

    @pytest.mark.parametrize(
        "cls",
        [AggAssign, AggAnnot, AggPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_type_validation(self, cls):
        """All styles reject wrong types."""
        with pytest.raises(ValidationError):
            cls(name="Alice", age="not_a_number")


# =========================================================================
# ENTITIES
# =========================================================================
class TestEntityFieldStyles:
    @pytest.mark.parametrize(
        "cls",
        [EntAssign, EntAnnot, EntPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_basic_instantiation(self, cls):
        obj = cls(label="Widget", weight=1.5)
        assert obj.label == "Widget"
        assert obj.weight == 1.5

    @pytest.mark.parametrize(
        "cls",
        [EntAssign, EntAnnot, EntPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_default_values(self, cls):
        obj = cls(label="Gadget")
        assert obj.weight == 0.0

    @pytest.mark.parametrize(
        "cls",
        [EntAssign, EntAnnot, EntPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_declared_fields(self, cls):
        df = declared_fields(cls)
        assert "label" in df
        assert "weight" in df

    @pytest.mark.parametrize(
        "cls",
        [EntAssign, EntAnnot],
        ids=["assign", "annot"],
    )
    def test_max_length_constraint(self, cls):
        with pytest.raises(ValidationError):
            cls(label="X" * 31)  # max_length=30


# =========================================================================
# VALUE OBJECTS
# =========================================================================
class TestValueObjectFieldStyles:
    @pytest.mark.parametrize(
        "cls",
        [VOAssign, VOAnnot, VOPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_basic_instantiation(self, cls):
        obj = cls(street="123 Main St", zip_code="12345")
        assert obj.street == "123 Main St"
        assert obj.zip_code == "12345"

    @pytest.mark.parametrize(
        "cls",
        [VOAssign, VOAnnot, VOPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_declared_fields(self, cls):
        df = declared_fields(cls)
        assert "street" in df
        assert "zip_code" in df

    @pytest.mark.parametrize(
        "cls",
        [VOAssign, VOAnnot],
        ids=["assign", "annot"],
    )
    def test_required_field_enforcement(self, cls):
        with pytest.raises(ValidationError):
            cls(zip_code="12345")  # street is required


# =========================================================================
# COMMANDS
# =========================================================================
class TestCommandFieldStyles:
    @pytest.mark.parametrize(
        "cls",
        [CmdAssign, CmdAnnot, CmdPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_basic_instantiation(self, cls):
        obj = cls(user_id="u1", email="a@b.com")
        assert obj.email == "a@b.com"

    @pytest.mark.parametrize(
        "cls",
        [CmdAssign, CmdAnnot, CmdPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_declared_fields(self, cls):
        df = declared_fields(cls)
        assert "user_id" in df
        assert "email" in df


# =========================================================================
# EVENTS
# =========================================================================
class TestEventFieldStyles:
    @pytest.mark.parametrize(
        "cls",
        [EvtAssign, EvtAnnot, EvtPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_basic_instantiation(self, cls):
        obj = cls(user_id="u1", email="a@b.com")
        assert obj.email == "a@b.com"

    @pytest.mark.parametrize(
        "cls",
        [EvtAssign, EvtAnnot, EvtPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_declared_fields(self, cls):
        df = declared_fields(cls)
        assert "user_id" in df
        assert "email" in df


# =========================================================================
# VALUE OBJECTS IN COMMANDS AND EVENTS
# =========================================================================
class TestValueObjectInCommandsAndEvents:
    """ValueObject() descriptors work in commands/events (converted to annotations)."""

    @pytest.mark.parametrize(
        "cls,vo_cls",
        [(CmdVOAssign, VOAssign), (CmdVOPlain, VOPlain)],
        ids=["cmd_vo_assign", "cmd_vo_plain"],
    )
    def test_command_with_vo_instantiation(self, cls, vo_cls):
        vo = vo_cls(street="123 Main St", zip_code="12345")
        obj = cls(user_id="u1", email="a@b.com", address=vo)
        assert obj.address.street == "123 Main St"

    @pytest.mark.parametrize(
        "cls,vo_cls",
        [(EvtVOAssign, VOAssign), (EvtVOPlain, VOPlain)],
        ids=["evt_vo_assign", "evt_vo_plain"],
    )
    def test_event_with_vo_instantiation(self, cls, vo_cls):
        vo = vo_cls(street="456 Elm St", zip_code="67890")
        obj = cls(user_id="u1", email="a@b.com", address=vo)
        assert obj.address.street == "456 Elm St"

    @pytest.mark.parametrize(
        "cls",
        [CmdVOAssign, CmdVOPlain],
        ids=["cmd_vo_assign", "cmd_vo_plain"],
    )
    def test_command_vo_optional_defaults_to_none(self, cls):
        obj = cls(user_id="u1", email="a@b.com")
        assert obj.address is None

    @pytest.mark.parametrize(
        "cls",
        [CmdVOAssign, CmdVOPlain],
        ids=["cmd_vo_assign", "cmd_vo_plain"],
    )
    def test_command_vo_declared_fields(self, cls):
        df = declared_fields(cls)
        assert "address" in df
        assert "user_id" in df
        assert "email" in df
        # No shadow fields
        assert "address_street" not in df
        assert "address_zip_code" not in df

    @pytest.mark.parametrize(
        "cls",
        [CmdVOAssign, CmdVOPlain],
        ids=["cmd_vo_assign", "cmd_vo_plain"],
    )
    def test_command_vo_fields_are_resolved_fields(self, cls):
        df = declared_fields(cls)
        for name in ("user_id", "email", "address"):
            assert isinstance(df[name], ResolvedField), (
                f"{name} should be a ResolvedField"
            )


# =========================================================================
# PROJECTIONS
# =========================================================================
class TestProjectionFieldStyles:
    @pytest.mark.parametrize(
        "cls",
        [ProjAssign, ProjAnnot, ProjPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_basic_instantiation(self, cls):
        obj = cls(proj_id="p1", title="Dashboard")
        assert obj.title == "Dashboard"

    @pytest.mark.parametrize(
        "cls",
        [ProjAssign, ProjAnnot, ProjPlain],
        ids=["assign", "annot", "plain"],
    )
    def test_declared_fields(self, cls):
        df = declared_fields(cls)
        assert "proj_id" in df
        assert "title" in df

    @pytest.mark.parametrize(
        "cls",
        [ProjAssign, ProjAnnot],
        ids=["assign", "annot"],
    )
    def test_max_length_constraint(self, cls):
        with pytest.raises(ValidationError):
            cls(proj_id="p1", title="X" * 101)  # max_length=100


# =========================================================================
# CROSS-STYLE EQUIVALENCE
# =========================================================================
class TestCrossStyleEquivalence:
    """Verify that assignment and annotation styles produce equivalent metadata."""

    def test_aggregate_fields_match_between_assign_and_annot(self):
        df_assign = declared_fields(AggAssign)
        df_annot = declared_fields(AggAnnot)

        # Both should have the same field names (excluding id which is auto-generated)
        assign_names = {n for n in df_assign if n != "id"}
        annot_names = {n for n in df_annot if n != "id"}
        assert assign_names == annot_names

    def test_aggregate_required_flags_match(self):
        df_assign = declared_fields(AggAssign)
        df_annot = declared_fields(AggAnnot)

        assert df_assign["name"].required == df_annot["name"].required
        assert df_assign["age"].required == df_annot["age"].required

    def test_entity_fields_match_between_assign_and_annot(self):
        df_assign = declared_fields(EntAssign)
        df_annot = declared_fields(EntAnnot)

        # Exclude auto-generated reference fields (e.g. agg_assign, agg_annot)
        # and auto-id — they differ due to parent aggregate names
        own_fields = {"label", "weight"}
        assert own_fields.issubset(set(df_assign.keys()))
        assert own_fields.issubset(set(df_annot.keys()))

    def test_vo_fields_match_between_assign_and_annot(self):
        df_assign = declared_fields(VOAssign)
        df_annot = declared_fields(VOAnnot)
        assert set(df_assign.keys()) == set(df_annot.keys())

    def test_command_fields_match_between_assign_and_annot(self):
        df_assign = declared_fields(CmdAssign)
        df_annot = declared_fields(CmdAnnot)
        assert set(df_assign.keys()) == set(df_annot.keys())

    def test_event_fields_match_between_assign_and_annot(self):
        df_assign = declared_fields(EvtAssign)
        df_annot = declared_fields(EvtAnnot)
        assert set(df_assign.keys()) == set(df_annot.keys())

    def test_projection_fields_match_between_assign_and_annot(self):
        df_assign = declared_fields(ProjAssign)
        df_annot = declared_fields(ProjAnnot)
        assert set(df_assign.keys()) == set(df_annot.keys())


# =========================================================================
# IDENTIFIER FIELDS across styles
# =========================================================================
class TestIdentifierFieldStyles:
    def test_assign_identifier_on_aggregate(self):
        class MyAgg(BaseAggregate):
            my_id = Identifier(identifier=True)
            name = String()

        df = declared_fields(MyAgg)
        assert df["my_id"].identifier is True
        assert "id" not in df  # auto-id should NOT be injected

    def test_annot_identifier_on_aggregate(self):
        class MyAgg(BaseAggregate):
            my_id: Identifier(identifier=True)
            name: String()

        df = declared_fields(MyAgg)
        assert df["my_id"].identifier is True
        assert "id" not in df


# =========================================================================
# CONSTRAINT ENFORCEMENT for FieldSpec styles
# =========================================================================
class TestConstraintEnforcement:
    """Verify that Protean field constraints are enforced for both FieldSpec styles."""

    def test_integer_min_value_assign(self):
        class VO(BaseValueObject):
            count = Integer(min_value=0)

        with pytest.raises(ValidationError):
            VO(count=-1)

    def test_integer_min_value_annot(self):
        class VO(BaseValueObject):
            count: Integer(min_value=0)

        with pytest.raises(ValidationError):
            VO(count=-1)

    def test_integer_max_value_assign(self):
        class VO(BaseValueObject):
            count = Integer(max_value=100)

        with pytest.raises(ValidationError):
            VO(count=101)

    def test_integer_max_value_annot(self):
        class VO(BaseValueObject):
            count: Integer(max_value=100)

        with pytest.raises(ValidationError):
            VO(count=101)

    def test_float_constraints_assign(self):
        class VO(BaseValueObject):
            score = Float(min_value=0.0, max_value=10.0)

        with pytest.raises(ValidationError):
            VO(score=11.0)

    def test_float_constraints_annot(self):
        class VO(BaseValueObject):
            score: Float(min_value=0.0, max_value=10.0)

        with pytest.raises(ValidationError):
            VO(score=11.0)

    def test_string_min_length_assign(self):
        class VO(BaseValueObject):
            code = String(min_length=3, max_length=10)

        with pytest.raises(ValidationError):
            VO(code="AB")

    def test_string_min_length_annot(self):
        class VO(BaseValueObject):
            code: String(min_length=3, max_length=10)

        with pytest.raises(ValidationError):
            VO(code="AB")

    def test_choices_assign(self):
        class VO(BaseValueObject):
            status = String(max_length=10, choices=Status)

        vo = VO(status="ACTIVE")
        assert vo.status == "ACTIVE"
        with pytest.raises(ValidationError):
            VO(status="UNKNOWN")

    def test_choices_annot(self):
        class VO(BaseValueObject):
            status: String(max_length=10, choices=Status)

        vo = VO(status="ACTIVE")
        assert vo.status == "ACTIVE"
        with pytest.raises(ValidationError):
            VO(status="UNKNOWN")


# =========================================================================
# MIXED STYLES within a single class
# =========================================================================
class TestMixedStyles:
    """Verify that assignment-style and plain annotation can coexist."""

    def test_mixed_assign_and_plain_on_aggregate(self):
        class MixedAgg(BaseAggregate):
            name = String(max_length=50, required=True)
            description: str | None = None
            count = Integer(default=0)

        obj = MixedAgg(name="Test", description="A description")
        assert obj.name == "Test"
        assert obj.description == "A description"
        assert obj.count == 0

        df = declared_fields(MixedAgg)
        assert "name" in df
        assert "description" in df
        assert "count" in df

    def test_mixed_assign_and_plain_on_value_object(self):
        class MixedVO(BaseValueObject):
            label = String(max_length=30, required=True)
            note: str | None = None

        vo = MixedVO(label="Hello", note="World")
        assert vo.label == "Hello"
        assert vo.note == "World"

    def test_mixed_constraint_enforcement(self):
        """FieldSpec fields enforce constraints; plain fields do not."""

        class MixedAgg(BaseAggregate):
            constrained = String(max_length=5, required=True)
            unconstrained: str | None = None

        # Constrained field rejects long strings
        with pytest.raises(ValidationError):
            MixedAgg(constrained="too long string")

        # Unconstrained field accepts anything
        obj = MixedAgg(constrained="ok", unconstrained="X" * 1000)
        assert len(obj.unconstrained) == 1000


# =========================================================================
# DEFERRED ANNOTATIONS (from __future__ import annotations)
# =========================================================================
class TestDeferredAnnotations:
    """Annotation-style FieldSpec is incompatible with deferred annotations.

    Style 1 (assignment) and Style 3 (plain) work correctly with
    ``from __future__ import annotations``, but Style 2 (annotation with
    FieldSpec) does NOT because deferred annotations convert the FieldSpec
    expression into a string that is never evaluated.
    """

    def test_assignment_style_works_with_deferred_annotations(self):
        """Assignment-style FieldSpecs live in vars(cls), not annotations."""
        import sys
        import types

        code = (
            "from __future__ import annotations\n"
            "from protean.core.value_object import BaseValueObject\n"
            "from protean.fields import String\n"
            "\n"
            "class DeferredVO(BaseValueObject):\n"
            "    name = String(max_length=50, required=True)\n"
        )
        mod = types.ModuleType("_test_deferred_assign")
        sys.modules["_test_deferred_assign"] = mod
        try:
            exec(compile(code, "<test>", "exec"), mod.__dict__)
            vo = mod.DeferredVO(name="Hello")
            assert vo.name == "Hello"
            df = declared_fields(mod.DeferredVO)
            assert "name" in df
        finally:
            del sys.modules["_test_deferred_assign"]

    def test_plain_style_works_with_deferred_annotations(self):
        """Plain type annotations are handled natively by Pydantic."""
        import sys
        import types

        code = (
            "from __future__ import annotations\n"
            "from protean.core.value_object import BaseValueObject\n"
            "\n"
            "class DeferredVO(BaseValueObject):\n"
            "    name: str\n"
        )
        mod = types.ModuleType("_test_deferred_plain")
        sys.modules["_test_deferred_plain"] = mod
        try:
            exec(compile(code, "<test>", "exec"), mod.__dict__)
            vo = mod.DeferredVO(name="Hello")
            assert vo.name == "Hello"
            df = declared_fields(mod.DeferredVO)
            assert "name" in df
        finally:
            del sys.modules["_test_deferred_plain"]

    def test_annotation_style_fails_with_deferred_annotations(self):
        """Annotation-style FieldSpec becomes a string with deferred annotations."""
        import sys
        import types

        code = (
            "from __future__ import annotations\n"
            "from protean.core.value_object import BaseValueObject\n"
            "from protean.fields import String\n"
            "\n"
            "class DeferredVO(BaseValueObject):\n"
            "    name: String(max_length=50, required=True)\n"
        )
        mod = types.ModuleType("_test_deferred_annot")
        sys.modules["_test_deferred_annot"] = mod
        try:
            with pytest.raises(Exception):
                exec(compile(code, "<test>", "exec"), mod.__dict__)
        finally:
            sys.modules.pop("_test_deferred_annot", None)


# =========================================================================
# ANNOTATION-STYLE IDENTIFIER
# =========================================================================
class TestAnnotationIdentifier:
    """Comprehensive tests for annotation-style identifier=True across all
    domain element types.  Covers the scenarios described in the bug report:
    projections requiring at least one identifier, aggregates with
    auto_add_id_field=False, and FieldSpec metadata preservation.
    """

    # ----- Aggregates -----

    def test_annot_identifier_suppresses_auto_id(self):
        """Annotation-style identifier=True must suppress auto-id injection."""

        class Agg(BaseAggregate):
            custom_id: Identifier(identifier=True)
            name: String(max_length=50)

        df = declared_fields(Agg)
        assert df["custom_id"].identifier is True
        assert "id" not in df

    def test_annot_identifier_with_auto_add_id_field_false(self):
        """auto_add_id_field=False combined with annotation-style identifier."""

        class Agg(BaseAggregate):
            class Meta:
                auto_add_id_field = False

            order_id: Identifier(identifier=True)
            total: Float(default=0.0)

        df = declared_fields(Agg)
        assert df["order_id"].identifier is True
        assert "id" not in df

    def test_annot_identifier_instantiation(self):
        """Annotation-style identifier must be usable at runtime."""

        class Agg(BaseAggregate):
            order_id: Identifier(identifier=True)
            total: Float(default=0.0)

        obj = Agg(order_id="ORD-001", total=99.99)
        assert obj.order_id == "ORD-001"
        assert obj.total == 99.99

    def test_annot_identifier_auto_generated(self):
        """Identifier field without explicit value gets auto-generated."""

        class Agg(BaseAggregate):
            order_id: Identifier(identifier=True)
            name: String(max_length=50)

        obj = Agg(name="Test")
        assert obj.order_id is not None

    def test_annot_identifier_in_to_dict(self):
        """Annotation-style identifier must appear in to_dict."""

        class Agg(BaseAggregate):
            order_id: Identifier(identifier=True)
            name: String(max_length=50)

        obj = Agg(order_id="ORD-001", name="Test")
        d = obj.to_dict()
        assert d["order_id"] == "ORD-001"
        assert "id" not in d

    # ----- Projections -----

    def test_annot_identifier_on_projection(self, test_domain):
        """Annotation-style identifier on a projection must satisfy the
        'at least one identifier' requirement during registration."""

        class OrderView(BaseProjection):
            order_id: Identifier(identifier=True)
            customer_name: String(max_length=100)

        # Registration should succeed (not raise IncorrectUsageError)
        test_domain.register(OrderView)
        test_domain.init(traverse=False)

        df = declared_fields(OrderView)
        assert df["order_id"].identifier is True

    def test_annot_identifier_projection_instantiation(self, test_domain):
        """Projection with annotation-style identifier can be instantiated."""

        class DashboardView(BaseProjection):
            view_id: Identifier(identifier=True)
            title: String(max_length=100)
            count: Integer(default=0)

        test_domain.register(DashboardView)
        test_domain.init(traverse=False)

        obj = DashboardView(view_id="v1", title="Dashboard", count=42)
        assert obj.view_id == "v1"
        assert obj.title == "Dashboard"
        assert obj.count == 42

    def test_assign_vs_annot_identifier_projection_equivalence(self, test_domain):
        """Assignment and annotation styles must produce equivalent projections."""

        class ProjA(BaseProjection):
            pid = Identifier(identifier=True)
            label = String(max_length=50)

        class ProjB(BaseProjection):
            pid: Identifier(identifier=True)
            label: String(max_length=50)

        test_domain.register(ProjA)
        test_domain.register(ProjB)
        test_domain.init(traverse=False)

        df_a = declared_fields(ProjA)
        df_b = declared_fields(ProjB)
        assert set(df_a.keys()) == set(df_b.keys())
        assert df_a["pid"].identifier == df_b["pid"].identifier

    # ----- Entities -----

    def test_annot_identifier_on_entity(self):
        """Annotation-style identifier on entities suppresses auto-id."""

        class Ent(BaseEntity):
            ent_id: Identifier(identifier=True)
            label: String(max_length=30)

        df = declared_fields(Ent)
        assert df["ent_id"].identifier is True
        assert "id" not in df

    def test_annot_identifier_entity_instantiation(self):
        """Entity with annotation-style identifier can be instantiated."""

        class Ent(BaseEntity):
            ent_id: Identifier(identifier=True)
            label: String(max_length=30)

        obj = Ent(ent_id="e1", label="Widget")
        assert obj.ent_id == "e1"
        assert obj.label == "Widget"

    # ----- Commands -----

    def test_annot_identifier_on_command(self):
        """Command with annotation-style identifier has correct metadata."""

        class Cmd(BaseCommand):
            cmd_id: Identifier(identifier=True)
            body: String(max_length=200)

        df = declared_fields(Cmd)
        assert df["cmd_id"].identifier is True

    # ----- Events -----

    def test_annot_identifier_on_event(self):
        """Event with annotation-style identifier has correct metadata."""

        class Evt(BaseEvent):
            evt_id: Identifier(identifier=True)
            detail: String(max_length=200)

        df = declared_fields(Evt)
        assert df["evt_id"].identifier is True

    # ----- FieldSpec metadata preservation -----

    def test_annot_fieldspec_metadata_preserved(self):
        """__protean_field_meta__ must be populated for annotation-style fields."""
        from protean.fields.spec import FieldSpec

        class Agg(BaseAggregate):
            custom_id: Identifier(identifier=True)
            name: String(max_length=50, required=True)

        meta = getattr(Agg, "__protean_field_meta__", {})
        assert "custom_id" in meta
        assert "name" in meta
        assert isinstance(meta["custom_id"], FieldSpec)
        assert isinstance(meta["name"], FieldSpec)
        assert meta["custom_id"].identifier is True
        assert meta["name"].required is True

    def test_annot_fieldspec_metadata_matches_assignment_style(self):
        """Annotation and assignment styles produce equivalent __protean_field_meta__."""
        from protean.fields.spec import FieldSpec

        class AggA(BaseAggregate):
            my_id = Identifier(identifier=True)
            name = String(max_length=50, required=True)

        class AggB(BaseAggregate):
            my_id: Identifier(identifier=True)
            name: String(max_length=50, required=True)

        meta_a = getattr(AggA, "__protean_field_meta__", {})
        meta_b = getattr(AggB, "__protean_field_meta__", {})

        # Same field names tracked
        assert set(meta_a.keys()) == set(meta_b.keys())

        # Same metadata
        for name in meta_a:
            assert isinstance(meta_a[name], FieldSpec)
            assert isinstance(meta_b[name], FieldSpec)
            assert meta_a[name].identifier == meta_b[name].identifier
            assert meta_a[name].required == meta_b[name].required

    # ----- Multiple fields with annotation style -----

    def test_annot_multiple_fields_all_resolved(self):
        """Multiple annotation-style fields are all correctly resolved."""

        class Agg(BaseAggregate):
            agg_id: Identifier(identifier=True)
            name: String(max_length=100, required=True)
            score: Float(min_value=0.0, max_value=100.0)
            count: Integer(default=0)
            active: Boolean(default=True)

        df = declared_fields(Agg)
        assert df["agg_id"].identifier is True
        assert "id" not in df

        obj = Agg(agg_id="a1", name="Test", score=85.5)
        assert obj.agg_id == "a1"
        assert obj.name == "Test"
        assert obj.score == 85.5
        assert obj.count == 0
        assert obj.active is True

    # ----- Mixed annotation + assignment with identifier -----

    def test_mixed_annot_identifier_with_assignment_fields(self):
        """Annotation-style identifier mixed with assignment-style regular fields."""

        class Agg(BaseAggregate):
            agg_id: Identifier(identifier=True)
            name = String(max_length=50, required=True)
            count = Integer(default=0)

        df = declared_fields(Agg)
        assert df["agg_id"].identifier is True
        assert "id" not in df
        assert "name" in df
        assert "count" in df

    def test_assignment_identifier_with_annot_fields(self):
        """Assignment-style identifier mixed with annotation-style regular fields."""

        class Agg(BaseAggregate):
            agg_id = Identifier(identifier=True)
            name: String(max_length=50, required=True)
            count: Integer(default=0)

        df = declared_fields(Agg)
        assert df["agg_id"].identifier is True
        assert "id" not in df
        assert "name" in df
        assert "count" in df
