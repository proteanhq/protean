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
from protean.fields.simple import Auto, Identifier, String
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
        # Required, so it emits faithfully: the grammar has no optional form, and
        # the ADR worked example carries the projection's ``name`` as required.
        name = String(max_length=100, required=True)

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
        # The event still carries the surfaced id: with no read side authored, the
        # generator derives the default projection from the event with that field as
        # its key (ADR-0041), so the model has to supply it either way.
        model = """aggregate Order:
    field name: string(max_length=100)

command CreateOrder:
    field name: string(max_length=100)

event OrderCreated:
    field order_id: string
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
    field order_id: string
    field name: string(max_length=100)
"""
        assert parse_model(model)["aggregate"]["name"] == "Order"

    def test_name_normalization_matches_protean_add(self):
        model = """aggregate order_item:
    field name: string(max_length=100)

command createOrderItem:
    field name: string(max_length=100)

event order_item_created:
    field order_item_id: string
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
    field thing_id: string
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
    # Each test asserts both the reported line and a rule-identifying substring of
    # the message, so a wrong branch that raises at the same physical line cannot
    # pass in place of the rule under test.

    def test_bad_keyword(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("widget Order:\n    field name: string\n")
        assert exc.value.line == 1
        assert "unknown block keyword" in str(exc.value)

    def test_non_identifier_name(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate 2Bad:\n    field name: string\n")
        assert exc.value.line == 1
        assert "is not a valid name" in str(exc.value)

    def test_python_keyword_name(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate class:\n    field name: string\n")
        assert exc.value.line == 1
        assert "is a Python keyword" in str(exc.value)

    def test_name_that_normalizes_to_an_invalid_class_name(self):
        # ``_2fa`` passes ``isidentifier()`` but normalizes to ``2fa``, which is
        # not a valid class name.
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate _2fa:\n    field name: string\n")
        assert exc.value.line == 1
        assert "does not normalize to a valid class name" in str(exc.value)

    def test_aggregate_name_whose_slug_is_a_python_keyword(self):
        # ``class_`` normalizes to the valid class ``Class`` but to the slug
        # ``class``, a keyword. ``plan_add_slice`` rejects that pair too, and the
        # aggregate's slug is what the surfaced id is derived from.
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate class_:\n    field name: string\n")
        assert exc.value.line == 1
        assert "module variable" in str(exc.value)

    def test_reserved_identity_field_name_on_the_aggregate(self):
        # The framework injects the aggregate's ``id``; an authored ``id`` is
        # replaced by it, so the declaration here would be lost on promotion.
        model = "aggregate Order:\n    field id: string\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2
        assert "is reserved" in str(exc.value)

    def test_reserved_factory_field_name_on_the_aggregate(self):
        model = "aggregate Order:\n    field create: string\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2
        assert "is reserved" in str(exc.value)

    def test_reserved_meta_field_name_on_a_command(self):
        # ``Meta`` is the nested options class the generated element declares.
        model = (
            "aggregate Order:\n    field name: string\n\n"
            "command CreateOrder:\n    field Meta: string\n"
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 5
        assert "is reserved" in str(exc.value)

    def test_reserved_name_is_allowed_where_it_is_not_declared(self):
        # ``create`` is reserved on the aggregate, not on the event: the reservation
        # is per block, so this parses.
        model = (
            "aggregate Order:\n    field name: string\n\n"
            "command CreateOrder:\n    field name: string\n\n"
            "event OrderCreated:\n    field order_id: string\n"
            "    field create: string\n"
        )
        assert "create" in parse_model(model)["event"]["fields"]

    def test_event_without_the_surfaced_id(self):
        # The read side keys on the surfaced id and has no other source for it
        # (ADR-0041), so an event that omits it is rejected on the event header.
        model = (
            "aggregate Order:\n    field name: string\n\n"
            "command CreateOrder:\n    field name: string\n\n"
            "event OrderCreated:\n    field name: string\n\n"
            "projection OrderSummary:\n    field order_id: identifier(key)\n"
            "    field name: string\n\n"
            "projector OrderProjector:\n    for OrderSummary\n"
            "    consumes OrderCreated\n"
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The 'event OrderCreated:' header is the 7th physical line.
        assert exc.value.line == 7
        assert "must carry 'order_id'" in str(exc.value)

    def test_write_side_only_event_without_the_surfaced_id(self):
        # The rule does not depend on a read side being authored: the generator
        # derives the default projection from the event and keys it on this field.
        model = (
            "aggregate Order:\n    field name: string\n\n"
            "command CreateOrder:\n    field name: string\n\n"
            "event OrderCreated:\n    field name: string\n"
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 7
        assert "must carry 'order_id'" in str(exc.value)

    def test_surfaced_id_of_the_wrong_type(self):
        # ADR-0041 v1 surfaces the reference as a string or an identifier. An
        # integer cannot hold the aggregate's id.
        model = (
            "aggregate Order:\n    field name: string\n\n"
            "command CreateOrder:\n    field name: string\n\n"
            "event OrderCreated:\n    field order_id: integer\n"
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 8
        assert "must be a string or an identifier" in str(exc.value)

    def test_surfaced_id_may_be_an_identifier(self):
        model = (
            "aggregate Order:\n    field name: string\n\n"
            "command CreateOrder:\n    field name: string\n\n"
            "event OrderCreated:\n    field order_id: identifier\n"
        )
        assert parse_model(model)["event"]["fields"]["order_id"]["type"] == "Identifier"

    def test_empty_constraint_list(self):
        model = "aggregate Order:\n    field name: string()\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2
        assert "empty constraint list" in str(exc.value)

    def test_max_length_with_a_unicode_numeric(self):
        # A superscript two satisfies ``isdigit`` but not ``int()``; every violation
        # has to surface as a ModelParseError, not a raw ValueError.
        model = "aggregate Order:\n    field name: string(max_length=\u00b2)\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2
        assert "max_length must be a positive integer" in str(exc.value)

    def test_non_aggregate_name_with_a_keyword_slug_is_accepted(self):
        # Only the aggregate's slug is load-bearing (it derives the surfaced id).
        # ``command class_:`` gives the valid class ``Class``, and ADR-0041's grammar
        # admits any non-keyword identifier as a block name.
        model = (
            "aggregate Order:\n    field name: string\n\n"
            "command class_:\n    field name: string\n\n"
            "event OrderCreated:\n    field order_id: string\n"
        )
        assert parse_model(model)["command"]["name"] == "Class"

    def test_unknown_field_type(self):
        model = "aggregate Order:\n    field name: str\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2
        assert "unknown field type" in str(exc.value)

    def test_python_keyword_field_name(self):
        model = "aggregate Order:\n    field class: string\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2
        assert "is a Python keyword" in str(exc.value)

    def test_duplicate_field_name(self):
        model = "aggregate Order:\n    field name: string\n    field name: integer\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 3
        assert "duplicate field" in str(exc.value)

    def test_max_length_on_non_string(self):
        model = "aggregate Order:\n    field count: integer(max_length=5)\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2
        assert "max_length is valid only on string and text" in str(exc.value)

    def test_non_positive_max_length(self):
        model = "aggregate Order:\n    field name: string(max_length=0)\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2
        assert "max_length must be a positive integer" in str(exc.value)

    def test_duplicate_max_length_constraint(self):
        model = "aggregate Order:\n    field name: string(max_length=5, max_length=6)\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2
        assert "duplicate 'max_length' constraint" in str(exc.value)

    def test_duplicate_key_constraint(self):
        model = _write_side(
            "\nprojection OrderSummary:\n    field order_id: identifier(key, key)\n"
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The 'field order_id: identifier(key, key)' line is the 12th physical line.
        assert exc.value.line == 12
        assert "duplicate 'key' constraint" in str(exc.value)

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
        assert "'key' is valid only on" in str(exc.value)

    def test_key_outside_a_projection(self):
        model = "aggregate Order:\n    field order_id: identifier(key)\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2
        assert "'key' is valid only on" in str(exc.value)

    def test_two_aggregates(self):
        model = _write_side("\naggregate Extra:\n    field name: string\n")
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The second aggregate header is the 11th physical line.
        assert exc.value.line == 11
        assert "more than one aggregate" in str(exc.value)

    def test_two_commands(self):
        model = _write_side("\ncommand Second:\n    field name: string\n")
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The second command header is the 11th physical line.
        assert exc.value.line == 11
        assert "more than one command" in str(exc.value)

    def test_two_events(self):
        model = _write_side("\nevent Second:\n    field name: string\n")
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The second event header is the 11th physical line.
        assert exc.value.line == 11
        assert "more than one event" in str(exc.value)

    def test_no_aggregate(self):
        model = """command CreateOrder:
    field name: string

event OrderCreated:
    field name: string
"""
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == len(model.splitlines())
        assert "must define exactly one aggregate" in str(exc.value)

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
        assert "must define exactly one command" in str(exc.value)

    def test_no_event(self):
        model = """aggregate Order:
    field name: string

command CreateOrder:
    field name: string
"""
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == len(model.splitlines())
        assert "must define exactly one event" in str(exc.value)

    def test_empty_string(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("")
        assert exc.value.line == 1
        assert "must define exactly one aggregate" in str(exc.value)

    def test_whitespace_only(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("   \n  \n")
        assert exc.value.line == 2
        assert "must define exactly one aggregate" in str(exc.value)

    def test_non_string_input(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model(None)  # type: ignore[arg-type]
        assert exc.value.line == 1
        assert "must be a string" in str(exc.value)

    def test_projector_without_projection(self):
        model = _write_side(
            "\nprojector OrderProjector:\n    for OrderSummary\n"
            "    consumes OrderCreated\n"
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # The projector header (present without a projection) is line 11.
        assert exc.value.line == 11
        assert "read side needs both a projection and a projector" in str(exc.value)

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
        assert "does not name the model's projection" in str(exc.value)

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
        assert "does not name the model's" in str(exc.value)

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
        assert "is not on the event" in str(exc.value)

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
        assert "does not match the shape" in str(exc.value)

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
        assert "needs exactly one 'key' field" in str(exc.value)

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
        assert "more than one 'key' field" in str(exc.value)

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
        assert "projection key must be" in str(exc.value)

    def test_indented_line_before_any_header(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("    field name: string\n")
        assert exc.value.line == 1
        assert "indented line appears before any block header" in str(exc.value)

    def test_malformed_header_without_colon(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate Order\n    field name: string\n")
        assert exc.value.line == 1
        assert "malformed block header" in str(exc.value)

    def test_non_identifier_field_name(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate Order:\n    field 2x: string\n")
        assert exc.value.line == 2
        assert "is not a valid name" in str(exc.value)

    def test_body_line_that_is_not_a_field(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate Order:\n    not a field line\n")
        assert exc.value.line == 2
        assert "expected a field line" in str(exc.value)

    def test_empty_max_length_constraint(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate Order:\n    field name: string(max_length=)\n")
        assert exc.value.line == 2
        assert "malformed constraint" in str(exc.value)

    def test_unknown_constraint(self):
        with pytest.raises(ModelParseError) as exc:
            parse_model("aggregate Order:\n    field name: string(weird)\n")
        assert exc.value.line == 2
        assert "unknown constraint" in str(exc.value)

    def test_duplicate_for_line(self):
        model = "projector P:\n    for A\n    for B\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 3
        assert "duplicate 'for' line" in str(exc.value)

    def test_duplicate_consumes_line(self):
        model = "projector P:\n    consumes A\n    consumes B\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 3
        assert "duplicate 'consumes' line" in str(exc.value)

    def test_projector_body_line_that_is_neither_for_nor_consumes(self):
        model = "projector P:\n    field x: string\n"
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        assert exc.value.line == 2
        assert "expected 'for <Projection>' or 'consumes <Event>'" in str(exc.value)

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
        assert "more than one projection" in str(exc.value)

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
        assert "more than one projector" in str(exc.value)

    def test_projector_missing_for_line(self):
        model = _write_side(
            "\nprojection OrderSummary:\n    field order_id: identifier(key)\n",
            "\nprojector OrderProjector:\n    consumes OrderCreated\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # Reported at the projector header, line 14.
        assert exc.value.line == 14
        assert "needs a 'for" in str(exc.value)

    def test_projector_missing_consumes_line(self):
        model = _write_side(
            "\nprojection OrderSummary:\n    field order_id: identifier(key)\n",
            "\nprojector OrderProjector:\n    for OrderSummary\n",
        )
        with pytest.raises(ModelParseError) as exc:
            parse_model(model)
        # Reported at the projector header, line 14.
        assert exc.value.line == 14
        assert "needs a 'consumes" in str(exc.value)


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
            order_id = String(max_length=None, required=True)
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
    # Every eligible event carries the aggregate's surfaced id. It goes in first so
    # a test that passes its own ``order_id`` overrides it.
    surfaced = {"order_id": {"kind": "standard", "type": "String", "required": True}}
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
                        "fields": {
                            **surfaced,
                            **(
                                event_fields
                                if event_fields is not None
                                else dict(clean)
                            ),
                        },
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
                    "required": True,
                }
            }
        )
        with pytest.raises(ModelEmitError) as exc:
            emit_model(ir, "m.Order")
        assert "choices" in str(exc.value)

    def test_optional_field_raises(self):
        # No ``required`` flag: the grammar has no optional form, so the emitter
        # raises rather than emit the field as required and change its meaning.
        ir = _synthetic_ir(
            event_fields={"note": {"kind": "standard", "type": "String"}}
        )
        with pytest.raises(ModelEmitError) as exc:
            emit_model(ir, "m.Order")
        assert "optional" in str(exc.value)

    def test_hand_set_min_length_raises(self):
        # ``min_length`` is recorded only when an author sets it; the grammar
        # cannot carry it, so dropping it would lose the constraint. Raise instead.
        ir = _synthetic_ir(
            event_fields={
                "code": {
                    "kind": "standard",
                    "type": "String",
                    "min_length": 3,
                    "required": True,
                }
            }
        )
        with pytest.raises(ModelEmitError) as exc:
            emit_model(ir, "m.Order")
        assert "min_length" in str(exc.value)

    def test_explicit_min_length_zero_raises(self):
        # ``min_length=0`` on a required field accepts the empty string. The grammar
        # re-derives the implicit bound of 1, so emitting it would silently forbid
        # what the author allowed.
        ir = _synthetic_ir(
            event_fields={
                "note": {
                    "kind": "standard",
                    "type": "String",
                    "min_length": 0,
                    "required": True,
                }
            }
        )
        with pytest.raises(ModelEmitError) as exc:
            emit_model(ir, "m.Order")
        assert "min_length" in str(exc.value)

    def test_authored_auto_field_raises_rather_than_being_dropped(self):
        # ``IRBuilder`` gives an authored ``Auto`` field IR kind ``auto`` with no
        # ``auto_generated`` marker, the same kind as the injected identity. Only
        # the marker means "derived", so this field has to reach the type check and
        # raise, not be filtered out of the model.
        domain = Domain(name="Ordering", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100, required=True)
            sequence = Auto(increment=True)

        @domain.event(part_of=Order)
        class OrderCreated:
            order_id = String(max_length=None, required=True)
            name = String(max_length=100, required=True)

        @domain.command(part_of=Order)
        class CreateOrder:
            name = String(max_length=100, required=True)

        domain.init(traverse=False)
        ir = domain.to_ir()
        fqn = _cluster_fqn(ir)
        # Guard the premise: the authored field is kind ``auto`` and unmarked.
        sequence = ir["clusters"][fqn]["aggregate"]["fields"]["sequence"]
        assert sequence["kind"] == "auto"
        assert "auto_generated" not in sequence

        with pytest.raises(ModelEmitError) as exc:
            emit_model(ir, fqn)
        assert "sequence" in str(exc.value)

    def test_projection_keyed_on_other_than_the_surfaced_id_raises(self):
        # A projection keyed ``id`` rather than ``order_id`` is emittable field by
        # field, but the text does not read back, so the emitter refuses it instead
        # of returning a model ``parse_model`` rejects.
        projections = {
            "m.Report": {
                "projection": {
                    "name": "OrderSummary",
                    "fields": {
                        "id": {
                            "kind": "identifier",
                            "type": "Identifier",
                            "identifier": True,
                        }
                    },
                },
                "projectors": {
                    "m.OrderProjector": {
                        "name": "OrderProjector",
                        "aggregates": ["m.Order"],
                        "handlers": {"M.OrderCreated.v1": ["on_order_created"]},
                    }
                },
            }
        }
        with pytest.raises(ModelEmitError) as exc:
            emit_model(_synthetic_ir(projections=projections), "m.Order")
        assert "cannot read back" in str(exc.value)

    def test_projected_field_absent_from_the_event_raises(self):
        # Same contract on the other read-side rule: a projected field the event
        # does not source makes the emitted text unparseable, so emit refuses.
        projections = {
            "m.Report": {
                "projection": {
                    "name": "OrderSummary",
                    "fields": {
                        "order_id": {
                            "kind": "identifier",
                            "type": "Identifier",
                            "identifier": True,
                        },
                        "absent": {
                            "kind": "standard",
                            "type": "String",
                            "required": True,
                        },
                    },
                },
                "projectors": {
                    "m.OrderProjector": {
                        "name": "OrderProjector",
                        "aggregates": ["m.Order"],
                        "handlers": {"M.OrderCreated.v1": ["on_order_created"]},
                    }
                },
            }
        }
        ir = _synthetic_ir(
            event_fields={
                "order_id": {"kind": "standard", "type": "String", "required": True},
                "name": {"kind": "standard", "type": "String", "required": True},
            },
            projections=projections,
        )
        with pytest.raises(ModelEmitError) as exc:
            emit_model(ir, "m.Order")
        assert "cannot read back" in str(exc.value)

    def test_non_canonical_participant_name_raises(self):
        # A domain class written ``order_item`` gives the IR that name verbatim, and
        # the parser normalizes a block name to PascalCase, so the emitted text would
        # read back as a differently named aggregate. Refuse instead of renaming.
        ir = _synthetic_ir(
            event_fields={
                "order_item_id": {
                    "kind": "standard",
                    "type": "String",
                    "required": True,
                },
                "name": {"kind": "standard", "type": "String", "required": True},
            }
        )
        ir["clusters"]["m.Order"]["aggregate"]["name"] = "order_item"
        with pytest.raises(ModelEmitError) as exc:
            emit_model(ir, "m.Order")
        assert "reads back as 'OrderItem'" in str(exc.value)

    def test_event_without_the_surfaced_id_raises(self):
        # The guard covers the parser's rules without a second copy of them: an
        # event missing the surfaced id emits text that does not read back.
        ir = _synthetic_ir()
        del ir["clusters"]["m.Order"]["events"]["m.OrderCreated"]["fields"]["order_id"]
        with pytest.raises(ModelEmitError) as exc:
            emit_model(ir, "m.Order")
        assert "cannot read back" in str(exc.value)
        assert "must carry 'order_id'" in str(exc.value)

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

    def test_single_event_multi_method_projector_raises(self):
        # One event, but the projector handles it with two methods: still a
        # multi-handler projector the grammar cannot express.
        projections = {
            "m.Report": {
                "projection": {"name": "OrderSummary", "fields": {}},
                "projectors": {
                    "m.OrderProjector": {
                        "name": "OrderProjector",
                        "aggregates": ["m.Order"],
                        "handlers": {"M.OrderCreated.v1": ["on_created", "on_again"]},
                    }
                },
            }
        }
        with pytest.raises(ModelEmitError):
            emit_model(_synthetic_ir(projections=projections), "m.Order")

    def test_auto_generated_event_is_filtered(self):
        # A cluster carrying an authored event and an auto-generated one emits the
        # authored event only; the auto-generated event is not counted as a second.
        ir = _synthetic_ir()
        ir["clusters"]["m.Order"]["events"]["m.OrderDefaulted"] = {
            "name": "OrderDefaulted",
            "__type__": "M.OrderDefaulted.v1",
            "auto_generated": True,
            "fields": {
                "name": {"kind": "standard", "type": "String", "required": True}
            },
        }
        text = emit_model(ir, "m.Order")
        assert "event OrderCreated:" in text
        assert "OrderDefaulted" not in text

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


# Field-entry keys the grammar carries. The round trip is an inverse over these;
# everything else (``min_length``, ``description``, the injected identity) is
# outside the grammar by ADR-0041.
_GRAMMAR_KEYS = {"kind", "type", "max_length", "identifier", "required"}


def _grammar_visible(entry: dict) -> dict:
    """Reduce an IR field entry to what the grammar carries.

    Keeps only the grammar keys, and drops ``required`` from the projection key
    (it takes the framework identity default, which the parser writes as
    ``identifier`` with no ``required``).
    """
    visible = {k: v for k, v in entry.items() if k in _GRAMMAR_KEYS}
    if visible.get("identifier"):
        visible.pop("required", None)
    return visible


def _grammar_fields(fields: dict) -> dict:
    """The grammar-visible fields of an IR participant, minus the injected id."""
    return {
        name: _grammar_visible(entry)
        for name, entry in fields.items()
        if not (entry.get("auto_generated") or entry.get("kind") == "auto")
    }


@pytest.mark.no_test_domain
class TestConformance:
    def test_order_slice_round_trip(self):
        ir = _build_order_domain().to_ir()
        text = emit_model(ir, _cluster_fqn(ir))
        assert parse_model(text) == ORDER_FRAGMENT

    def test_round_trip_matches_the_source_ir(self):
        # Compare the parsed fragment against the source IR's own field entries,
        # not a hand-written constant, so any emitter loss (a dropped constraint,
        # an optional field coerced to required) reddens this test.
        ir = _build_order_domain().to_ir()
        fqn = _cluster_fqn(ir)
        cluster = ir["clusters"][fqn]
        fragment = parse_model(emit_model(ir, fqn))

        command = next(iter(cluster["commands"].values()))
        event = next(iter(cluster["events"].values()))
        assert fragment["aggregate"]["fields"] == _grammar_fields(
            cluster["aggregate"]["fields"]
        )
        assert fragment["command"]["fields"] == _grammar_fields(command["fields"])
        assert fragment["event"]["fields"] == _grammar_fields(event["fields"])

        projection = next(iter(ir["projections"].values()))["projection"]
        assert fragment["projection"]["fields"] == _grammar_fields(projection["fields"])

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
