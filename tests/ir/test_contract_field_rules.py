"""The published-contract check and the compatibility report apply one set of field rules.

``diff_ir()`` builds ``contracts.breaking_changes`` for published events, and
``classify_changes()`` builds the compatibility report over every persisted
element. For a published event's fields, both lists must flag the same breaks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from protean import Domain
from protean.cli import app
from protean.cli.hooks import _check_compat_single
from protean.fields import Decimal, Float, Identifier, Integer, List, String
from protean.ir.builder import IRBuilder
from protean.ir.config import CompatConfig
from protean.ir.diff import (
    CompatibilityChange,
    CompatibilityReport,
    breaking_change_messages,
    classify_changes,
    diff_ir,
)

pytestmark = pytest.mark.no_test_domain

EVENT_FQN = "shop.Placed"
EVENT_TYPE = "Shop.Placed.v1"

runner = CliRunner()


def _build(
    published: bool = True,
    version: int = 1,
    order_fields: dict[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build the IR of a domain with one event ``Placed`` holding *fields*.

    *order_fields* go on the ``Order`` aggregate the event belongs to.
    """
    domain = Domain(name="Shop")
    order = domain.aggregate(
        type(
            "Order",
            (),
            {"__module__": "shop", "name": String(), **(order_fields or {})},
        )
    )
    placed = type(
        "Placed", (), {"__module__": "shop", "order_id": Identifier(), **fields}
    )
    domain.event(placed, part_of=order, published=published, version=version)
    domain.init(traverse=False)
    return IRBuilder(domain).build()


def _contract_breaks(
    left: dict[str, Any], right: dict[str, Any]
) -> list[dict[str, Any]]:
    return diff_ir(left, right).get("contracts", {}).get("breaking_changes", [])


def _report(left: dict[str, Any], right: dict[str, Any]):
    return classify_changes(diff_ir(left, right), left, right)


# Each case: (left fields, right fields, the fields both lists must flag).
_PARITY_CASES = {
    "type-change": (
        {"qty": Integer()},
        {"qty": String()},
        {"qty"},
    ),
    "scale-change": (
        {"amount": Decimal(precision=19, scale=2)},
        {"amount": Decimal(precision=19, scale=4)},
        {"amount"},
    ),
    "precision-lowered": (
        {"amount": Decimal(precision=19, scale=2)},
        {"amount": Decimal(precision=10, scale=2)},
        {"amount"},
    ),
    "precision-added": (
        {"amount": Decimal(scale=2)},
        {"amount": Decimal(precision=19, scale=2)},
        {"amount"},
    ),
    "precision-raised": (
        {"amount": Decimal(precision=10, scale=2)},
        {"amount": Decimal(precision=19, scale=2)},
        set(),
    ),
    "required-added-without-default": (
        {},
        {"note": String(required=True)},
        {"note"},
    ),
    "required-added-with-default": (
        {},
        {"note": String(required=True, default="none")},
        set(),
    ),
    "optional-added": (
        {},
        {"note": String()},
        set(),
    ),
    "rename-with-type-change": (
        {"qty": Integer()},
        {"count": String(renamed_from="qty")},
        {"qty"},
    ),
    "rename-with-scale-change": (
        {"amount": Decimal(precision=19, scale=2)},
        {"total": Decimal(precision=19, scale=4, renamed_from="amount")},
        {"amount"},
    ),
    "plain-rename": (
        {"amount": Decimal(precision=19, scale=2)},
        {"total": Decimal(precision=19, scale=2, renamed_from="amount")},
        set(),
    ),
    "list-content-type-changed": (
        {"tags": List(content_type=String)},
        {"tags": List(content_type=Integer)},
        {"tags"},
    ),
    "rename-with-value-type-change": (
        {"tags": List(content_type=String)},
        {"labels": List(content_type=Integer, renamed_from="tags")},
        {"tags"},
    ),
    "same-value-type": (
        {"tags": List(content_type=String)},
        {"tags": List(content_type=String, description="Tags")},
        set(),
    ),
    "non-shape-attribute-change": (
        {"note": String(max_length=50)},
        {"note": String(max_length=100)},
        set(),
    ),
}


class TestContractAndReportAgree:
    @pytest.mark.filterwarnings("ignore::UserWarning")
    @pytest.mark.parametrize(
        ("left_fields", "right_fields", "expected"),
        list(_PARITY_CASES.values()),
        ids=list(_PARITY_CASES),
    )
    def test_a_field_is_flagged_by_both_lists_or_by_neither(
        self, left_fields, right_fields, expected
    ):
        left, right = _build(**left_fields), _build(**right_fields)

        contract_fields = {b["field"] for b in _contract_breaks(left, right)}
        report_fields = {
            c.field_name
            for c in _report(left, right).breaking_changes
            if c.element_fqn == EVENT_FQN
        }

        assert contract_fields == expected
        assert report_fields == expected


class TestSameNameFieldChanges:
    def test_a_scale_change_is_a_contract_break(self):
        result = diff_ir(
            _build(amount=Decimal(precision=19, scale=2)),
            _build(amount=Decimal(precision=19, scale=4)),
        )

        assert result["contracts"]["breaking_changes"] == [
            {
                "type": "contract_field_type_changed",
                "fqn": EVENT_FQN,
                "field": "amount",
                "left": "Decimal",
                "right": "Decimal",
                "message": (
                    "Field 'amount' Decimal shape changed (scale from 2 to 4) in "
                    f"published event '{EVENT_TYPE}'"
                ),
            }
        ]
        assert result["summary"]["has_breaking_changes"] is True

    def test_a_type_change_is_a_contract_break(self):
        result = diff_ir(_build(qty=Integer()), _build(qty=String()))

        assert result["contracts"]["breaking_changes"] == [
            {
                "type": "contract_field_type_changed",
                "fqn": EVENT_FQN,
                "field": "qty",
                "left": "Integer",
                "right": "String",
                "message": (
                    "Field 'qty' type changed from 'Integer' to 'String' in "
                    f"published event '{EVENT_TYPE}'"
                ),
            }
        ]
        assert result["summary"]["has_breaking_changes"] is True

    def test_a_type_change_that_also_drops_the_shape_reports_the_type(self):
        left = _build(amount=Decimal(precision=19, scale=2))
        right = _build(amount=Float())

        breaks = _contract_breaks(left, right)
        assert [b["message"] for b in breaks] == [
            (
                "Field 'amount' type changed from 'Decimal' to 'Float' in "
                f"published event '{EVENT_TYPE}'"
            )
        ]
        report = _report(left, right)
        assert [c.change_type for c in report.breaking_changes] == [
            "field_type_changed"
        ]
        assert "type changed from 'Decimal' to 'Float'" in (
            report.breaking_changes[0].message
        )

    @pytest.mark.parametrize(
        "right_field",
        [Decimal(precision=19, scale=2), Decimal(scale=2)],
        ids=["precision-raised", "precision-removed"],
    )
    def test_a_precision_widening_is_not_a_contract_break(self, right_field):
        result = diff_ir(
            _build(amount=Decimal(precision=10, scale=2)), _build(amount=right_field)
        )

        assert result["contracts"].get("breaking_changes", []) == []
        assert result["summary"]["has_breaking_changes"] is False

    def test_breaks_are_listed_in_field_order(self):
        # Set iteration order follows the string hash seed, so five fields
        # declared in reverse make an accidentally sorted order unlikely.
        names = ["e", "d", "c", "b", "a"]
        breaks = _contract_breaks(
            _build(**{name: Integer() for name in names}),
            _build(**{name: String() for name in names}),
        )

        assert [b["field"] for b in breaks] == ["a", "b", "c", "d", "e"]

    def test_an_internal_event_has_no_contract_entry(self):
        left = _build(published=False, amount=Decimal(precision=19, scale=2))
        right = _build(published=False, amount=Decimal(precision=19, scale=4))

        assert _contract_breaks(left, right) == []
        assert [c.field_name for c in _report(left, right).breaking_changes] == [
            "amount"
        ]


class TestAddedFields:
    def test_a_required_field_without_a_default_is_a_contract_break(self):
        result = diff_ir(_build(), _build(note=String(required=True)))

        assert result["contracts"]["breaking_changes"] == [
            {
                "type": "contract_required_field_added",
                "fqn": EVENT_FQN,
                "field": "note",
                "message": (
                    f"Required field 'note' added to published event '{EVENT_TYPE}' "
                    "without a default value"
                ),
            }
        ]
        assert result["summary"]["has_breaking_changes"] is True

    @pytest.mark.filterwarnings("ignore::UserWarning")
    @pytest.mark.parametrize(
        "added",
        [String(required=True, default="none"), String()],
        ids=["required-with-default", "optional"],
    )
    def test_a_safe_addition_is_not_a_contract_break(self, added):
        result = diff_ir(_build(), _build(note=added))

        assert result["contracts"].get("breaking_changes", []) == []
        assert result["summary"]["has_breaking_changes"] is False

    def test_a_required_field_claimed_by_a_rename_is_not_an_addition(self):
        breaks = _contract_breaks(
            _build(qty=Integer(required=True)),
            _build(count=Integer(required=True, renamed_from="qty")),
        )

        assert breaks == []


class TestReportFieldName:
    def test_same_name_type_change_names_the_field(self):
        report = _report(_build(qty=Integer()), _build(qty=String()))

        assert [(c.change_type, c.field_name) for c in report.breaking_changes] == [
            ("field_type_changed", "qty")
        ]

    def test_same_name_shape_change_names_the_field(self):
        report = _report(
            _build(amount=Decimal(precision=19, scale=2)),
            _build(amount=Decimal(precision=19, scale=4)),
        )

        assert [(c.change_type, c.field_name) for c in report.breaking_changes] == [
            ("field_type_changed", "amount")
        ]

    @pytest.mark.parametrize(
        ("left_field", "right_field"),
        [
            (Integer(), String(renamed_from="qty")),
            (Decimal(precision=19, scale=2), Decimal(scale=4, renamed_from="qty")),
        ],
        ids=["type-change", "shape-change"],
    )
    def test_rename_with_a_break_names_the_old_field(self, left_field, right_field):
        report = _report(_build(qty=left_field), _build(count=right_field))

        assert [(c.change_type, c.field_name) for c in report.breaking_changes] == [
            ("field_type_changed", "qty")
        ]

    def test_required_field_added_names_the_field(self):
        report = _report(_build(), _build(note=String(required=True)))

        assert [(c.change_type, c.field_name) for c in report.breaking_changes] == [
            ("required_field_added", "note")
        ]


def _write(tmp_path, name: str, ir: dict[str, Any]) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(ir), encoding="utf-8")
    return str(path)


def _diff_cli(tmp_path, left, right, *extra: str):
    return runner.invoke(
        app,
        [
            "ir",
            "diff",
            "-l",
            _write(tmp_path, "left.json", left),
            "-r",
            _write(tmp_path, "right.json", right),
            *extra,
        ],
    )


def _breaking_section(output: str) -> str:
    """The "Breaking Changes" list of the text output, with line wrapping removed.

    The Avro verdict printed after it repeats the report's messages, so a count
    over the whole output would see a break more than once.
    """
    flat = " ".join(output.split())
    start = flat.index("Breaking Changes (")
    end = flat.find("Avro compatibility", start)
    return flat[start:] if end == -1 else flat[start:end]


class TestTextOutputPrintsEachBreakOnce:
    def test_a_same_name_scale_change_prints_once(self, tmp_path):
        result = _diff_cli(
            tmp_path,
            _build(amount=Decimal(precision=19, scale=2)),
            _build(amount=Decimal(precision=19, scale=4)),
        )

        output = _breaking_section(result.output)
        assert result.exit_code == 1
        assert "Breaking Changes (1):" in output
        assert output.count("Decimal shape changed (scale from 2 to 4)") == 1
        assert f"in published event '{EVENT_TYPE}'" in output

    def test_a_rename_with_a_scale_change_prints_once(self, tmp_path):
        result = _diff_cli(
            tmp_path,
            _build(amount=Decimal(precision=19, scale=2)),
            _build(total=Decimal(precision=19, scale=4, renamed_from="amount")),
        )

        output = _breaking_section(result.output)
        assert result.exit_code == 1
        assert "Breaking Changes (1):" in output
        assert output.count("renamed to 'total' with a Decimal shape change") == 1
        assert f"in published event '{EVENT_TYPE}'" in output

    def test_a_required_field_added_prints_once(self, tmp_path):
        result = _diff_cli(tmp_path, _build(), _build(note=String(required=True)))

        output = _breaking_section(result.output)
        assert "Breaking Changes (1):" in output
        assert output.count("Required field 'note' added") == 1

    def test_a_removed_field_prints_once(self, tmp_path):
        result = _diff_cli(tmp_path, _build(note=String()), _build())

        output = _breaking_section(result.output)
        assert "Breaking Changes (1):" in output
        assert output.count("Field 'note' removed") == 1

    def test_breaks_on_two_fields_each_print(self, tmp_path):
        result = _diff_cli(
            tmp_path,
            _build(qty=Integer(), amount=Decimal(precision=19, scale=2)),
            _build(qty=String(), amount=Decimal(precision=19, scale=4)),
        )

        output = _breaking_section(result.output)
        assert "Breaking Changes (2):" in output
        assert output.count("Field 'amount' Decimal shape changed") == 1
        assert output.count("Field 'qty' type changed") == 1

    def test_a_break_on_an_internal_event_still_prints(self, tmp_path):
        result = _diff_cli(
            tmp_path,
            _build(published=False, amount=Decimal(precision=19, scale=2)),
            _build(published=False, amount=Decimal(precision=19, scale=4)),
        )

        output = _breaking_section(result.output)
        assert result.exit_code == 1
        assert "Breaking Changes (1):" in output
        assert (
            f"Field 'amount' Decimal shape changed (scale from 2 to 4) in EVENT "
            f"'{EVENT_FQN}'" in output
        )

    def test_an_event_type_change_prints_from_both_lists(self, tmp_path):
        result = _diff_cli(tmp_path, _build(), _build(version=2))

        output = _breaking_section(result.output)
        assert "Breaking Changes (2):" in output
        assert "type changed for published event" in output
        assert f"Type string changed for '{EVENT_FQN}'" in output


class TestBreakingChangeMessagesMatchOnEveryKeyPart:
    """A report change is dropped only when element, field and kind all match."""

    _CONTRACT = {
        "type": "contract_field_type_changed",
        "fqn": EVENT_FQN,
        "field": "amount",
        "message": "contract: amount",
    }

    def _messages(self, **change: str) -> list[str]:
        report = CompatibilityReport(
            breaking_changes=[
                CompatibilityChange(
                    severity="breaking",
                    message="report: amount",
                    **{
                        "element_fqn": EVENT_FQN,
                        "change_type": "field_type_changed",
                        "field_name": "amount",
                        **change,
                    },
                )
            ]
        )
        return breaking_change_messages(
            {"contracts": {"breaking_changes": [self._CONTRACT]}}, report
        )

    def test_a_full_match_drops_the_report_change(self):
        assert self._messages() == ["contract: amount"]

    @pytest.mark.parametrize(
        "change",
        [
            {"element_fqn": "shop.Order"},
            {"field_name": "qty"},
            {"change_type": "field_removed"},
        ],
        ids=["other-element", "other-field", "other-kind"],
    )
    def test_a_partial_match_keeps_the_report_change(self, change):
        assert self._messages(**change) == ["contract: amount", "report: amount"]

    def test_without_a_report_only_contract_messages_are_listed(self):
        assert breaking_change_messages(
            {"contracts": {"breaking_changes": [self._CONTRACT]}}
        ) == ["contract: amount"]


class TestSameFieldOnTwoElements:
    def test_an_aggregate_break_still_prints_beside_the_event_break(self, tmp_path):
        result = _diff_cli(
            tmp_path,
            _build(
                order_fields={"amount": Decimal(precision=19, scale=2)},
                amount=Decimal(precision=19, scale=2),
            ),
            _build(
                order_fields={"amount": Decimal(precision=19, scale=4)},
                amount=Decimal(precision=19, scale=4),
            ),
        )

        output = _breaking_section(result.output)
        assert "Breaking Changes (2):" in output
        assert "in AGGREGATE 'shop.Order'" in output
        assert f"in published event '{EVENT_TYPE}'" in output


class TestExcludedPublishedEvent:
    def test_a_field_break_on_an_excluded_published_event_exits_1(self, tmp_path):
        protean_dir = tmp_path / ".protean"
        protean_dir.mkdir()
        (protean_dir / "config.toml").write_text(
            f'[compatibility]\nexclude = ["{EVENT_FQN}"]\n', encoding="utf-8"
        )

        result = _diff_cli(
            tmp_path,
            _build(amount=Decimal(precision=19, scale=2)),
            _build(amount=Decimal(precision=19, scale=4)),
            "--dir",
            str(protean_dir),
            "-f",
            "json",
        )

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["compatibility"]["breaking_changes"] == []
        assert [b["field"] for b in payload["contracts"]["breaking_changes"]] == [
            "amount"
        ]

    def test_under_warn_the_break_is_printed_and_exits_0(self, tmp_path):
        protean_dir = tmp_path / ".protean"
        protean_dir.mkdir()
        (protean_dir / "config.toml").write_text(
            f'[compatibility]\nstrictness = "warn"\nexclude = ["{EVENT_FQN}"]\n',
            encoding="utf-8",
        )

        result = _diff_cli(
            tmp_path,
            _build(qty=Integer()),
            _build(qty=String()),
            "--dir",
            str(protean_dir),
        )

        assert result.exit_code == 0
        assert (
            f"Field 'qty' type changed from 'Integer' to 'String' in "
            f"published event '{EVENT_TYPE}'" in _breaking_section(result.output)
        )


class TestJsonCompatibilityBlock:
    def test_field_name_is_filled_for_a_type_change(self, tmp_path):
        result = _diff_cli(
            tmp_path, _build(qty=Integer()), _build(qty=String()), "-f", "json"
        )

        payload = json.loads(result.output)
        breaks = payload["compatibility"]["breaking_changes"]
        assert [(b["change_type"], b["field_name"]) for b in breaks] == [
            ("field_type_changed", "qty")
        ]


class TestHookOnExcludedPublishedEvent:
    """The pre-commit hook names a contract break the `exclude` filter left in."""

    def _check(self, config: CompatConfig) -> bool:
        baseline = _build(qty=Integer())
        current = _build(qty=String())
        with (
            patch("protean.ir.git.load_ir_from_commit", return_value=baseline),
            patch("protean.cli.hooks._load_live_ir", return_value=current),
        ):
            return _check_compat_single(
                "shop.py", Path(".protean"), base="HEAD", config=config
            )

    def test_strict_blocks_and_names_the_break(self, capsys):
        assert self._check(CompatConfig(exclude=(EVENT_FQN,))) is False

        err = " ".join(capsys.readouterr().err.split())
        assert "Breaking IR changes detected for shop.py:" in err
        assert (
            f"! Field 'qty' type changed from 'Integer' to 'String' in "
            f"published event '{EVENT_TYPE}'" in err
        )

    def test_warn_passes_and_names_the_break(self, capsys):
        config = CompatConfig(strictness="warn", exclude=(EVENT_FQN,))
        assert self._check(config) is True

        err = " ".join(capsys.readouterr().err.split())
        assert "Field 'qty' type changed from 'Integer' to 'String'" in err
        assert "strictness=warn" in err
