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

from tests.eval.scoring import (
    AmbiguousGoldError,
    element_signatures,
    score,
    score_boundary,
)

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


class TestAmbiguousGold:
    """The gold must be scorable by class name alone, or the score is wrong."""

    @staticmethod
    def _two_contexts_ir() -> dict[str, Any]:
        """An IR with a ``CreateOrder`` command and an ``Order`` aggregate under
        each of two bounded contexts: four elements, two class names."""
        return {
            "elements": {
                "AGGREGATE": ["sales.order.Order", "billing.order.Order"],
                "COMMAND": [
                    "sales.commands.CreateOrder",
                    "billing.commands.CreateOrder",
                ],
            },
            "clusters": {},
        }

    def test_two_gold_elements_sharing_a_class_name_are_rejected(self) -> None:
        """Two commands named ``CreateOrder`` in different packages reduce to one
        signature. Scoring against that gold would count one element where the
        gold carries two, and let a single produced command recover both, so the
        scorer refuses the gold instead of reporting the number."""
        produced = ir_of(package="p", aggregates=("Order",), commands=("CreateOrder",))
        with pytest.raises(AmbiguousGoldError) as excinfo:
            score(produced, self._two_contexts_ir())
        message = str(excinfo.value)
        assert "command/CreateOrder" in message
        assert "sales.commands.CreateOrder" in message
        assert "billing.commands.CreateOrder" in message
        # Every colliding signature is named, not just the first one found.
        assert "aggregate/Order" in message

    def test_two_gold_aggregates_sharing_a_name_collide_on_their_fields_too(
        self,
    ) -> None:
        """Fields key on the aggregate's class name, so two aggregates named
        ``Order`` also merge their fields. The rejection names the field."""
        gold = {
            "elements": {},
            "clusters": {
                "sales.order.Order": {
                    "aggregate": {
                        "name": "Order",
                        "fqn": "sales.order.Order",
                        "fields": {"total": {"type": "Integer"}},
                    }
                },
                "billing.order.Order": {
                    "aggregate": {
                        "name": "Order",
                        "fqn": "billing.order.Order",
                        "fields": {"total": {"type": "Integer"}},
                    }
                },
            },
        }
        with pytest.raises(AmbiguousGoldError, match="field/Order/total"):
            score(ir_of(package="p"), gold)

    def test_the_same_collision_in_the_produced_ir_is_not_rejected(self) -> None:
        """Only the gold sets the denominator. A produced project carrying two
        ``CreateOrder`` commands still recovers the one the gold asks for."""
        gold = ir_of(package="gold", aggregates=("Order",), commands=("CreateOrder",))
        result = score(self._two_contexts_ir(), gold)
        assert result.expected == 2
        assert result.score == 1.0

    def test_a_repeated_fqn_is_one_element_not_a_collision(self) -> None:
        """The same FQN listed twice is one element, so it is not ambiguous."""
        gold = {
            "elements": {"COMMAND": ["app.commands.X", "app.commands.X"]},
            "clusters": {},
        }
        assert score(gold, gold).expected == 1


def boundary_ir(*, package: str = "app", clusters: dict[str, dict[str, Any]]) -> dict:
    """Build an IR carrying per-cluster placement sections and a domain package.

    ``clusters`` maps an aggregate class name to a spec dict with an optional
    ``context`` (the module segment, defaulting to the aggregate name lowercased)
    and optional ``commands``/``events``/``command_handlers``/``event_handlers``/
    ``entities`` tuples of class names. Each element lands both in its aggregate's
    cluster (what the boundary scorer reads) and in the flat ``elements`` map (what
    the base rubric reads), so a fixture can be scored both ways. The ``package``
    forms the FQNs and the domain name, so a gold and a produced IR can use
    different packages and still match on the class name and context segment.
    """
    sections = {
        "commands": "COMMAND",
        "events": "EVENT",
        "command_handlers": "COMMAND_HANDLER",
        "event_handlers": "EVENT_HANDLER",
        "entities": "ENTITY",
    }
    elements: dict[str, list[str]] = defaultdict(list)
    ir_clusters: dict[str, Any] = {}
    for aggregate, spec in clusters.items():
        context = spec.get("context", aggregate.lower())
        agg_fqn = f"{package}.{context}.aggregate.{aggregate}"
        elements["AGGREGATE"].append(agg_fqn)
        cluster: dict[str, Any] = {
            "aggregate": {
                "name": aggregate,
                "fqn": agg_fqn,
                "module": f"{package}.{context}.aggregate",
                "fields": {},
            }
        }
        for section, element_key in sections.items():
            members: dict[str, Any] = {}
            for name in spec.get(section, ()):
                fqn = f"{package}.{context}.{section}.{name}"
                members[fqn] = {
                    "name": name,
                    "module": f"{package}.{context}.{section}",
                }
                elements[element_key].append(fqn)
            cluster[section] = members
        ir_clusters[agg_fqn] = cluster
    return {
        "domain": {"normalized_name": package, "name": package},
        "elements": dict(elements),
        "clusters": ir_clusters,
    }


# A two-aggregate gold: an Order and a Payment, each owning its own create
# command, created event, and command handler. Six per-cluster placement
# elements in all.
BOUNDARY_GOLD = boundary_ir(
    package="gold",
    clusters={
        "Order": {
            "commands": ("CreateOrder",),
            "events": ("OrderCreated",),
            "command_handlers": ("OrderCommandHandler",),
        },
        "Payment": {
            "commands": ("CreatePayment",),
            "events": ("PaymentCreated",),
            "command_handlers": ("PaymentCommandHandler",),
        },
    },
)


class TestPlacement:
    def test_gold_places_every_element_against_itself(self) -> None:
        result = score_boundary(BOUNDARY_GOLD, BOUNDARY_GOLD)
        assert result.placement == 1.0
        assert result.placement_expected == 6
        assert result.misplaced == ()

    def test_the_same_names_under_the_right_aggregate_place_correctly(self) -> None:
        """A produced project with the gold's element names, each under the
        correct aggregate but in a different package, places 1.0."""
        produced = boundary_ir(
            package="produced",
            clusters={
                "Order": {
                    "commands": ("CreateOrder",),
                    "events": ("OrderCreated",),
                    "command_handlers": ("OrderCommandHandler",),
                },
                "Payment": {
                    "commands": ("CreatePayment",),
                    "events": ("PaymentCreated",),
                    "command_handlers": ("PaymentCommandHandler",),
                },
            },
        )
        assert score_boundary(produced, BOUNDARY_GOLD).placement == 1.0

    def test_the_same_names_under_the_wrong_aggregate_place_zero(self) -> None:
        """The discriminator (AC2): swap the two aggregates' slices. Every gold
        element name is still present, so the base rubric scores full recovery,
        but each sits under the wrong aggregate, so placement collapses to 0."""
        planted_wrong = boundary_ir(
            package="produced",
            clusters={
                "Order": {
                    "commands": ("CreatePayment",),
                    "events": ("PaymentCreated",),
                    "command_handlers": ("PaymentCommandHandler",),
                },
                "Payment": {
                    "commands": ("CreateOrder",),
                    "events": ("OrderCreated",),
                    "command_handlers": ("OrderCommandHandler",),
                },
            },
        )
        # The base rubric cannot see the swap: all eight names (two aggregates,
        # two commands, two events, two handlers) are present.
        assert score(planted_wrong, BOUNDARY_GOLD).score == 1.0
        wrong = score_boundary(planted_wrong, BOUNDARY_GOLD)
        right = score_boundary(BOUNDARY_GOLD, BOUNDARY_GOLD)
        assert wrong.placement == 0.0
        assert wrong.placement_expected == 6
        # The whole point of the layer: the wrong decomposition is separated from
        # the right one by the placement number, where the base score is blind.
        assert right.placement > wrong.placement
        assert ("command", "CreateOrder") in wrong.misplaced

    def test_placement_denominator_is_what_was_recovered(self) -> None:
        """Placement is conditional on recovery: a produced project that recovers
        only one element, correctly placed, scores 1.0 over that one element."""
        produced = boundary_ir(
            package="produced", clusters={"Order": {"commands": ("CreateOrder",)}}
        )
        result = score_boundary(produced, BOUNDARY_GOLD)
        assert result.placement == 1.0
        assert result.placement_expected == 1
        assert result.placed == (("command", "CreateOrder"),)

    def test_entities_count_toward_placement(self) -> None:
        """An entity under the wrong aggregate is a misplacement, so the boundary
        signal covers entities and not only the command/event/handler slice."""
        gold = boundary_ir(
            package="gold",
            clusters={"Order": {"entities": ("LineItem",)}, "Payment": {}},
        )
        misplaced = boundary_ir(
            package="produced",
            clusters={"Order": {}, "Payment": {"entities": ("LineItem",)}},
        )
        result = score_boundary(misplaced, gold)
        assert result.placement == 0.0
        assert ("entity", "LineItem") in result.misplaced


class TestContext:
    def test_matching_contexts_across_packages_score_one(self) -> None:
        """Context matches on the package-relative segment, so a gold under
        ``sales`` and a produced project under ``app`` still match on ``order``
        and ``payment``."""
        gold = boundary_ir(
            package="sales",
            clusters={
                "Order": {"context": "order"},
                "Payment": {"context": "payment"},
            },
        )
        produced = boundary_ir(
            package="app",
            clusters={
                "Order": {"context": "order"},
                "Payment": {"context": "payment"},
            },
        )
        result = score_boundary(produced, gold)
        assert result.context == 1.0
        assert result.context_expected == 2
        assert set(result.contexts_matched) == {"Order", "Payment"}

    def test_an_aggregate_in_the_wrong_context_scores_low(self) -> None:
        """One aggregate under the wrong context module drops the context score
        and is named in the mismatch breakdown."""
        gold = boundary_ir(
            package="sales",
            clusters={
                "Order": {"context": "order"},
                "Payment": {"context": "payment"},
            },
        )
        produced = boundary_ir(
            package="app",
            clusters={
                "Order": {"context": "payment"},  # wrong context
                "Payment": {"context": "payment"},
            },
        )
        result = score_boundary(produced, gold)
        assert result.context == pytest.approx(1 / 2)
        assert result.contexts_mismatched == ("Order",)
        assert result.contexts_matched == ("Payment",)

    def test_a_single_context_task_is_not_penalized(self) -> None:
        """The negative test for the new branch: a single-aggregate (flat-spec)
        task's one aggregate matches its own context, so context stays 1.0 and
        does not spuriously fall below 1."""
        gold = boundary_ir(package="gold", clusters={"Order": {"context": "order"}})
        produced = boundary_ir(package="app", clusters={"Order": {"context": "order"}})
        result = score_boundary(produced, gold)
        assert result.context == 1.0
        assert result.context_expected == 1


class TestBoundaryDegenerateInputs:
    def test_empty_produced_scores_zero_without_raising(self) -> None:
        result = score_boundary({}, BOUNDARY_GOLD)
        assert result.placement == 0.0
        assert result.context == 0.0
        assert result.placement_expected == 0
        assert result.context_expected == 0

    def test_empty_gold_does_not_divide_by_zero(self) -> None:
        result = score_boundary(BOUNDARY_GOLD, {})
        assert result.placement == 0.0
        assert result.context == 0.0

    def test_a_cluster_aggregate_with_no_name_contributes_no_placement(self) -> None:
        """A malformed cluster whose aggregate has neither name nor fqn is
        skipped, so its elements are not keyed under an empty owner."""
        gold = {
            "domain": {"normalized_name": "gold"},
            "elements": {},
            "clusters": {
                "a": {
                    "aggregate": {"fields": {}},
                    "commands": {"a.commands.X": {"name": "X"}},
                },
            },
        }
        produced = boundary_ir(package="p", clusters={"Order": {"commands": ("X",)}})
        result = score_boundary(produced, gold)
        assert result.placement == 0.0
        assert result.placement_expected == 0


class TestBoundaryAmbiguousGold:
    def test_a_command_name_repeated_across_aggregates_is_rejected(self) -> None:
        """A gold with the same command name under two aggregates has no defined
        correct placement, so scoring refuses it (the base flat-elements guard)."""
        gold = boundary_ir(
            package="gold",
            clusters={
                "Order": {"commands": ("Create",)},
                "Payment": {"commands": ("Create",)},
            },
        )
        with pytest.raises(AmbiguousGoldError, match="Create"):
            score_boundary(boundary_ir(package="p", clusters={"Order": {}}), gold)

    def test_an_entity_name_repeated_across_aggregates_is_rejected(self) -> None:
        """Entities are not in the flat rubric, so the placement guard is what
        rejects an entity name owned by two aggregates in the gold."""
        gold = boundary_ir(
            package="gold",
            clusters={
                "Order": {"entities": ("LineItem",)},
                "Payment": {"entities": ("LineItem",)},
            },
        )
        with pytest.raises(AmbiguousGoldError, match="entity/LineItem"):
            score_boundary(boundary_ir(package="p", clusters={"Order": {}}), gold)
