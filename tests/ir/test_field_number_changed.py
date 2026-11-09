"""``classify_changes()`` reports an event whose Protobuf field numbers move.

The Protobuf generator numbers fields 1..N in sorted name order. Within one
``__version__``, an event change that gives a kept field a different number is
a breaking ``field_number_changed``. The ShopStream ``PointsEarned`` event is
the worked case: renaming ``amount`` to ``points`` moves four field numbers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from protean import Domain
from protean.cli import app
from protean.cli.hooks import _check_compat_single
from protean.fields import Identifier, Integer, String
from protean.ir.builder import IRBuilder
from protean.ir.config import CompatConfig
from protean.ir.diff import (
    _AVRO_CHANGE_SAFETY,
    CompatibilityReport,
    breaking_change_messages,
    classify_changes,
    diff_ir,
)
from protean.ir.generators.protobuf import field_numbers, generate_proto_schema
from tests.ir.support.git_repo import commit_ir
from tests.ir.test_compatibility import (
    _make_cluster,
    _make_command,
    _make_entity,
    _make_event,
    _make_projection_group,
    _minimal_ir,
)

pytestmark = pytest.mark.no_test_domain

EVENT_FQN = "app.PointsEarned"
FIX_TEXT = (
    "Bump `__version__` and register an upcaster for the old version, "
    "which may return the payload unchanged"
)

runner = CliRunner()


def _std(**extra: object) -> dict:
    return {"kind": "standard", "type": "String", **extra}


# The ShopStream ``PointsEarned`` fields. Sorted, they are numbered:
# account_id 1, amount 2, balance_after 3, customer_id 4, occurred_at 5,
# reason 6.
_POINTS_EARNED = {
    "account_id": _std(identifier=True),
    "amount": _std(type="Integer", required=True),
    "balance_after": _std(type="Integer", required=True),
    "customer_id": _std(required=True),
    "occurred_at": _std(type="DateTime"),
    "reason": _std(),
}


def _renamed_fields() -> dict:
    """``PointsEarned`` with ``amount`` renamed to ``points``.

    Sorted: account_id 1, balance_after 2, customer_id 3, occurred_at 4,
    points 5, reason 6.
    """
    fields = {k: v for k, v in _POINTS_EARNED.items() if k != "amount"}
    fields["points"] = _std(type="Integer", required=True, renamed_from=["amount"])
    return fields


def _event_ir(fields: dict, version: object = 1, upcasters: dict | None = None):
    event = _make_event(
        "PointsEarned",
        EVENT_FQN,
        fields=fields,
        __version__=version,
        __type__=f"Test.PointsEarned.v{version}",
    )
    extra = {"upcasters": upcasters} if upcasters else {}
    return _minimal_ir(
        clusters={"app.Order": _make_cluster("Order", events={EVENT_FQN: event})},
        **extra,
    )


def _run(left: dict, right: dict) -> CompatibilityReport:
    return classify_changes(diff_ir(left, right), left, right)


def _number_changes(report: CompatibilityReport) -> list:
    return [
        c
        for c in report.breaking_changes + report.safe_changes
        if c.change_type == "field_number_changed"
    ]


class TestRenameWithinOneVersion:
    def test_the_rename_is_one_breaking_change_naming_each_moved_field(self):
        report = _run(_event_ir(_POINTS_EARNED), _event_ir(_renamed_fields()))

        changes = _number_changes(report)
        assert len(changes) == 1
        change = changes[0]
        assert change in report.breaking_changes
        assert change.severity == "breaking"
        assert change.element_fqn == EVENT_FQN
        assert change.field_name is None
        assert change.message == (
            "Protobuf field numbers changed in event 'app.PointsEarned' within "
            "version 1: balance_after 3 -> 2, customer_id 4 -> 3, "
            "occurred_at 5 -> 4, points (from amount) 2 -> 5. " + FIX_TEXT
        )

    def test_fields_that_keep_their_number_are_not_named(self):
        report = _run(_event_ir(_POINTS_EARNED), _event_ir(_renamed_fields()))

        message = _number_changes(report)[0].message
        assert "account_id" not in message
        assert "reason" not in message

    def test_the_rename_itself_is_still_reported_safe(self):
        report = _run(_event_ir(_POINTS_EARNED), _event_ir(_renamed_fields()))

        assert [c.change_type for c in report.safe_changes] == ["field_renamed"]

    def test_a_rename_that_keeps_every_number_is_safe(self):
        # ``amount`` -> ``amount_total`` sorts into the same place.
        fields = {k: v for k, v in _POINTS_EARNED.items() if k != "amount"}
        fields["amount_total"] = _std(
            type="Integer", required=True, renamed_from=["amount"]
        )

        report = _run(_event_ir(_POINTS_EARNED), _event_ir(fields))

        assert _number_changes(report) == []
        assert report.is_breaking is False

    def test_the_text_output_prints_the_change_once(self):
        left, right = _event_ir(_POINTS_EARNED), _event_ir(_renamed_fields())
        result = diff_ir(left, right)

        messages = breaking_change_messages(result, _run(left, right))

        number_lines = [m for m in messages if "Protobuf field numbers" in m]
        assert len(number_lines) == 1


class TestVersionBump:
    def test_a_bumped_version_reports_no_number_change(self):
        report = _run(
            _event_ir(_POINTS_EARNED, version=1),
            _event_ir(_renamed_fields(), version=2),
        )

        assert _number_changes(report) == []

    def test_a_bump_with_an_upcaster_leaves_nothing_breaking(self):
        upcasters = {
            "PointsEarned": [{"from_version": 1, "to_version": 2, "fqn": "x.Up"}]
        }
        report = _run(
            _event_ir(_POINTS_EARNED, version=1),
            _event_ir(_renamed_fields(), version=2, upcasters=upcasters),
        )

        assert [c for c in report.breaking_changes if c.element_fqn == EVENT_FQN] == []
        assert _number_changes(report) == []

    @pytest.mark.parametrize(
        ("left_v", "right_v"), [(None, 1), (1, None), (None, None)]
    )
    def test_a_missing_version_on_either_side_reports_nothing(self, left_v, right_v):
        left = _event_ir(_POINTS_EARNED, version=left_v)
        right = _event_ir(_renamed_fields(), version=right_v)
        for ir, v in ((left, left_v), (right, right_v)):
            if v is None:
                del ir["clusters"]["app.Order"]["events"][EVENT_FQN]["__version__"]

        assert _number_changes(_run(left, right)) == []


class TestAddedField:
    def test_an_optional_field_that_sorts_last_is_safe(self):
        fields = {**_POINTS_EARNED, "zzz_note": _std()}

        report = _run(_event_ir(_POINTS_EARNED), _event_ir(fields))

        assert _number_changes(report) == []
        assert report.is_breaking is False

    def test_an_optional_field_that_sorts_first_moves_every_field(self):
        fields = {**_POINTS_EARNED, "aaa_note": _std()}

        report = _run(_event_ir(_POINTS_EARNED), _event_ir(fields))

        changes = _number_changes(report)
        assert len(changes) == 1
        assert changes[0] in report.breaking_changes
        assert changes[0].message == (
            "Protobuf field numbers changed in event 'app.PointsEarned' within "
            "version 1: account_id 1 -> 2, amount 2 -> 3, balance_after 3 -> 4, "
            "customer_id 4 -> 5, occurred_at 5 -> 6, reason 6 -> 7. " + FIX_TEXT
        )


class TestRemovedField:
    def test_removing_a_middle_field_names_only_the_later_fields(self):
        fields = {k: v for k, v in _POINTS_EARNED.items() if k != "customer_id"}

        report = _run(_event_ir(_POINTS_EARNED), _event_ir(fields))

        changes = _number_changes(report)
        assert len(changes) == 1
        assert changes[0].message == (
            "Protobuf field numbers changed in event 'app.PointsEarned' within "
            "version 1: occurred_at 5 -> 4, reason 6 -> 5. " + FIX_TEXT
        )
        removed = [
            c for c in report.breaking_changes if c.change_type == "field_removed"
        ]
        assert [c.field_name for c in removed] == ["customer_id"]

    def test_removing_the_last_field_moves_nothing(self):
        fields = {k: v for k, v in _POINTS_EARNED.items() if k != "reason"}

        report = _run(_event_ir(_POINTS_EARNED), _event_ir(fields))

        assert _number_changes(report) == []
        assert [c.change_type for c in report.breaking_changes] == ["field_removed"]


def _cluster_ir(**cluster_kwargs: Any) -> dict:
    return _minimal_ir(clusters={"app.Order": _make_cluster("Order", **cluster_kwargs)})


class TestOtherElementsAreNotChecked:
    """Only events are checked; the same rename elsewhere reports no move."""

    def test_aggregate(self):
        report = _run(
            _cluster_ir(fields=_POINTS_EARNED), _cluster_ir(fields=_renamed_fields())
        )
        assert _number_changes(report) == []
        assert [c.change_type for c in report.safe_changes] == ["field_renamed"]

    def test_entity(self):
        def ir(fields):
            return _cluster_ir(
                entities={"app.Line": _make_entity("Line", "app.Line", fields)}
            )

        report = _run(ir(_POINTS_EARNED), ir(_renamed_fields()))
        assert _number_changes(report) == []
        assert [c.change_type for c in report.safe_changes] == ["field_renamed"]

    def test_value_object(self):
        def ir(fields):
            vo = {
                "element_type": "VALUE_OBJECT",
                "fields": fields,
                "fqn": "app.Money",
                "module": "app",
                "name": "Money",
                "part_of": "app.Order",
            }
            return _cluster_ir(value_objects={"app.Money": vo})

        report = _run(ir(_POINTS_EARNED), ir(_renamed_fields()))
        assert _number_changes(report) == []
        assert [c.change_type for c in report.safe_changes] == ["field_renamed"]

    def test_command(self):
        def ir(fields):
            return _cluster_ir(
                commands={"app.Earn": _make_command("Earn", "app.Earn", fields)}
            )

        report = _run(ir(_POINTS_EARNED), ir(_renamed_fields()))
        assert _number_changes(report) == []
        assert [c.change_type for c in report.safe_changes] == ["field_renamed"]

    def test_projection(self):
        def ir(fields):
            return _minimal_ir(
                projections={
                    "app.Balance": _make_projection_group("Balance", fields=fields)
                }
            )

        report = _run(ir(_POINTS_EARNED), ir(_renamed_fields()))
        assert _number_changes(report) == []
        assert [c.change_type for c in report.safe_changes] == ["field_renamed"]


class TestEventOnOneSideOnly:
    def test_an_added_event_reports_no_number_change(self):
        report = _run(_minimal_ir(), _event_ir(_POINTS_EARNED))
        assert [c.change_type for c in report.safe_changes] == ["element_added"]
        assert _number_changes(report) == []

    def test_a_removed_event_reports_no_number_change(self):
        report = _run(_event_ir(_POINTS_EARNED), _minimal_ir())
        assert [c.change_type for c in report.breaking_changes] == ["element_removed"]
        assert _number_changes(report) == []


class TestRenameMatching:
    def test_a_renamed_from_naming_a_kept_field_is_not_a_rename(self):
        # ``amount`` stays, so ``aaa_amount`` is a plain addition that moves
        # every field; ``amount`` is matched to itself, not to ``aaa_amount``.
        fields = {
            **_POINTS_EARNED,
            "aaa_amount": _std(type="Integer", renamed_from=["amount"]),
        }

        report = _run(_event_ir(_POINTS_EARNED), _event_ir(fields))

        message = _number_changes(report)[0].message
        assert "amount 2 -> 3" in message
        assert "from amount" not in message

    def test_an_old_field_claimed_twice_is_matched_once(self):
        fields = {k: v for k, v in _POINTS_EARNED.items() if k != "amount"}
        fields["points"] = _std(type="Integer", renamed_from=["amount"])
        fields["score"] = _std(type="Integer", renamed_from=["amount"])

        report = _run(_event_ir(_POINTS_EARNED), _event_ir(fields))

        message = _number_changes(report)[0].message
        assert message.count("(from amount)") == 1

    @pytest.mark.parametrize("aliases", [["amount", "x"], ["x", "amount"]])
    def test_every_old_field_a_rename_replaces_is_checked(self, aliases):
        # ``points`` replaces ``amount`` (number 1) and ``x`` (number 3) and
        # takes number 3, so ``x`` keeps its number and ``amount`` moves,
        # whichever order the aliases are listed in.
        left_fields = {"amount": _std(), "b": _std(), "x": _std()}
        right_fields = {
            "a0": _std(),
            "b": _std(),
            "points": _std(renamed_from=aliases),
        }

        report = _run(_event_ir(left_fields), _event_ir(right_fields))

        assert _number_changes(report)[0].message == (
            "Protobuf field numbers changed in event 'app.PointsEarned' within "
            "version 1: points (from amount) 1 -> 3. " + FIX_TEXT
        )

    def test_a_kept_field_carrying_renamed_from_is_matched_by_name(self):
        # ``reason`` stays and names the removed ``customer_id`` as an old
        # name; only the name match counts for ``reason``.
        fields = {k: v for k, v in _POINTS_EARNED.items() if k != "customer_id"}
        fields["reason"] = _std(renamed_from=["customer_id"])

        report = _run(_event_ir(_POINTS_EARNED), _event_ir(fields))

        assert _number_changes(report)[0].message == (
            "Protobuf field numbers changed in event 'app.PointsEarned' within "
            "version 1: occurred_at 5 -> 4, reason 6 -> 5. " + FIX_TEXT
        )


class TestGeneratedEventsAreNotChecked:
    """Nobody can bump the version of an event the framework defines."""

    @pytest.mark.parametrize("flag", ["is_fact_event", "auto_generated"])
    def test_a_flagged_event_reports_no_number_change(self, flag):
        left = _event_ir(_POINTS_EARNED)
        right = _event_ir(_renamed_fields())
        for ir in (left, right):
            ir["clusters"]["app.Order"]["events"][EVENT_FQN][flag] = True

        assert _number_changes(_run(left, right)) == []

    def test_a_fact_event_from_a_real_domain_reports_no_number_change(self):
        def build(**fields: Any) -> dict[str, Any]:
            domain = Domain(name="Bank")
            domain.aggregate(
                type("Account", (), {"__module__": "bank", **fields}),
                fact_events=True,
            )
            domain.init(traverse=False)
            return IRBuilder(domain).build()

        left = build(name=String())
        right = build(aaa=String(), name=String())

        events = [
            e
            for cluster in right["clusters"].values()
            for e in cluster["events"].values()
        ]
        assert [e["is_fact_event"] for e in events] == [True]
        assert _number_changes(_run(left, right)) == []


class TestAvroSafety:
    def test_the_change_type_is_neutral_for_avro(self):
        assert _AVRO_CHANGE_SAFETY["field_number_changed"] == (True, True)

    def test_the_event_verdict_ignores_the_number_change(self):
        report = _run(_event_ir(_POINTS_EARNED), _event_ir(_renamed_fields()))

        # ``field_renamed`` is forward-unsafe because ``amount`` was required;
        # the number change adds no direction break of its own.
        assert report.avro_verdicts_by_element()[EVENT_FQN] == "BACKWARD"
        assert [c.change_type for _, c in report.avro_direction_breaks()] == [
            "field_renamed"
        ]


class TestGeneratorAndCheckShareTheNumbering:
    def test_the_generated_numbers_match_the_helper(self):
        element = {
            "element_type": "EVENT",
            "fqn": EVENT_FQN,
            "name": "PointsEarned",
            "module": "app",
            "fields": _renamed_fields(),
        }

        proto = generate_proto_schema(element)

        written = {}
        for line in proto.splitlines():
            if line.startswith("  ") and " = " in line:
                left, number = line.strip().rstrip(";").split(" = ")
                written[left.split()[-1]] = int(number)
        assert written == field_numbers(_renamed_fields())
        assert written == {
            "account_id": 1,
            "balance_after": 2,
            "customer_id": 3,
            "occurred_at": 4,
            "points": 5,
            "reason": 6,
        }


# ------------------------------------------------------------------
# Command line: `protean ir diff` and the `protean-check-compat` hook
# ------------------------------------------------------------------


def _build(**fields: Any) -> dict[str, Any]:
    """The IR of a ``Shop`` domain with a version-1 ``Placed`` event."""
    domain = Domain(name="Shop")
    order = domain.aggregate(
        type("Order", (), {"__module__": "shop", "name": String()})
    )
    placed = type("Placed", (), {"__module__": "shop", **fields})
    domain.event(placed, part_of=order, version=1)
    domain.init(traverse=False)
    return IRBuilder(domain).build()


def _write(tmp_path: Path, name: str, ir: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(ir), encoding="utf-8")
    return str(path)


class TestIrDiffJson:
    def test_the_json_lists_the_change_and_exits_1(self, tmp_path):
        left = _build(order_id=Identifier(), qty=Integer())
        right = _build(order_id=Identifier(), qty=Integer(), aaa=String())

        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "-l",
                _write(tmp_path, "left.json", left),
                "-r",
                _write(tmp_path, "right.json", right),
                "-f",
                "json",
            ],
        )

        assert result.exit_code == 1
        breaks = json.loads(result.output)["compatibility"]["breaking_changes"]
        moved = [b for b in breaks if b["change_type"] == "field_number_changed"]
        assert len(moved) == 1
        assert moved[0]["severity"] == "breaking"
        assert moved[0]["element_fqn"] == "shop.Placed"


class TestIrDiffRename:
    def test_a_renamed_from_rename_exits_1_and_names_the_rename(self, tmp_path):
        left = _build(amount=Integer(), customer_id=Identifier(), reason=String())
        right = _build(
            customer_id=Identifier(),
            points=Integer(renamed_from=["amount"]),
            reason=String(),
        )
        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "-l",
                _write(tmp_path, "left.json", left),
                "-r",
                _write(tmp_path, "right.json", right),
            ],
        )

        assert result.exit_code == 1
        output = " ".join(result.output.split())
        assert (
            "Protobuf field numbers changed in event 'shop.Placed' within "
            "version 1: customer_id 2 -> 1, points (from amount) 1 -> 2." in output
        )


_SHOP_SOURCE = """
from protean import Domain
from protean.fields import Identifier, Integer, String

domain = Domain(name="Shop")


@domain.aggregate
class Order:
    name = String()


@domain.event(part_of=Order, version=1)
class Placed:
    aaa = String()
    order_id = Identifier()
    qty = Integer()
"""


class TestHook:
    @pytest.fixture(autouse=True)
    def _repo(self, tmp_path, monkeypatch, isolated_git):
        # HEAD holds Placed without ``aaa``; shop.py adds it, sorting first.
        commit_ir(tmp_path, _build(order_id=Identifier(), qty=Integer()))
        (tmp_path / "shop.py").write_text(_SHOP_SOURCE, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.delitem(sys.modules, "shop", raising=False)
        yield
        sys.modules.pop("shop", None)

    def test_strict_blocks_and_prints_the_change(self, capsys):
        ok = _check_compat_single(
            "shop.py", Path(".protean"), base="HEAD", config=CompatConfig()
        )

        assert ok is False
        err = " ".join(capsys.readouterr().err.split())
        assert (
            "Protobuf field numbers changed in event 'shop.Placed' within "
            "version 1: order_id 1 -> 2, qty 2 -> 3." in err
        )
        assert FIX_TEXT in err
