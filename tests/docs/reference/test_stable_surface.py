"""Check what docs/reference/stable-surface.md says about field declaration styles.

The page shows the annotation style, ``placed_at: DateTime(required=True)``, as
the documented default. It also says a module that uses
``from __future__ import annotations`` must use the assignment style instead.
"""

from datetime import UTC, datetime

import pytest

from protean.exceptions import ValidationError
from protean.utils.reflection import declared_fields
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

POSTPONED_ASSIGNMENT_STYLE = """
from __future__ import annotations

from protean import Domain
from protean.fields import DateTime

domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    placed_at = DateTime(required=True)
"""


@pytest.fixture
def example():
    module = load_example("reference/stable-surface/001.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


def test_annotation_style_declares_a_required_field(example):
    assert declared_fields(example.Order)["placed_at"].required is True


def test_annotation_style_field_parses_a_datetime(example):
    order = example.Order(placed_at="2026-01-02T03:04:05+00:00")

    assert order.placed_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_annotation_style_field_is_required(example):
    with pytest.raises(ValidationError, match="placed_at.*is required"):
        example.Order()


def test_assignment_style_works_under_postponed_annotations():
    namespace: dict = {"__name__": "postponed_assignment_style"}
    exec(compile(POSTPONED_ASSIGNMENT_STYLE, "postponed.py", "exec"), namespace)
    domain, order_cls = namespace["domain"], namespace["Order"]
    domain.init(traverse=False)

    with domain.domain_context():
        order = order_cls(placed_at="2026-01-02T03:04:05+00:00")
        assert order.placed_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        with pytest.raises(ValidationError, match="placed_at.*is required"):
            order_cls()
