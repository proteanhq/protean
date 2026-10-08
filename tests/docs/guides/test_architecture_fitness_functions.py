"""The examples on the architecture fitness functions guide behave as the page says."""

import pytest

from protean import Domain, Index
from protean.fields import String, Text
from protean.ir.builder import IRBuilder
from protean.utils import fqn
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _codes_for(ir: dict, code: str) -> list[dict]:
    return [d for d in ir["diagnostics"] if d["code"] == code]


def test_suppress_checks_silences_the_unbounded_index_on_note():
    example = load_example("guides/architecture-fitness-functions/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        ir = IRBuilder(example.domain).build()

    assert _codes_for(ir, "UNBOUNDED_INDEXED_STRING") == []


def test_the_same_note_without_suppress_checks_is_flagged():
    domain = Domain(name="UnsuppressedNotes")

    @domain.aggregate(indexes=[Index("body")])
    class Note:
        body = Text()

    domain.init(traverse=False)
    with domain.domain_context():
        ir = IRBuilder(domain).build()

    [finding] = _codes_for(ir, "UNBOUNDED_INDEXED_STRING")
    assert finding["element"] == fqn(Note)
    assert finding["field"] == "body"
    assert finding["level"] == "warning"


def _ir_with_rule(rule_path: str, aggregate_name: str) -> tuple[dict, type]:
    domain = Domain(name="Naming", config={"lint": {"rules": [rule_path]}})
    aggregate = type(aggregate_name, (), {"name": String(max_length=50)})
    aggregate = domain.aggregate(aggregate)
    domain.init(traverse=False)
    with domain.domain_context():
        return IRBuilder(domain).build(), aggregate


def test_check_naming_passes_a_pascal_case_aggregate():
    example = load_example("guides/architecture-fitness-functions/002.py")

    ir, _ = _ir_with_rule(f"{example.__name__}.check_naming", "OrderLine")

    assert example.check_naming(ir) == []
    assert _codes_for(ir, "AGGREGATE_NOT_PASCAL_CASE") == []


@pytest.mark.parametrize("name", ["order_line", "Order_Line", "orderLine"])
def test_check_naming_flags_an_aggregate_that_is_not_pascal_case(name):
    example = load_example("guides/architecture-fitness-functions/002.py")

    ir, aggregate = _ir_with_rule(f"{example.__name__}.check_naming", name)

    [finding] = _codes_for(ir, "AGGREGATE_NOT_PASCAL_CASE")
    assert finding["element"] == fqn(aggregate)
    assert finding["level"] == "info"
    assert finding["message"] == f"{name} should be PascalCase"
    # A custom finding without a category gets the ``custom`` category.
    assert finding["category"] == "custom"
