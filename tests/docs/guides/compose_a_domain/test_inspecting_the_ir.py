"""The examples on the inspecting-the-IR guide behave as the page says."""

import json

import jsonschema
import pytest

from protean.ir import load_schema
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example(tmp_path, monkeypatch):
    # The example writes domain-ir.json to the working directory.
    monkeypatch.chdir(tmp_path)
    return load_example("guides/compose-a-domain/inspecting-the-ir/001.py")


def _name(example, cls):
    return f"{example.__name__}.{cls.__name__}"


def test_ir_has_the_top_level_sections_the_page_shows(example):
    assert set(example.ir) == {
        "$schema",
        "ir_version",
        "generated_at",
        "checksum",
        "domain",
        "contracts",
        "clusters",
        "projections",
        "flows",
        "elements",
        "diagnostics",
    }
    assert example.ir["$schema"] == "https://protean.dev/ir/v0.2.0/schema.json"
    assert example.ir["ir_version"] == "0.2.0"
    assert example.ir["checksum"].startswith("sha256:")
    assert example.ir["domain"]["name"] == "Ecommerce"


def test_ir_prints_as_json(example, capsys):
    load_example("guides/compose-a-domain/inspecting-the-ir/001.py")

    printed = json.loads(capsys.readouterr().out)
    assert printed["ir_version"] == "0.2.0"
    assert _name(example, example.Order) in printed["clusters"]


def test_ir_is_written_to_a_file_with_sorted_keys(example, tmp_path):
    text = (tmp_path / "domain-ir.json").read_text()

    assert json.loads(text) == example.ir
    assert text == json.dumps(example.ir, indent=2, sort_keys=True)


def test_order_records_the_event_place_order_raises(example):
    cluster = example.ir["clusters"][_name(example, example.Order)]

    assert cluster["aggregate"]["method_edges"] == {
        "place_order": {"raises": [_name(example, example.OrderPlaced)]}
    }


def test_command_handler_records_the_aggregate_method_it_invokes(example):
    cluster = example.ir["clusters"][_name(example, example.Order)]
    handler = cluster["command_handlers"][_name(example, example.OrderCommandHandler)]

    assert handler["method_edges"] == {
        "handle_place_order": {
            "invokes": [
                {"element": _name(example, example.Order), "method": "place_order"}
            ]
        }
    }


def test_the_same_domain_gives_the_same_checksum(example):
    assert example.domain.to_ir()["checksum"] == example.ir["checksum"]


def test_ir_validates_against_the_shipped_schema(example):
    jsonschema.validate(instance=example.ir, schema=load_schema())


def test_schema_rejects_an_ir_without_its_version(example):
    broken = {key: value for key, value in example.ir.items() if key != "ir_version"}

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=broken, schema=load_schema())
