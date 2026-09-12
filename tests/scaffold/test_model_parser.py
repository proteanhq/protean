"""Tests for the textual event-model parser, emitter, and their round trip.

The grammar and the normative worked example are ADR-0041. The parser turns model
text into a slice-shaped IR fragment; the emitter reads a real IR (built by
``to_ir()``) back to model text; the conformance test asserts the two are inverses
over the covered subset, matching the ADR worked example.
"""

import json
from pathlib import Path

import pytest

from protean import Domain, handle
from protean.fields import ValueObject
from protean.fields.simple import Identifier, String
from protean.scaffold.model_parser import (
    ModelEmitError,
    ModelParseError,
    emit_model,
    parse_model,
)

# The normative worked example (ADR-0041, the Order slice text and its fragment).
ORDER_MODEL = """aggregate Order:
    field name: string(max_length=100)

command CreateOrder:
    field name: string(max_length=100)

event OrderCreated:
    field order_id: string
    field name: string(max_length=100)

projection OrderSummary:
    field order_id: identifier(key)
    field name: string(max_length=100)

projector OrderProjector:
    for OrderSummary
    consumes OrderCreated
"""

ORDER_FRAGMENT = {
    "aggregate": {
        "name": "Order",
        "fields": {
            "name": {
                "kind": "standard",
                "type": "String",
                "max_length": 100,
                "required": True,
            }
        },
    },
    "command": {
        "name": "CreateOrder",
        "fields": {
            "name": {
                "kind": "standard",
                "type": "String",
                "max_length": 100,
                "required": True,
            }
        },
    },
    "event": {
        "name": "OrderCreated",
        "fields": {
            "order_id": {"kind": "standard", "type": "String", "required": True},
            "name": {
                "kind": "standard",
                "type": "String",
                "max_length": 100,
                "required": True,
            },
        },
    },
    "projection": {
        "name": "OrderSummary",
        "fields": {
            "order_id": {
                "kind": "identifier",
                "type": "Identifier",
                "identifier": True,
            },
            "name": {
                "kind": "standard",
                "type": "String",
                "max_length": 100,
                "required": True,
            },
        },
    },
    "projector": {
        "name": "OrderProjector",
        "for": "OrderSummary",
        "consumes": "OrderCreated",
    },
}


# ---------------------------------------------------------------------------
# Domain builders for the emitter and conformance tests
# ---------------------------------------------------------------------------


def _build_order_domain() -> Domain:
    """The eligible Order slice, whose ``to_ir()`` emits the ADR worked example."""
    domain = Domain(name="Ordering", root_path=".")

    @domain.event(part_of="Order")
    class OrderCreated:
        # ``max_length=None`` opts out of the default String max, so the surfaced
        # ``order_id`` reference is a plain ``string`` (ADR-0041 worked example).
        order_id = String(max_length=None, required=True)
        name = String(max_length=100, required=True)

    @domain.aggregate
    class Order:
        name = String(max_length=100, required=True)

    @domain.command(part_of="Order")
    class CreateOrder:
        name = String(max_length=100, required=True)

    @domain.projection
    class OrderSummary:
        order_id = Identifier(required=True, identifier=True)
        name = String(max_length=100)

    @domain.projector(projector_for=OrderSummary, aggregates=[Order])
    class OrderProjector:
        @handle(OrderCreated)
        def on_order_created(self, event):
            pass

    domain.init(traverse=False)
    return domain


def _build_write_side_only_domain() -> Domain:
    """An aggregate, command, and event with no read side."""
    domain = Domain(name="Ordering", root_path=".")

    @domain.event(part_of="Order")
    class OrderCreated:
        order_id = String(max_length=None, required=True)
        name = String(max_length=100, required=True)

    @domain.aggregate
    class Order:
        name = String(max_length=100, required=True)

    @domain.command(part_of="Order")
    class CreateOrder:
        name = String(max_length=100, required=True)

    domain.init(traverse=False)
    return domain


def _cluster_fqn(ir: dict) -> str:
    return next(iter(ir["clusters"]))


# ---------------------------------------------------------------------------
# Parser: the worked example and structural shapes
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestParseWorkedExample:
    def test_parses_to_the_adr_fragment(self):
        assert parse_model(ORDER_MODEL) == ORDER_FRAGMENT

    def test_write_side_only_has_no_read_side(self):
        model = """aggregate Order:
    field name: string(max_length=100)

command CreateOrder:
    field name: string(max_length=100)

event OrderCreated:
    field name: string(max_length=100)
"""
        fragment = parse_model(model)
        assert "projection" not in fragment
        assert "projector" not in fragment
        assert set(fragment) == {"aggregate", "command", "event"}

    def test_blank_and_comment_lines_are_ignored(self):
        model = """# a leading comment
aggregate Order:

    # the aggregate's fields
    field name: string(max_length=100)

command CreateOrder:
    field name: string(max_length=100)

event OrderCreated:
    field name: string(max_length=100)
"""
        assert parse_model(model)["aggregate"]["name"] == "Order"

    def test_name_normalization_matches_protean_add(self):
        model = """aggregate order_item:
    field name: string(max_length=100)

command createOrderItem:
    field name: string(max_length=100)

event order_item_created:
    field name: string(max_length=100)
"""
        fragment = parse_model(model)
        assert fragment["aggregate"]["name"] == "OrderItem"
        assert fragment["command"]["name"] == "CreateOrderItem"
        assert fragment["event"]["name"] == "OrderItemCreated"


@pytest.mark.no_test_domain
class TestParseEveryPrimitive:
    def test_every_type_and_both_constraints(self):
        model = """aggregate Thing:
    field a: string
    field b: text
    field c: integer
    field d: float
    field e: boolean
    field f: date
    field g: datetime
    field h: identifier
    field i: string(max_length=50)
    field j: text(max_length=10)

command CreateThing:
    field name: string

event ThingCreated:
    field name: string
"""
        fields = parse_model(model)["aggregate"]["fields"]
        assert fields["a"] == {"kind": "standard", "type": "String", "required": True}
        assert fields["b"] == {"kind": "text", "type": "Text", "required": True}
        assert fields["c"] == {"kind": "standard", "type": "Integer", "required": True}
        assert fields["d"] == {"kind": "standard", "type": "Float", "required": True}
        assert fields["e"] == {"kind": "standard", "type": "Boolean", "required": True}
        assert fields["f"] == {"kind": "standard", "type": "Date", "required": True}
        assert fields["g"] == {"kind": "standard", "type": "DateTime", "required": True}
        assert fields["h"] == {
            "kind": "identifier",
            "type": "Identifier",
            "required": True,
        }
        assert fields["i"] == {
            "kind": "standard",
            "type": "String",
            "max_length": 50,
            "required": True,
        }
        assert fields["j"] == {
            "kind": "text",
            "type": "Text",
            "max_length": 10,
            "required": True,
        }


# ---------------------------------------------------------------------------
# Parser: one negative test per rule, each asserting the reported line
# ---------------------------------------------------------------------------


def _write_side(*extra_blocks: str) -> str:
    """A minimal valid write side, plus any extra blocks appended."""
    base = """aggregate Order:
    field name: string(max_length=100)

command CreateOrder:
    field name: string(max_length=100)

event OrderCreated:
    field order_id: string
    field name: string(max_length=100)
"""
    return base + "".join(extra_blocks)


@pytest.mark.no_test_domain
class TestParseRejections:
    def test_bad_keyword(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("widget Order:\n    field name: string\n")
        assert exc.value.line == 1

    def test_non_identifier_name(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate 2Bad:\n    field name: string\n")
        assert exc.value.line == 1

    def test_python_keyword_name(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate class:\n    field name: string\n")
        assert exc.value.line == 1

    def test_unknown_field_type(self):
        model = "aggregate Order:\n    field name: str\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2

    def test_python_keyword_field_name(self):
        model = "aggregate Order:\n    field class: string\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2

    def test_duplicate_field_name(self):
        model = "aggregate Order:\n    field name: string\n    field name: integer\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 3

    def test_max_length_on_non_string(self):
        model = "aggregate Order:\n    field count: integer(max_length=5)\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2

    def test_non_positive_max_length(self):
        model = "aggregate Order:\n    field name: string(max_length=0)\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2

    def test_key_on_non_identifier_field(self):
        # ``key`` in a projection but on a string field.
        model = _write_side(
            "\nprojection OrderSummary:\n    field order_id: identifier(key)\n"
            "    field name: string(key)\n",
            "\nprojector OrderProjector:\n    for OrderSummary\n"
            "    consumes OrderCreated\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The offending 'field name: string(key)' is the 13th physical line.
        assert exc.value.line == 13

    def test_key_outside_a_projection(self):
        model = "aggregate Order:\n    field order_id: identifier(key)\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2

    def test_two_aggregates(self):
        model = _write_side("\naggregate Extra:\n    field name: string\n")
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The second aggregate header is the 11th physical line.
        assert exc.value.line == 11

    def test_no_command(self):
        model = """aggregate Order:
    field name: string

event OrderCreated:
    field name: string
"""
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # A missing block is reported at the end of the model.
        assert exc.value.line == len(model.splitlines())

    def test_projector_without_projection(self):
        model = _write_side(
            "\nprojector OrderProjector:\n    for OrderSummary\n"
            "    consumes OrderCreated\n"
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The projector header (present without a projection) is line 11.
        assert exc.value.line == 11

    def test_for_names_an_undefined_projection(self):
        model = _write_side(
            "\nprojection OrderSummary:\n    field order_id: identifier(key)\n",
            "\nprojector OrderProjector:\n    for WrongName\n"
            "    consumes OrderCreated\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The 'for WrongName' line is the 15th physical line.
        assert exc.value.line == 15

    def test_consumes_names_an_undefined_event(self):
        model = _write_side(
            "\nprojection OrderSummary:\n    field order_id: identifier(key)\n",
            "\nprojector OrderProjector:\n    for OrderSummary\n"
            "    consumes WrongEvent\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The 'consumes WrongEvent' line is the 16th physical line.
        assert exc.value.line == 16

    def test_projection_field_absent_from_event(self):
        model = _write_side(
            "\nprojection OrderSummary:\n    field order_id: identifier(key)\n"
            "    field missing: string\n",
            "\nprojector OrderProjector:\n    for OrderSummary\n"
            "    consumes OrderCreated\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The 'field missing: string' line is the 13th physical line.
        assert exc.value.line == 13

    def test_projection_field_shape_mismatch(self):
        # 'name' is on the event as string(max_length=100); here it is max_length=50.
        model = _write_side(
            "\nprojection OrderSummary:\n    field order_id: identifier(key)\n"
            "    field name: string(max_length=50)\n",
            "\nprojector OrderProjector:\n    for OrderSummary\n"
            "    consumes OrderCreated\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The 'field name: string(max_length=50)' line is line 13.
        assert exc.value.line == 13

    def test_projection_with_no_key(self):
        model = _write_side(
            "\nprojection OrderSummary:\n    field name: string(max_length=100)\n",
            "\nprojector OrderProjector:\n    for OrderSummary\n"
            "    consumes OrderCreated\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # Reported at the projection header, line 11.
        assert exc.value.line == 11

    def test_projection_with_two_keys(self):
        model = _write_side(
            "\nprojection OrderSummary:\n    field order_id: identifier(key)\n"
            "    field alt_id: identifier(key)\n",
            "\nprojector OrderProjector:\n    for OrderSummary\n"
            "    consumes OrderCreated\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The second key field is line 13.
        assert exc.value.line == 13

    def test_projection_key_must_be_slug_id(self):
        # The only key is 'wrong_id', not the aggregate's surfaced 'order_id'.
        model = _write_side(
            "\nprojection OrderSummary:\n    field wrong_id: identifier(key)\n",
            "\nprojector OrderProjector:\n    for OrderSummary\n"
            "    consumes OrderCreated\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The 'field wrong_id' key line is line 12.
        assert exc.value.line == 12

    def test_indented_line_before_any_header(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("    field name: string\n")
        assert exc.value.line == 1

    def test_malformed_header_without_colon(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate Order\n    field name: string\n")
        assert exc.value.line == 1

    def test_non_identifier_field_name(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate Order:\n    field 2x: string\n")
        assert exc.value.line == 2

    def test_body_line_that_is_not_a_field(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate Order:\n    not a field line\n")
        assert exc.value.line == 2

    def test_empty_max_length_constraint(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate Order:\n    field name: string(max_length=)\n")
        assert exc.value.line == 2

    def test_unknown_constraint(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate Order:\n    field name: string(weird)\n")
        assert exc.value.line == 2

    def test_duplicate_for_line(self):
        model = "projector P:\n    for A\n    for B\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 3

    def test_duplicate_consumes_line(self):
        model = "projector P:\n    consumes A\n    consumes B\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 3

    def test_projector_body_line_that_is_neither_for_nor_consumes(self):
        model = "projector P:\n    field x: string\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2

    def test_two_projections(self):
        model = _write_side(
            "\nprojection OrderSummary:\n    field order_id: identifier(key)\n",
            "\nprojection Other:\n    field order_id: identifier(key)\n",
            "\nprojector OrderProjector:\n    for OrderSummary\n"
            "    consumes OrderCreated\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The second projection header is line 14.
        assert exc.value.line == 14

    def test_two_projectors(self):
        model = _write_side(
            "\nprojection OrderSummary:\n    field order_id: identifier(key)\n",
            "\nprojector OrderProjector:\n    for OrderSummary\n"
            "    consumes OrderCreated\n",
            "\nprojector Second:\n    for OrderSummary\n    consumes OrderCreated\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The second projector header is line 18.
        assert exc.value.line == 18

    def test_projector_missing_for_line(self):
        model = _write_side(
            "\nprojection OrderSummary:\n    field order_id: identifier(key)\n",
            "\nprojector OrderProjector:\n    consumes OrderCreated\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # Reported at the projector header, line 14.
        assert exc.value.line == 14

    def test_projector_missing_consumes_line(self):
        model = _write_side(
            "\nprojection OrderSummary:\n    field order_id: identifier(key)\n",
            "\nprojector OrderProjector:\n    for OrderSummary\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # Reported at the projector header, line 14.
        assert exc.value.line == 14


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestEmitter:
    def test_eligible_cluster_emits_parseable_text(self):
        ir = _build_order_domain().to_ir()
        text = emit_model(ir, _cluster_fqn(ir))
        # The text parses, and the round trip yields the ADR worked example.
        assert parse_model(text) == ORDER_FRAGMENT

    def test_fields_are_name_sorted(self):
        ir = _build_order_domain().to_ir()
        text = emit_model(ir, _cluster_fqn(ir))
        event_body = text.split("event OrderCreated:\n", 1)[1]
        # 'name' sorts before 'order_id'.
        assert (
            event_body.splitlines()[0].strip() == "field name: string(max_length=100)"
        )
        assert event_body.splitlines()[1].strip() == "field order_id: string"

    def test_injected_identity_is_filtered(self):
        ir = _build_order_domain().to_ir()
        text = emit_model(ir, _cluster_fqn(ir))
        assert "field id:" not in text

    def test_fact_event_is_not_emitted(self):
        domain = Domain(name="Ordering", root_path=".")

        @domain.event(part_of="Order")
        class OrderCreated:
            name = String(max_length=100, required=True)

        @domain.aggregate(fact_events=True)
        class Order:
            name = String(max_length=100, required=True)

        @domain.command(part_of="Order")
        class CreateOrder:
            name = String(max_length=100, required=True)

        domain.init(traverse=False)
        ir = domain.to_ir()
        text = emit_model(ir, _cluster_fqn(ir))
        # Exactly the one authored event is emitted; the fact event is filtered.
        assert "event OrderCreated:" in text
        assert "Fact" not in text

    def test_write_side_only_emits_three_blocks(self):
        ir = _build_write_side_only_domain().to_ir()
        text = emit_model(ir, _cluster_fqn(ir))
        assert "projection" not in text
        assert "projector" not in text
        fragment = parse_model(text)
        assert set(fragment) == {"aggregate", "command", "event"}

    def test_unknown_cluster_raises(self):
        ir = _build_order_domain().to_ir()
        with pytest.raises(ModelEmitError):
            emit_model(ir, "nope.Missing")

    def test_value_object_field_raises(self):
        domain = Domain(name="Ordering", root_path=".")

        @domain.value_object
        class Address:
            city = String(max_length=50, required=True)

        @domain.event(part_of="Order")
        class OrderCreated:
            name = String(max_length=100, required=True)

        @domain.aggregate
        class Order:
            name = String(max_length=100, required=True)
            shipping = ValueObject(Address)

        @domain.command(part_of="Order")
        class CreateOrder:
            name = String(max_length=100, required=True)

        domain.init(traverse=False)
        ir = domain.to_ir()
        with pytest.raises(ModelEmitError):
            emit_model(ir, _cluster_fqn(ir))

    def test_second_command_raises(self):
        domain = Domain(name="Ordering", root_path=".")

        @domain.event(part_of="Order")
        class OrderCreated:
            name = String(max_length=100, required=True)

        @domain.aggregate
        class Order:
            name = String(max_length=100, required=True)

        @domain.command(part_of="Order")
        class CreateOrder:
            name = String(max_length=100, required=True)

        @domain.command(part_of="Order")
        class CancelOrder:
            name = String(max_length=100, required=True)

        domain.init(traverse=False)
        ir = domain.to_ir()
        with pytest.raises(ModelEmitError):
            emit_model(ir, _cluster_fqn(ir))

    def test_choices_field_raises(self):
        domain = Domain(name="Ordering", root_path=".")

        @domain.event(part_of="Order")
        class OrderCreated:
            name = String(max_length=100, required=True)

        @domain.aggregate
        class Order:
            name = String(max_length=100, required=True)
            status = String(max_length=20, choices=["OPEN", "CLOSED"])

        @domain.command(part_of="Order")
        class CreateOrder:
            name = String(max_length=100, required=True)

        domain.init(traverse=False)
        ir = domain.to_ir()
        with pytest.raises(ModelEmitError):
            emit_model(ir, _cluster_fqn(ir))

    def test_multi_aggregate_projector_raises(self):
        """The shipped ordering example is ineligible; the emitter must raise."""
        example = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "protean"
            / "ir"
            / "examples"
            / "ordering-ir.json"
        )
        ir = json.loads(example.read_text(encoding="utf-8"))
        with pytest.raises(ModelEmitError):
            emit_model(ir, "ecommerce.ordering.Order")


def _synthetic_ir(
    *,
    event_fields: dict | None = None,
    aggregate_fields: dict | None = None,
    projections: dict | None = None,
) -> dict:
    """A hand-built IR carrying just the keys the emitter reads.

    The emitter takes a plain dict, so a synthetic IR is the most direct way to
    reach its ineligibility branches for field shapes and read-side wiring that a
    real ``to_ir()`` will not produce.
    """
    clean = {"name": {"kind": "standard", "type": "String", "required": True}}
    return {
        "clusters": {
            "m.Order": {
                "aggregate": {
                    "name": "Order",
                    "fields": aggregate_fields
                    if aggregate_fields is not None
                    else clean,
                },
                "commands": {
                    "m.CreateOrder": {"name": "CreateOrder", "fields": dict(clean)}
                },
                "events": {
                    "m.OrderCreated": {
                        "name": "OrderCreated",
                        "__type__": "M.OrderCreated.v1",
                        "fields": event_fields
                        if event_fields is not None
                        else dict(clean),
                    }
                },
            }
        },
        "projections": projections or {},
    }


@pytest.mark.no_test_domain
class TestEmitterIneligibility:
    def test_two_authored_events_raises(self):
        domain = Domain(name="Ordering", root_path=".")

        @domain.event(part_of="Order")
        class OrderCreated:
            name = String(max_length=100, required=True)

        @domain.event(part_of="Order")
        class OrderRenamed:
            name = String(max_length=100, required=True)

        @domain.aggregate
        class Order:
            name = String(max_length=100, required=True)

        @domain.command(part_of="Order")
        class CreateOrder:
            name = String(max_length=100, required=True)

        domain.init(traverse=False)
        ir = domain.to_ir()
        with pytest.raises(ModelEmitError):
            emit_model(ir, _cluster_fqn(ir))

    def test_aggregate_with_only_the_injected_id_emits_a_headerless_block(self):
        ir = _synthetic_ir(
            aggregate_fields={
                "id": {"kind": "auto", "type": "Auto", "auto_generated": True}
            }
        )
        text = emit_model(ir, "m.Order")
        # The aggregate block is just its header; its only field was the injected id.
        assert "aggregate Order:\n\n" in text or text.startswith("aggregate Order:\n")
        assert "field id" not in text

    def test_field_max_length_on_non_string_raises(self):
        ir = _synthetic_ir(
            event_fields={
                "count": {
                    "kind": "standard",
                    "type": "Integer",
                    "max_length": 5,
                    "required": True,
                }
            }
        )
        with pytest.raises(ModelEmitError):
            emit_model(ir, "m.Order")

    def test_identifier_flag_outside_a_projection_raises(self):
        ir = _synthetic_ir(
            event_fields={
                "ref": {
                    "kind": "identifier",
                    "type": "Identifier",
                    "identifier": True,
                    "required": True,
                }
            }
        )
        with pytest.raises(ModelEmitError):
            emit_model(ir, "m.Order")

    def test_unexpressible_field_key_raises(self):
        ir = _synthetic_ir(
            event_fields={
                "status": {
                    "kind": "standard",
                    "type": "String",
                    "choices": ["A", "B"],
                }
            }
        )
        with pytest.raises(ModelEmitError):
            emit_model(ir, "m.Order")

    def test_multi_aggregate_projector_raises(self):
        projections = {
            "m.Report": {
                "projection": {
                    "name": "OrderSummary",
                    "fields": {
                        "order_id": {
                            "kind": "identifier",
                            "type": "Identifier",
                            "identifier": True,
                        }
                    },
                },
                "projectors": {
                    "m.OrderProjector": {
                        "name": "OrderProjector",
                        "aggregates": ["m.Order", "m.Other"],
                        "handlers": {"M.OrderCreated.v1": ["on_order_created"]},
                    }
                },
            }
        }
        with pytest.raises(ModelEmitError):
            emit_model(_synthetic_ir(projections=projections), "m.Order")

    def test_multi_handler_projector_raises(self):
        projections = {
            "m.Report": {
                "projection": {"name": "OrderSummary", "fields": {}},
                "projectors": {
                    "m.OrderProjector": {
                        "name": "OrderProjector",
                        "aggregates": ["m.Order"],
                        "handlers": {
                            "M.OrderCreated.v1": ["on_created"],
                            "M.OrderRenamed.v1": ["on_renamed"],
                        },
                    }
                },
            }
        }
        with pytest.raises(ModelEmitError):
            emit_model(_synthetic_ir(projections=projections), "m.Order")

    def test_two_projectors_for_one_cluster_raises(self):
        one = {
            "name": "OrderProjector",
            "aggregates": ["m.Order"],
            "handlers": {"M.OrderCreated.v1": ["on_created"]},
        }
        projections = {
            "m.ReportA": {
                "projection": {"name": "SummaryA", "fields": {}},
                "projectors": {"m.PA": dict(one, name="PA")},
            },
            "m.ReportB": {
                "projection": {"name": "SummaryB", "fields": {}},
                "projectors": {"m.PB": dict(one, name="PB")},
            },
        }
        with pytest.raises(ModelEmitError):
            emit_model(_synthetic_ir(projections=projections), "m.Order")

    def test_projection_for_a_different_cluster_is_ignored(self):
        # A projector that names neither this cluster nor its event leaves the
        # slice write-side-only rather than raising.
        projections = {
            "m.Report": {
                "projection": {"name": "OtherSummary", "fields": {}},
                "projectors": {
                    "m.OtherProjector": {
                        "name": "OtherProjector",
                        "aggregates": ["m.Elsewhere"],
                        "handlers": {"M.Elsewhere.v1": ["on_it"]},
                    }
                },
            }
        }
        text = emit_model(_synthetic_ir(projections=projections), "m.Order")
        assert "projection" not in text
        assert "projector" not in text


# ---------------------------------------------------------------------------
# Conformance: IR to text to IR is an inverse over the covered subset
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestConformance:
    def test_order_slice_round_trip(self):
        ir = _build_order_domain().to_ir()
        text = emit_model(ir, _cluster_fqn(ir))
        assert parse_model(text) == ORDER_FRAGMENT

    def test_write_side_only_round_trip(self):
        ir = _build_write_side_only_domain().to_ir()
        text = emit_model(ir, _cluster_fqn(ir))
        fragment = parse_model(text)
        assert set(fragment) == {"aggregate", "command", "event"}
        assert fragment["aggregate"] == {
            "name": "Order",
            "fields": {
                "name": {
                    "kind": "standard",
                    "type": "String",
                    "max_length": 100,
                    "required": True,
                }
            },
        }
        assert fragment["event"]["fields"]["order_id"] == {
            "kind": "standard",
            "type": "String",
            "required": True,
        }
