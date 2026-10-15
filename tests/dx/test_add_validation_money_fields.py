"""The add-validation skill's assets store money as ``Decimal``.

A ``Float`` money field cannot hold 0.1 exactly, so a total of 0.3 does not
equal subtotals of 0.1 and 0.2 and the order's invariant rejects a correct
order. These tests pin the field shape the skill teaches, check that the
order invariant compares exactly, and run each changed asset as a script.
"""

from __future__ import annotations

import runpy
import subprocess
import sys
from decimal import Decimal as D
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.exceptions import ValidationError
from protean.utils.reflection import fields

# Each asset builds its own Domain; these tests never use the test domain.
pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
ASSETS = PACK_ROOT / dx.SKILLS_DIR / "add-validation" / "assets"

LAYER1 = "validation_layer1_field_constraints.py"
LAYER2 = "validation_layer2_vo_invariants.py"
LAYER3 = "validation_layer3_aggregate_invariants.py"
ALL_LAYERS = "validation_all_layers.py"

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; running an asset as a script needs a "
        "real directory",
        allow_module_level=True,
    )

_run_names = count()


def _load(asset: str) -> dict[str, Any]:
    # A unique run name keeps two loads of one file apart and skips the
    # asset's ``__main__`` demo block.
    return runpy.run_path(
        str(ASSETS / asset), run_name=f"add_validation_asset_{next(_run_names)}"
    )


def _ir_field(asset: str, cls_name: str, field_name: str) -> dict[str, Any]:
    domain = _load(asset)["domain"]
    domain.init(traverse=False)
    found = [
        element["fields"][field_name]
        for cluster in domain.to_ir()["clusters"].values()
        for group in cluster.values()
        for element in (group.values() if "name" not in group else [group])
        if element.get("name") == cls_name
    ]
    assert len(found) == 1, found
    return found[0]


MONEY_FIELDS = [
    (LAYER1, "Employee", "salary", True),
    (LAYER2, "Money", "amount", True),
    (LAYER3, "Order", "total_amount", False),
    (LAYER3, "OrderItem", "price", True),
    (LAYER3, "OrderItem", "subtotal", True),
    (ALL_LAYERS, "Price", "amount", True),
]


@pytest.mark.parametrize(("asset", "cls_name", "field_name", "required"), MONEY_FIELDS)
def test_money_field_is_a_decimal_with_precision_19_and_scale_4(
    asset, cls_name, field_name, required
):
    field = _ir_field(asset, cls_name, field_name)

    assert field["type"] == "Decimal"
    assert field["precision"] == 19
    assert field["scale"] == 4
    assert field.get("required", False) is required


def test_salary_minimum_is_a_decimal():
    field = fields(_load(LAYER1)["Employee"])["salary"]

    assert field.min_value == D("0.01")
    assert isinstance(field.min_value, D)


def test_order_total_default_is_not_a_float():
    default = _ir_field(LAYER3, "Order", "total_amount")["default"]

    assert default == 0
    assert not isinstance(default, float)


@pytest.mark.parametrize("field_name", ["latitude", "longitude"])
def test_coordinates_stay_float(field_name):
    assert _ir_field(LAYER2, "GeoCoordinate", field_name)["type"] == "Float"


def _order(ns: dict[str, Any], total: D) -> Any:
    item = ns["OrderItem"]
    return ns["Order"](
        order_id="ORD-EXACT",
        customer_name="Jane Doe",
        total_amount=total,
        items=[
            item(product_name="A", quantity=1, price=D("0.1"), subtotal=D("0.1")),
            item(product_name="B", quantity=1, price=D("0.2"), subtotal=D("0.2")),
        ],
    )


def test_order_total_compares_exactly():
    ns = _load(LAYER3)
    domain = ns["domain"]
    domain.init(traverse=False)
    with domain.domain_context():
        order = _order(ns, D("0.3"))

    assert order.total_amount == D("0.3")


def test_order_total_mismatch_is_still_rejected():
    ns = _load(LAYER3)
    domain = ns["domain"]
    domain.init(traverse=False)
    with domain.domain_context():
        with pytest.raises(ValidationError) as exc:
            _order(ns, D("0.4"))

    assert exc.value.messages["_entity"] == [
        "Total amount (0.4) must equal sum of item subtotals (0.3)"
    ]


@pytest.mark.parametrize(
    ("asset", "expected_line"),
    [
        (LAYER1, "Employee: Jane Doe, Dept: ENGINEERING"),
        (LAYER2, "Booking: BK-001"),
        (LAYER3, "Order: ORD-001, Total: $100"),
        (ALL_LAYERS, "Created: Blue Widget, Stock: 50"),
    ],
)
def test_demo_runs_as_a_script(asset, expected_line):
    # validation_all_layers.py logs a traceback on stderr for its expected
    # unauthorized case, so only the return code and stdout are checked.
    result = subprocess.run(
        [sys.executable, asset],
        cwd=ASSETS,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, (
        f"{asset} exited {result.returncode}:\n{result.stderr}"
    )
    assert expected_line in result.stdout.splitlines(), result.stdout
