"""Unit tests for the per-element scorer, over hand-authored IRs (no model).

The IRs here are built by :func:`ir_of`, which mirrors the shape
``protean ir show`` emits: an ``elements`` map of category to FQN lists, and a
``clusters`` map of aggregate FQN to its fields. The package prefix is arbitrary
and differs from the gold's on purpose, so these tests also pin the cross-project
class-name matching the scorer uses.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pytest

from tests.eval.scoring import element_signatures, score

pytestmark = pytest.mark.no_test_domain


def ir_of(
    *,
    package: str = "app",
    aggregates: tuple[str, ...] = (),
    commands: tuple[str, ...] = (),
    events: tuple[str, ...] = (),
    command_handlers: tuple[str, ...] = (),
    event_handlers: tuple[str, ...] = (),
    fields: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    """Build an IR dict from class names, in the shape the scorer reads.

    ``fields`` are ``(aggregate class name, field name)`` pairs, grouped under
    their aggregate's cluster. The ``package`` prefix forms the FQNs and is
    deliberately caller-set, so a test can give the "gold" and the "produced" IRs
    different packages and still expect a match on class name.
    """

    def fqns(module: str, names: tuple[str, ...]) -> list[str]:
        return [f"{package}.{module}.{name}" for name in names]

    elements = {
        "AGGREGATE": fqns("aggregate", aggregates),
        "COMMAND": fqns("commands", commands),
        "EVENT": fqns("events", events),
        "COMMAND_HANDLER": fqns("command_handlers", command_handlers),
        "EVENT_HANDLER": fqns("event_handlers", event_handlers),
    }
    by_aggregate: dict[str, dict[str, Any]] = defaultdict(dict)
    for aggregate, field_name in fields:
        by_aggregate[aggregate][field_name] = {"type": "String"}
    clusters = {
        f"{package}.aggregate.{aggregate}": {
            "aggregate": {
                "name": aggregate,
                "fqn": f"{package}.aggregate.{aggregate}",
                "fields": by_aggregate.get(aggregate, {}),
            }
        }
        for aggregate in aggregates
    }
    return {"elements": elements, "clusters": clusters}


# A gold with one of every scored category: an aggregate, two fields on it, a
# command, an event, and a command handler. Six scored elements in all.
GOLD = ir_of(
    package="gold",
    aggregates=("Order",),
    commands=("PlaceOrder",),
    events=("OrderPlaced",),
    command_handlers=("OrderCommandHandler",),
    fields=(("Order", "id"), ("Order", "customer_name")),
)


class TestKnownGood:
    def test_same_structure_scores_one(self) -> None:
        """A produced IR carrying every gold element (same class names, a
        different package) scores 1.0."""
        produced = ir_of(
            package="produced",
            aggregates=("Order",),
            commands=("PlaceOrder",),
            events=("OrderPlaced",),
            command_handlers=("OrderCommandHandler",),
            fields=(("Order", "id"), ("Order", "customer_name")),
        )
        result = score(produced, GOLD)
        assert result.score == 1.0
        assert result.expected == 6
        assert result.missing == ()

    def test_gold_scores_one_against_itself(self) -> None:
        assert score(GOLD, GOLD).score == 1.0


class TestKnownBad:
    @pytest.mark.parametrize(
        ("dropped", "missing_signature"),
        [
            ("aggregate", ("aggregate", "Order")),
            ("command", ("command", "PlaceOrder")),
            ("event", ("event", "OrderPlaced")),
            ("handler", ("handler", "OrderCommandHandler")),
            ("field", ("field", "Order", "customer_name")),
        ],
    )
    def test_dropping_one_element_lowers_the_score_by_a_sixth(
        self, dropped: str, missing_signature: tuple[str, ...]
    ) -> None:
        """Each scored category, dropped in turn, costs exactly one of the six
        gold elements, and the dropped element is named in ``missing``."""
        kwargs: dict[str, Any] = {
            "package": "produced",
            "aggregates": ("Order",),
            "commands": ("PlaceOrder",),
            "events": ("OrderPlaced",),
            "command_handlers": ("OrderCommandHandler",),
            "fields": (("Order", "id"), ("Order", "customer_name")),
        }
        if dropped == "aggregate":
            # Dropping the aggregate also strands its fields, so score against a
            # gold that has no fields to isolate the single-element loss.
            gold = ir_of(
                package="gold",
                aggregates=("Order",),
                commands=("PlaceOrder",),
                events=("OrderPlaced",),
                command_handlers=("OrderCommandHandler",),
            )
            produced = ir_of(
                package="produced",
                commands=("PlaceOrder",),
                events=("OrderPlaced",),
                command_handlers=("OrderCommandHandler",),
            )
            result = score(produced, gold)
            assert result.expected == 4
            assert result.score == pytest.approx(3 / 4)
            assert missing_signature in result.missing
            return
        if dropped == "command":
            kwargs["commands"] = ()
        elif dropped == "event":
            kwargs["events"] = ()
        elif dropped == "handler":
            kwargs["command_handlers"] = ()
        elif dropped == "field":
            kwargs["fields"] = (("Order", "id"),)
        produced = ir_of(**kwargs)
        result = score(produced, GOLD)
        assert result.score == pytest.approx(5 / 6)
        assert missing_signature in result.missing
        assert missing_signature not in result.recovered


class TestEqualWeighting:
    def test_dropping_a_field_and_dropping_an_aggregate_cost_the_same(self) -> None:
        """Every element weighs the same: a missing field lowers the score by
        the same unit as a missing aggregate."""
        gold = ir_of(
            package="gold",
            aggregates=("Order", "Customer"),
            fields=(("Order", "id"), ("Order", "total")),
        )
        # gold: 2 aggregates + 2 fields = 4 scored elements.
        drop_field = ir_of(
            package="p",
            aggregates=("Order", "Customer"),
            fields=(("Order", "id"),),
        )
        drop_aggregate = ir_of(
            package="p",
            aggregates=("Order",),
            fields=(("Order", "id"), ("Order", "total")),
        )
        field_score = score(drop_field, gold)
        aggregate_score = score(drop_aggregate, gold)
        assert field_score.expected == aggregate_score.expected == 4
        assert field_score.score == aggregate_score.score == pytest.approx(3 / 4)


class TestMatchingCrux:
    def test_a_name_shared_across_categories_does_not_cross_match(self) -> None:
        """A produced aggregate named ``Ping`` does not recover a gold command
        named ``Ping``: the category is part of the signature."""
        gold = ir_of(package="gold", aggregates=("Ping",), commands=("Ping",))
        produced = ir_of(package="p", aggregates=("Ping",))
        result = score(produced, gold)
        assert ("aggregate", "Ping") in result.recovered
        assert ("command", "Ping") in result.missing
        assert result.score == pytest.approx(1 / 2)

    def test_a_field_name_is_scoped_to_its_aggregate(self) -> None:
        """The same field name under two aggregates is two signatures; producing
        it under one recovers only that one."""
        gold = ir_of(
            package="gold",
            aggregates=("Order", "Invoice"),
            fields=(("Order", "total"), ("Invoice", "total")),
        )
        produced = ir_of(
            package="p",
            aggregates=("Order", "Invoice"),
            fields=(("Order", "total"),),
        )
        result = score(produced, gold)
        assert ("field", "Order", "total") in result.recovered
        assert ("field", "Invoice", "total") in result.missing

    def test_renaming_the_aggregate_drops_every_field_under_it(self) -> None:
        """Fields key on the aggregate class name, so a produced project that
        renames the aggregate recovers none of its fields."""
        gold = ir_of(
            package="gold",
            aggregates=("Order",),
            fields=(("Order", "id"), ("Order", "total")),
        )
        produced = ir_of(
            package="p",
            aggregates=("Purchase",),
            fields=(("Purchase", "id"), ("Purchase", "total")),
        )
        result = score(produced, gold)
        assert result.recovered == ()
        assert ("field", "Order", "id") in result.missing
        assert ("field", "Order", "total") in result.missing
        assert result.score == 0.0

    def test_a_command_handler_and_event_handler_share_the_handler_category(
        self,
    ) -> None:
        """Handlers are one category: an event handler named ``H`` recovers a
        gold command handler named ``H``."""
        gold = ir_of(package="gold", command_handlers=("H",))
        produced = ir_of(package="p", event_handlers=("H",))
        assert score(produced, gold).score == 1.0


class TestDegenerateInputs:
    def test_empty_produced_ir_scores_zero_without_raising(self) -> None:
        """An un-loadable produced project yields ``{}`` from build_ir; the
        scorer reports 0.0 with everything missing rather than raising."""
        result = score({}, GOLD)
        assert result.score == 0.0
        assert result.recovered == ()
        assert len(result.missing) == 6

    def test_empty_gold_does_not_divide_by_zero(self) -> None:
        """The empty-input guard: a gold with no scored element scores 0.0 with
        an expected count of zero, no ZeroDivisionError."""
        result = score(GOLD, {})
        assert result.score == 0.0
        assert result.expected == 0

    def test_signatures_of_empty_ir_are_empty(self) -> None:
        assert element_signatures({}) == set()
        assert element_signatures({"elements": {}, "clusters": {}}) == set()

    def test_a_cluster_aggregate_with_no_name_or_fqn_contributes_no_fields(
        self,
    ) -> None:
        """A malformed cluster whose aggregate has neither ``name`` nor ``fqn``
        is skipped, so its fields do not key under the empty string and collide
        with another such aggregate's."""
        ir = {
            "elements": {},
            "clusters": {
                "a": {"aggregate": {"fields": {"total": {"type": "Integer"}}}},
                "b": {"aggregate": {"fields": {"total": {"type": "Integer"}}}},
            },
        }
        assert element_signatures(ir) == set()
