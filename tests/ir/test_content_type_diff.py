"""A change to a ``Dict`` or ``List`` field's value type breaks old payloads.

The field's ``type`` stays ``Dict`` or ``List`` on both sides, so the change
shows up only in the IR's ``content_type``. Old and new code stop accepting
the same rows whichever way the value type moves, so every difference breaks.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import CliRunner

from protean import Domain
from protean.cli import app
from protean.fields import Decimal, Dict, Float, Integer, List, String, ValueObject
from protean.ir.builder import IRBuilder
from protean.ir.diff import classify_changes, diff_ir

pytestmark = pytest.mark.no_test_domain

PRICE_FQN = "shop.Price"
EVENT_FQN = "shop.Repriced"
EVENT_TYPE = "Shop.Repriced.v1"

runner = CliRunner()

# A field factory takes the domain's value objects by name and returns a field,
# so a field can name a value object registered on the same domain.
FieldFactory = Callable[[dict[str, Any]], Any]


def _build(published: bool = True, **fields: FieldFactory) -> dict[str, Any]:
    """Build a domain whose ``Price`` aggregate and ``Repriced`` event hold *fields*."""
    domain = Domain(name="Shop")
    value_objects = {
        name: domain.value_object(
            type(name, (), {"__module__": "shop", "amount": Float()})
        )
        for name in ("TierPrice", "Band")
    }
    price = domain.aggregate(
        type(
            "Price",
            (),
            {
                "__module__": "shop",
                "name": String(),
                **{name: make(value_objects) for name, make in fields.items()},
            },
        )
    )
    domain.event(
        type(
            "Repriced",
            (),
            {
                "__module__": "shop",
                **{name: make(value_objects) for name, make in fields.items()},
            },
        ),
        part_of=price,
        published=published,
    )
    domain.init(traverse=False)
    return IRBuilder(domain).build()


def _breaks(left: dict[str, Any], right: dict[str, Any], fqn: str = PRICE_FQN):
    report = classify_changes(diff_ir(left, right), left, right)
    return [
        (c.change_type, c.field_name, c.message)
        for c in report.breaking_changes
        if c.element_fqn == fqn
    ]


def _safe_fields(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    report = classify_changes(diff_ir(left, right), left, right)
    return [c.message for c in report.safe_changes if c.element_fqn == PRICE_FQN]


def _contract_breaks(left: dict[str, Any], right: dict[str, Any]):
    return diff_ir(left, right).get("contracts", {}).get("breaking_changes", [])


def untyped_dict(_vos: dict[str, Any]) -> Any:
    return Dict()


def tier_dict(vos: dict[str, Any]) -> Any:
    return Dict(value_type=ValueObject(vos["TierPrice"]))


def band_dict(vos: dict[str, Any]) -> Any:
    return Dict(value_type=ValueObject(vos["Band"]))


def string_list(_vos: dict[str, Any]) -> Any:
    return List(content_type=String)


def integer_list(_vos: dict[str, Any]) -> Any:
    return List(content_type=Integer)


def _message(left: str, right: str, element: str = "AGGREGATE") -> str:
    fqn = PRICE_FQN if element == "AGGREGATE" else EVENT_FQN
    return (
        f"Field 'tiers' value type changed from '{left}' to '{right}' in "
        f"{element} '{fqn}'"
    )


class TestTheIRCarriesTheValueType:
    def test_a_typed_dict_names_its_value_object(self):
        field = _build(tiers=tier_dict)["clusters"][PRICE_FQN]["aggregate"]["fields"][
            "tiers"
        ]

        assert (field["type"], field.get("content_type")) == ("Dict", "TierPrice")

    def test_an_untyped_dict_has_no_value_type(self):
        field = _build(tiers=untyped_dict)["clusters"][PRICE_FQN]["aggregate"][
            "fields"
        ]["tiers"]

        assert (field["type"], field.get("content_type")) == ("Dict", None)


class TestValueTypeChangesAreBreaking:
    @pytest.mark.parametrize(
        ("left_field", "right_field", "left_name", "right_name"),
        [
            (untyped_dict, tier_dict, "unset", "TierPrice"),
            (tier_dict, band_dict, "TierPrice", "Band"),
            (tier_dict, untyped_dict, "TierPrice", "unset"),
            (string_list, integer_list, "String", "Integer"),
            (integer_list, string_list, "Integer", "String"),
        ],
        ids=[
            "dict-value-type-added",
            "dict-value-type-changed",
            "dict-value-type-removed",
            "list-content-type-changed",
            "list-content-type-changed-back",
        ],
    )
    def test_the_report_lists_one_field_type_changed(
        self, left_field, right_field, left_name, right_name
    ):
        left, right = _build(tiers=left_field), _build(tiers=right_field)

        assert _breaks(left, right) == [
            ("field_type_changed", "tiers", _message(left_name, right_name))
        ]
        assert not any("tiers" in message for message in _safe_fields(left, right))

    @pytest.mark.parametrize(
        ("left_type", "right_type"),
        [(None, "String"), ("String", None), ("String", "Integer")],
        ids=["list-content-type-added", "list-content-type-removed", "changed"],
    )
    def test_a_list_content_type_delta_in_the_ir_is_breaking(
        self, left_type, right_type
    ):
        # ``List()`` always emits a content type, so an IR without one comes
        # from a hand-written or older snapshot. Edit the IR to cover it.
        left, right = _build(tiers=string_list), _build(tiers=string_list)
        for ir, value in ((left, left_type), (right, right_type)):
            field = ir["clusters"][PRICE_FQN]["aggregate"]["fields"]["tiers"]
            if value is None:
                field.pop("content_type")
            else:
                field["content_type"] = value

        shown = {None: "unset"}
        assert _breaks(left, right) == [
            (
                "field_type_changed",
                "tiers",
                _message(
                    shown.get(left_type, left_type), shown.get(right_type, right_type)
                ),
            )
        ]

    def test_a_type_change_reports_the_type_not_the_value_type(self):
        left = _build(tiers=string_list)
        right = _build(tiers=lambda _vos: String())

        assert _breaks(left, right) == [
            (
                "field_type_changed",
                "tiers",
                (
                    "Field 'tiers' type changed from 'List' to 'String' in "
                    f"AGGREGATE '{PRICE_FQN}'"
                ),
            )
        ]


class TestUnchangedValueTypesAreNotReported:
    def test_a_same_value_type_with_another_change_gives_no_entry(self):
        left = _build(tiers=tier_dict)
        right = _build(
            tiers=lambda vos: Dict(
                value_type=ValueObject(vos["TierPrice"]), description="Tier prices"
            )
        )

        assert diff_ir(left, right)["summary"]["has_changes"] is True
        assert _breaks(left, right) == []
        assert _contract_breaks(left, right) == []

    def test_a_list_of_decimal_with_the_same_content_type_gives_no_entry(self):
        left = _build(tiers=lambda _vos: List(content_type=Decimal))
        right = _build(
            tiers=lambda _vos: List(content_type=Decimal, description="Prices")
        )

        assert _breaks(left, right) == []

    def test_optional_and_union_compare_equal_across_python_versions(self):
        # Python 3.14 records ``Optional[int]`` as ``Union``; earlier versions
        # record it as ``Optional``. Edit the IR to stand in for both builds.
        left, right = _build(tiers=string_list), _build(tiers=string_list)
        for ir, value in ((left, "Optional"), (right, "Union")):
            ir["clusters"][PRICE_FQN]["aggregate"]["fields"]["tiers"][
                "content_type"
            ] = value

        assert _breaks(left, right) == []
        assert _breaks(left, right, fqn=EVENT_FQN) == []
        assert _contract_breaks(left, right) == []

    def test_decimal_precision_rules_are_unchanged(self):
        left = _build(amount=lambda _vos: Decimal(precision=10, scale=2))
        widened = _build(amount=lambda _vos: Decimal(precision=19, scale=2))
        rescaled = _build(amount=lambda _vos: Decimal(precision=10, scale=4))

        assert _breaks(left, widened) == []
        assert [b[2] for b in _breaks(left, rescaled)] == [
            (
                "Field 'amount' Decimal shape changed (scale from 2 to 4) in "
                f"AGGREGATE '{PRICE_FQN}'"
            )
        ]


class TestPublishedEvents:
    def test_diff_ir_lists_a_contract_field_type_changed(self):
        left, right = _build(tiers=untyped_dict), _build(tiers=tier_dict)

        assert _contract_breaks(left, right) == [
            {
                "type": "contract_field_type_changed",
                "fqn": EVENT_FQN,
                "field": "tiers",
                "left": "Dict",
                "right": "Dict",
                "message": (
                    "Field 'tiers' value type changed from 'unset' to 'TierPrice' "
                    f"in published event '{EVENT_TYPE}'"
                ),
            }
        ]
        assert _breaks(left, right, EVENT_FQN) == [
            ("field_type_changed", "tiers", _message("unset", "TierPrice", "EVENT"))
        ]

    def test_an_internal_event_has_no_contract_entry(self):
        left = _build(published=False, tiers=untyped_dict)
        right = _build(published=False, tiers=tier_dict)

        assert _contract_breaks(left, right) == []
        assert [b[1] for b in _breaks(left, right, EVENT_FQN)] == ["tiers"]


class TestRenames:
    def test_a_rename_with_a_value_type_change_is_breaking(self):
        left = _build(tiers=untyped_dict)
        right = _build(
            tier_prices=lambda vos: Dict(
                value_type=ValueObject(vos["TierPrice"]), renamed_from="tiers"
            )
        )

        assert _breaks(left, right) == [
            (
                "field_type_changed",
                "tiers",
                (
                    "Field 'tiers' renamed to 'tier_prices' with a value type change "
                    f"from 'unset' to 'TierPrice' in AGGREGATE '{PRICE_FQN}'"
                ),
            )
        ]
        assert not any("renamed" in message for message in _safe_fields(left, right))

        result = diff_ir(left, right)
        assert result["contracts"]["breaking_changes"] == [
            {
                "type": "contract_field_type_changed",
                "fqn": EVENT_FQN,
                "field": "tiers",
                "renamed_to": "tier_prices",
                "left": "Dict",
                "right": "Dict",
                "message": (
                    "Field 'tiers' renamed to 'tier_prices' with a value type "
                    "change from 'unset' to 'TierPrice' in published event "
                    f"'{EVENT_TYPE}'"
                ),
            }
        ]
        assert result["contracts"].get("renamed_fields", []) == []

    def test_a_rename_with_the_same_value_type_stays_a_rename(self):
        left = _build(tiers=tier_dict)
        right = _build(
            tier_prices=lambda vos: Dict(
                value_type=ValueObject(vos["TierPrice"]), renamed_from="tiers"
            )
        )

        assert _breaks(left, right) == []
        assert _safe_fields(left, right) == [
            f"Field 'tiers' renamed to 'tier_prices' in AGGREGATE '{PRICE_FQN}'"
        ]
        result = diff_ir(left, right)
        assert result["contracts"].get("breaking_changes", []) == []
        assert [r["type"] for r in result["contracts"]["renamed_fields"]] == [
            "contract_field_renamed"
        ]


class TestIrDiffCommand:
    def _invoke(self, tmp_path, left, right, *extra: str):
        left_path, right_path = tmp_path / "left.json", tmp_path / "right.json"
        left_path.write_text(json.dumps(left), encoding="utf-8")
        right_path.write_text(json.dumps(right), encoding="utf-8")
        return runner.invoke(
            app, ["ir", "diff", "-l", str(left_path), "-r", str(right_path), *extra]
        )

    def test_typing_an_internal_events_dict_value_exits_1(self, tmp_path):
        # No published event, so no contract break: only the report can give 1.
        result = self._invoke(
            tmp_path,
            _build(published=False, tiers=untyped_dict),
            _build(published=False, tiers=tier_dict),
        )

        assert result.exit_code == 1, result.output

    def test_the_json_report_lists_the_break(self, tmp_path):
        result = self._invoke(
            tmp_path,
            _build(published=False, tiers=untyped_dict),
            _build(published=False, tiers=tier_dict),
            "--format",
            "json",
        )

        assert result.exit_code == 1, result.output
        compatibility = json.loads(result.output)["compatibility"]
        breaks = sorted(
            (c["change_type"], c["element_fqn"], c["field_name"])
            for c in compatibility["breaking_changes"]
        )
        assert breaks == [
            ("field_type_changed", PRICE_FQN, "tiers"),
            ("field_type_changed", EVENT_FQN, "tiers"),
        ]
        assert not any(
            c.get("field_name") == "tiers" for c in compatibility["safe_changes"]
        )

    def test_typing_a_dict_value_exits_1_and_prints_each_break_once(self, tmp_path):
        result = self._invoke(
            tmp_path, _build(tiers=untyped_dict), _build(tiers=tier_dict)
        )

        assert result.exit_code == 1, result.output
        # The Avro verdict after the list repeats the messages, so count only
        # inside the "Breaking Changes" list.
        flat = " ".join(result.output.split())
        start = flat.index("Breaking Changes (")
        end = flat.find("Avro compatibility", start)
        breaking = flat[start:] if end == -1 else flat[start:end]
        assert breaking.count(_message("unset", "TierPrice")) == 1
        assert breaking.count("value type changed from 'unset' to 'TierPrice'") == 2

    def test_the_same_value_type_exits_2(self, tmp_path):
        result = self._invoke(
            tmp_path,
            _build(published=False, tiers=tier_dict),
            _build(
                published=False,
                tiers=lambda vos: Dict(
                    value_type=ValueObject(vos["TierPrice"]), description="Tiers"
                ),
            ),
        )

        assert result.exit_code == 2, result.output
