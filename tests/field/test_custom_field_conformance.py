"""The ``Custom`` field factory and its conformance harness.

Two layers here. The factory tests exercise ``Custom`` directly: the cast, the
guaranteed validation order, optional/required handling, and constraint
passthrough. The conformance tests run the worked example from the custom-fields
reference page against the reusable harness, so the documented recipe is
verified by execution, not by reading the page.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from decimal import Decimal

import pytest
from pydantic import AfterValidator, PlainSerializer, PlainValidator

from protean import value_object_from_entity
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import Custom, HasOne, String, ValueObject
from protean.integrations.pytest.custom_field_conformance import (
    run_custom_field_conformance,
)
from protean.utils.reflection import fields

# ---------------------------------------------------------------------------
# Load the worked example from docs_src (hyphenated path, so load by file).
# ---------------------------------------------------------------------------
_docs_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../docs_src"))
_spec = importlib.util.spec_from_file_location(
    "custom_fields_001",
    os.path.join(
        _docs_src, "guides", "domain-definition", "fields", "custom-fields", "001.py"
    ),
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

Color = _mod.Color
parse_color = _mod.parse_color
Palette = _mod.Palette
example_domain = _mod.domain


# ---------------------------------------------------------------------------
# A local Point type for the direct factory tests, so they do not lean on the
# docs example's Color.
# ---------------------------------------------------------------------------
class Point:
    """A 2D point parsed from an ``"x,y"`` string."""

    __slots__ = ("x", "y")

    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y

    def to_dict(self) -> str:
        return f"{self.x},{self.y}"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Point) and (other.x, other.y) == (self.x, self.y)

    def __repr__(self) -> str:
        return f"Point({self.x}, {self.y})"


def parse_point(value: object) -> Point:
    if isinstance(value, Point):
        return value
    if isinstance(value, str):
        x, _, y = value.partition(",")
        return Point(int(x), int(y))
    raise ValueError(f"cannot parse {value!r} as a Point")


def _point_field(**constraints):
    return Custom(
        Point,
        validators=[PlainValidator(parse_point)],
        serializers=[PlainSerializer(lambda p: p.to_dict(), return_type=str)],
        **constraints,
    )


# ===========================================================================
# Factory behavior
# ===========================================================================
class TestCustomFactory:
    def test_cast_parses_raw_input(self, test_domain):
        @test_domain.aggregate
        class Marker:
            at: Point = _point_field(required=True)

        test_domain.init(traverse=False)

        marker = Marker(at="3,4")
        assert marker.at == Point(3, 4)

    def test_existing_instance_passes_through(self, test_domain):
        @test_domain.aggregate
        class Marker:
            at: Point = _point_field(required=True)

        test_domain.init(traverse=False)

        marker = Marker(at=Point(1, 2))
        assert marker.at == Point(1, 2)

    def test_invalid_raw_value_is_rejected(self, test_domain):
        @test_domain.aggregate
        class Marker:
            at: Point = _point_field(required=True)

        test_domain.init(traverse=False)

        with pytest.raises(ValidationError):
            Marker(at="not-a-point")

    def test_optional_field_left_unset_is_none(self, test_domain):
        @test_domain.aggregate
        class Marker:
            at: Point = _point_field()

        test_domain.init(traverse=False)

        marker = Marker()
        assert marker.at is None

    def test_required_field_rejects_missing_value(self, test_domain):
        @test_domain.aggregate
        class Marker:
            at: Point = _point_field(required=True)

        test_domain.init(traverse=False)

        with pytest.raises(ValidationError):
            Marker()


class TestCustomValidationOrder:
    """Empty, then cast, then the supplied validators."""

    def test_empty_short_circuits_before_cast(self, test_domain):
        # An optional field left unset is None; the cast is never called, so it
        # cannot fail on the missing value.
        @test_domain.aggregate
        class Marker:
            at: Point = _point_field()

        test_domain.init(traverse=False)

        assert Marker().at is None

    def test_after_validator_runs_after_cast(self, test_domain):
        # The AfterValidator sees the parsed Point (the cast ran first) and can
        # reject it. This is the "validators" stage of the order.
        def reject_origin(point: Point) -> Point:
            if point == Point(0, 0):
                raise ValueError("the origin is not allowed")
            return point

        @test_domain.aggregate
        class Marker:
            at: Point = Custom(
                Point,
                validators=[PlainValidator(parse_point), AfterValidator(reject_origin)],
                required=True,
            )

        test_domain.init(traverse=False)

        # Cast succeeds, then the AfterValidator accepts a non-origin point.
        assert Marker(at="1,1").at == Point(1, 1)
        # Cast succeeds, then the AfterValidator rejects the origin.
        with pytest.raises(ValidationError):
            Marker(at="0,0")


class TestCustomValidationOrderProbes:
    """Prove the stage each callable runs at, not just the final value.

    Observing the final value cannot tell a correct order from a wrong one: a
    parser that happens to accept ``None`` produces the same ``None`` whether it
    ran or was skipped. These fields carry probes that fail if a stage runs on
    the wrong input.
    """

    def test_parser_is_never_called_for_a_missing_optional_value(self, test_domain):
        calls: list[object] = []

        def probing_parser(value: object) -> Point | None:
            calls.append(value)
            # A parser that tolerates None: the value alone cannot show whether
            # the empty check short-circuited, so the call log is the evidence.
            if value is None:
                return None
            return parse_point(value)

        @test_domain.aggregate
        class Marker:
            at: Point = Custom(Point, validators=[PlainValidator(probing_parser)])

        test_domain.init(traverse=False)

        assert Marker().at is None
        assert calls == [], f"the parser ran on a missing value: {calls!r}"

        Marker(at="3,4")
        assert calls == ["3,4"], f"the parser did not see the raw value: {calls!r}"

    def test_after_validator_receives_the_parsed_instance(self, test_domain):
        seen: list[object] = []

        def probing_validator(value: object) -> object:
            seen.append(value)
            return value

        @test_domain.aggregate
        class Marker:
            at: Point = Custom(
                Point,
                validators=[
                    PlainValidator(parse_point),
                    AfterValidator(probing_validator),
                ],
                required=True,
            )

        test_domain.init(traverse=False)

        Marker(at="3,4")
        assert seen == [Point(3, 4)], (
            f"the AfterValidator did not receive the parsed instance: {seen!r}"
        )
        assert isinstance(seen[0], Point)


class TestCustomReflection:
    def test_resolved_field_reports_required_and_field_kind(self, test_domain):
        @test_domain.aggregate
        class Marker:
            at: Point = _point_field(required=True)

        test_domain.init(traverse=False)

        resolved = fields(Marker)["at"]
        assert resolved.required is True
        assert resolved.field_kind == "custom"
        assert resolved.as_dict(Point(3, 4)) == "3,4"


class TestCustomConstraintPassthrough:
    """``**constraints`` reach the field, including the type-specific ones."""

    def test_max_length_applies_to_a_custom_over_str(self, test_domain):
        @test_domain.aggregate
        class Tag:
            code: str = Custom(
                str,
                validators=[PlainValidator(lambda v: str(v).upper())],
                max_length=3,
            )

        test_domain.init(traverse=False)

        assert fields(Tag)["code"].max_length == 3
        assert Tag(code="ab").code == "AB"
        with pytest.raises(ValidationError):
            Tag(code="abcd")

    def test_decimal_precision_and_scale_apply_to_a_custom_over_decimal(
        self, test_domain
    ):
        @test_domain.aggregate
        class Invoice:
            total: Decimal = Custom(
                Decimal,
                validators=[PlainValidator(lambda v: Decimal(str(v)))],
                precision=5,
                scale=2,
            )

        test_domain.init(traverse=False)

        assert Invoice(total="123.45").total == Decimal("123.45")
        with pytest.raises(ValidationError):
            Invoice(total="1234.567")

    def test_min_value_applies_to_a_custom_over_int(self, test_domain):
        @test_domain.aggregate
        class Batch:
            size: int = Custom(
                int, validators=[PlainValidator(lambda v: int(v))], min_value=1
            )

        test_domain.init(traverse=False)

        assert Batch(size="2").size == 2
        with pytest.raises(ValidationError):
            Batch(size="0")


class TestCustomRejectsChoices:
    """A choice set would replace the custom type with a Literal."""

    def test_choices_are_rejected_at_declaration(self):
        with pytest.raises(IncorrectUsageError, match="does not support choices"):
            Custom(
                Point,
                validators=[PlainValidator(parse_point)],
                choices=["0,0", "1,1"],
            )


class TestCustomDefault:
    def test_optional_field_falls_back_to_its_default(self, test_domain):
        @test_domain.aggregate
        class Marker:
            at: Point = _point_field(default=Point(0, 0))

        test_domain.init(traverse=False)

        assert Marker().at == Point(0, 0)
        assert Marker(at="3,4").at == Point(3, 4)

    def test_a_field_with_a_default_passes_conformance(self):
        # The harness must not insist that a missing value is None: a default is
        # part of the factory contract.
        field = _point_field(default=Point(0, 0))
        run_custom_field_conformance(
            field,
            valid_input="3,4",
            expected=Point(3, 4),
            invalid_input="garbage",
        )

    def test_a_field_with_a_callable_default_passes_conformance(self):
        field = _point_field(default=lambda: Point(1, 1))
        run_custom_field_conformance(
            field,
            valid_input="3,4",
            expected=Point(3, 4),
            invalid_input="garbage",
        )


class TestCustomAtTheAdapterBoundary:
    """What an adapter is handed for a custom field.

    Every adapter's ``from_entity`` goes through ``_entity_to_dict``. A driver or
    an index mapping only takes plain values, so the custom instance is
    serialized there, and reading it back parses it again.
    """

    def test_model_dict_holds_the_serialized_value(self, test_domain):
        @test_domain.aggregate
        class Marker:
            at: Point = _point_field(required=True)

        test_domain.init(traverse=False)

        with test_domain.domain_context():
            model_cls = test_domain.repository_for(Marker)._dao.database_model_cls
            record = model_cls.from_entity(Marker(at="3,4"))
            assert record["at"] == "3,4"

    def test_unique_lookup_uses_the_serialized_value(self, test_domain):
        @test_domain.aggregate
        class Marker:
            at: Point = _point_field(required=True, unique=True)

        test_domain.init(traverse=False)

        with test_domain.domain_context():
            repository = test_domain.repository_for(Marker)
            repository.add(Marker(at="3,4"))

            # The duplicate is found even though the filter carries a live Point
            # while the store holds the serialized "3,4".
            with pytest.raises(ValidationError):
                repository.add(Marker(at="3,4"))

    def test_filter_accepts_an_instance_and_a_raw_value(self, test_domain):
        @test_domain.aggregate
        class Marker:
            at: Point = _point_field(required=True)

        test_domain.init(traverse=False)

        with test_domain.domain_context():
            repository = test_domain.repository_for(Marker)
            repository.add(Marker(at="3,4"))

            dao = repository._dao
            assert dao.find_by(at=Point(3, 4)).at == Point(3, 4)
            assert dao.find_by(at="3,4").at == Point(3, 4)

    def test_custom_field_inside_a_value_object_is_serialized(self, test_domain):
        # An embedded value object is flattened into shadow attributes, and the
        # shadow attribute is what the adapter is handed. It carries the real
        # field, so the custom value is serialized there too.
        @test_domain.value_object
        class Location:
            at: Point = _point_field(required=True)

        @test_domain.aggregate
        class Marker:
            label: str = String(max_length=50)
            place = ValueObject(Location)

        test_domain.init(traverse=False)

        with test_domain.domain_context():
            repository = test_domain.repository_for(Marker)
            model_cls = repository._dao.database_model_cls
            marker = Marker(label="home", place=Location(at="3,4"))
            assert model_cls.from_entity(marker)["place_at"] == "3,4"

            repository.add(marker)
            assert repository.get(marker.id).place.at == Point(3, 4)


class TestCustomWithoutMetadata:
    """A Custom over a type Pydantic already understands needs no validators."""

    def test_bare_type_needs_no_validators(self, test_domain):
        @test_domain.aggregate
        class Holder:
            count: int = Custom(int, required=True)

        test_domain.init(traverse=False)

        assert Holder(count=5).count == 5


class TestCustomFieldProjectsToValueObject:
    """A custom field must survive projection into a value object.

    ``value_object_from_entity`` mirrors an entity's fields into a generated
    value object, and fact-event generation projects a child entity through the
    same path. Both read the bare Pydantic annotation, which for a custom field
    is the raw class with no schema, so the projected VO field needs the field's
    metadata re-attached or the VO fails at schema build.
    """

    def test_value_object_from_entity_projects_a_custom_field(self, test_domain):
        # Calling the Stable public API on an aggregate with a custom field must
        # build the VO and keep the field parseable.
        @test_domain.aggregate
        class Marker:
            at: Point = _point_field(required=True)

        test_domain.init(traverse=False)

        VO = value_object_from_entity(Marker)
        projected = VO(at="3,4")
        assert projected.at == Point(3, 4)

    def test_custom_field_on_child_entity_of_fact_event_aggregate(self, test_domain):
        # A custom field on a child entity of a fact_events aggregate round-trips
        # through save, reload, and event replay. ``domain.init()`` builds the
        # fact event, which projects the child entity into a VO; without the
        # metadata re-attach it crashes here at schema build.
        class Route(BaseAggregate):
            label: str = String(required=True)
            stop = HasOne("Waypoint")

        class Waypoint(BaseEntity):
            at: Point = _point_field(required=True)

        test_domain.register(Route, fact_events=True)
        test_domain.register(Waypoint, part_of=Route)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            route = Route(label="scenic", stop=Waypoint(at="3,4"))
            repository = test_domain.repository_for(Route)
            repository.add(route)

            reloaded = repository.get(route.id)
            assert reloaded.stop.at == Point(3, 4)

            fact_stream = f"{Route.meta_.stream_category}-fact-{route.id}"
            messages = test_domain.event_store.store.read(fact_stream)
            assert len(messages) > 0
            replayed = messages[-1].to_domain_object()
            assert replayed.stop.at == Point(3, 4)


# ===========================================================================
# Conformance suite: the worked example from the reference page
# ===========================================================================
class TestWorkedExampleConformance:
    def test_example_field_passes_conformance(self):
        # Rebuild the field exactly as the reference page states it, then run the
        # reusable harness. "Written from the page alone" is literally true: this
        # uses only Color, parse_color, Custom, and the two Pydantic objects.
        field = Custom(
            Color,
            validators=[PlainValidator(parse_color)],
            serializers=[PlainSerializer(lambda c: c.hex, return_type=str)],
            required=True,
        )
        run_custom_field_conformance(
            field,
            valid_input="#3366ff",
            expected=Color("#3366FF"),
            invalid_input="not-a-color",
        )

    def test_optional_example_field_passes_conformance(self):
        field = Custom(
            Color,
            validators=[PlainValidator(parse_color)],
            serializers=[PlainSerializer(lambda c: c.hex, return_type=str)],
        )
        run_custom_field_conformance(
            field,
            valid_input="#00ff00",
            expected=Color("#00FF00"),
            invalid_input="nope",
        )

    def test_docs_example_palette_round_trips(self):
        # Exercise the actual aggregate declared in the docs example, so the page
        # snippet is proven to run end to end, not just a re-declared copy.
        example_domain.init(traverse=False)
        with example_domain.domain_context():
            palette = Palette(name="sky", brand="#3366ff")
            assert palette.brand == Color("#3366FF")

            repository = example_domain.repository_for(Palette)
            repository.add(palette)

            reloaded = repository.get(palette.id)
            assert reloaded.brand == Color("#3366FF")

            fact_stream = f"{Palette.meta_.stream_category}-fact-{palette.id}"
            messages = example_domain.event_store.store.read(fact_stream)
            assert len(messages) > 0
            replayed = messages[-1].to_domain_object()
            assert replayed.brand == Color("#3366FF")


class TestConformanceHarnessGuards:
    """The harness must fail loudly when a field breaks the contract."""

    def test_rejects_a_non_fieldspec(self):
        with pytest.raises(TypeError):
            run_custom_field_conformance(
                object(),  # type: ignore[arg-type]
                valid_input="x",
                expected="x",
                invalid_input="y",
            )

    def test_rejects_a_built_in_field(self):
        # A built-in factory returns a FieldSpec too, so the isinstance check
        # alone would let a String() through and report it as custom-field
        # conformance.
        with pytest.raises(TypeError, match="built by Custom"):
            run_custom_field_conformance(
                String(max_length=10),
                valid_input="x",
                expected="x",
                invalid_input=1,
            )

    def test_flags_a_parser_that_accepts_everything(self):
        # A parser that returns a fixed value for any input never rejects, so the
        # harness must catch that the invalid value was not rejected.
        field = Custom(
            Point,
            validators=[PlainValidator(lambda _: Point(9, 9))],
            serializers=[PlainSerializer(lambda p: p.to_dict(), return_type=str)],
            required=True,
        )
        with pytest.raises(AssertionError):
            run_custom_field_conformance(
                field,
                valid_input="anything",
                expected=Point(9, 9),
                invalid_input="garbage",
            )

    def test_flags_a_required_field_that_accepts_a_missing_value(self):
        # required=True with a default makes the field effectively optional (the
        # default is honored), so a required field accepts a missing value. The
        # harness must catch that mismatch.
        with pytest.warns(UserWarning, match="required=True"):
            field = Custom(
                Point,
                validators=[PlainValidator(parse_point)],
                serializers=[PlainSerializer(lambda p: p.to_dict(), return_type=str)],
                required=True,
                default=Point(0, 0),
            )
        with pytest.raises(AssertionError):
            run_custom_field_conformance(
                field,
                valid_input="1,1",
                expected=Point(1, 1),
                invalid_input="garbage",
            )
