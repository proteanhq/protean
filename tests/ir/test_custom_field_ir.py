"""IR emission for a ``Custom`` field.

A ``Custom`` field carries ``field_kind="custom"``, which the builder copies
straight into the IR as ``"kind": "custom"``. The IR schema discriminates fields
on ``kind``, so without a matching definition the whole IR document fails schema
validation the moment a domain declares one custom field.
"""

import json

import pytest
from jsonschema import ValidationError, validate
from pydantic import PlainSerializer, PlainValidator

from protean.domain import Domain
from protean.fields import Custom, String
from protean.ir import load_schema
from protean.ir.builder import IRBuilder


class Color:
    """An RGB color stored as a ``#RRGGBB`` hex string."""

    __slots__ = ("hex",)

    def __init__(self, value: str) -> None:
        self.hex = str(value).upper()

    def to_dict(self) -> str:
        return self.hex

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Color) and other.hex == self.hex


def parse_color(value: object) -> Color:
    if isinstance(value, Color):
        return value
    return Color(value)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def ir():
    domain = Domain(name="Custom Field IR")

    @domain.aggregate
    class Palette:
        name: String(required=True)
        brand: Custom(
            Color,
            validators=[PlainValidator(parse_color)],
            serializers=[PlainSerializer(lambda color: color.hex, return_type=str)],
            required=True,
        )

    domain.init(traverse=False)
    return IRBuilder(domain).build()


@pytest.fixture(scope="module")
def ir_with_default():
    domain = Domain(name="Custom Field Default IR")

    @domain.aggregate
    class Theme:
        name: String(required=True)
        brand: Custom(
            Color,
            validators=[PlainValidator(parse_color)],
            serializers=[PlainSerializer(lambda color: color.hex, return_type=str)],
            default=Color("#FFFFFF"),
        )

    domain.init(traverse=False)
    return IRBuilder(domain).build()


@pytest.fixture(scope="module")
def brand_field(ir):
    cluster = next(c for fqn, c in ir["clusters"].items() if fqn.endswith(".Palette"))
    return cluster["aggregate"]["fields"]["brand"]


@pytest.mark.no_test_domain
class TestCustomFieldIR:
    def test_custom_field_carries_the_custom_kind(self, brand_field):
        assert brand_field["kind"] == "custom"
        assert brand_field["required"] is True

    def test_ir_with_a_custom_field_validates_against_the_schema(self, ir):
        try:
            validate(instance=ir, schema=load_schema())
        except ValidationError as exc:
            pytest.fail(
                f"IR with a custom field failed schema validation:\n"
                f"  Path: {'.'.join(str(p) for p in exc.absolute_path)}\n"
                f"  Message: {exc.message}"
            )


@pytest.mark.no_test_domain
class TestCustomFieldDefaultInIR:
    """A custom default is an instance of the custom type; the IR is JSON."""

    def test_custom_default_is_serialized(self, ir_with_default):
        cluster = next(
            c
            for fqn, c in ir_with_default["clusters"].items()
            if fqn.endswith(".Theme")
        )
        assert cluster["aggregate"]["fields"]["brand"]["default"] == "#FFFFFF"

    def test_ir_with_a_custom_default_serializes_to_json(self, ir_with_default):
        # The IR is written out as JSON and hashed into the canonical baselines,
        # so an unserialized default breaks every emitter, not just this test.
        json.dumps(ir_with_default)

    def test_ir_with_a_custom_default_validates_against_the_schema(
        self, ir_with_default
    ):
        try:
            validate(instance=ir_with_default, schema=load_schema())
        except ValidationError as exc:
            pytest.fail(
                f"IR with a custom default failed schema validation:\n"
                f"  Path: {'.'.join(str(p) for p in exc.absolute_path)}\n"
                f"  Message: {exc.message}"
            )


@pytest.fixture(scope="module")
def custom_type_fields():
    domain = Domain(name="Custom Field Type Names")

    @domain.aggregate
    class Reading:
        label: String(required=True)
        count: Custom(int, validators=[PlainValidator(lambda v: int(v))])
        ratio: Custom(float, validators=[PlainValidator(lambda v: float(v))])
        code: Custom(str, validators=[PlainValidator(lambda v: str(v))])
        brand: Custom(Color, validators=[PlainValidator(parse_color)])

    domain.init(traverse=False)
    ir = IRBuilder(domain).build()
    cluster = next(c for fqn, c in ir["clusters"].items() if fqn.endswith(".Reading"))
    return cluster["aggregate"]["fields"]


@pytest.mark.no_test_domain
class TestCustomFieldTypeName:
    """The IR ``type`` names the shape the value is stored in.

    The schema, Avro and Protobuf generators read this name, so a custom field
    over a primitive has to report that primitive: ``Custom(int, ...)`` stores
    an integer and must not be published as a string.
    """

    @pytest.mark.parametrize(
        ("name", "ir_type"),
        [
            ("count", "Integer"),
            ("ratio", "Float"),
            ("code", "String"),
            # An arbitrary class serializes through its own ``to_dict``, whose
            # shape the builder cannot know, so it stays String.
            ("brand", "String"),
        ],
    )
    def test_custom_field_type_follows_the_python_type(
        self, custom_type_fields, name, ir_type
    ):
        assert custom_type_fields[name]["kind"] == "custom"
        assert custom_type_fields[name]["type"] == ir_type
