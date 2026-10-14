"""IR coverage of what a save writes: ``auto_now`` flags and enrichers.

A ``DateTime``/``Date`` field records ``auto_now`` / ``auto_now_add`` when set.
Registered enrichers appear in a top-level ``enrichers`` section, by kind and
in registration order, so ``protean ir diff`` shows when either changes.
"""

import copy
import json

import jsonschema
import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.fields import Date, DateTime, String
from protean.ir import SCHEMA_PATH
from protean.ir.builder import IRBuilder
from protean.ir.diff import diff_ir

pytestmark = pytest.mark.no_test_domain


class Account(BaseAggregate):
    name: String(max_length=50)
    created_at: DateTime(auto_now_add=True)
    updated_at: DateTime(auto_now=True)
    opened_on: Date(auto_now_add=True)
    closed_at: DateTime()


def stamp_actor(aggregate):
    pass


def stamp_tenant(aggregate):
    pass


def add_request_id(command):
    return {}


def add_trace(event, aggregate):
    return {}


class CallableEnricher:
    def __call__(self, aggregate):
        pass


def _domain(*, aggregate=(), command=(), event=()):
    domain = Domain(name="Test")
    domain.register(Account)
    for fn in aggregate:
        domain.register_aggregate_enricher(fn)
    for fn in command:
        domain.register_command_enricher(fn)
    for fn in event:
        domain.register_event_enricher(fn)
    domain.init(traverse=False)
    return domain


def _build(**enrichers):
    return IRBuilder(_domain(**enrichers)).build()


def _account_fields(ir):
    cluster = ir["clusters"][f"{__name__}.Account"]
    return cluster["aggregate"]["fields"]


def _schema():
    return json.loads(SCHEMA_PATH.read_text())


class TestAutoNowFlags:
    def test_auto_now_is_recorded(self):
        assert _account_fields(_build())["updated_at"]["auto_now"] is True

    def test_auto_now_add_is_recorded(self):
        fields = _account_fields(_build())
        assert fields["created_at"]["auto_now_add"] is True
        assert fields["opened_on"]["auto_now_add"] is True

    def test_each_flag_appears_only_where_it_is_set(self):
        fields = _account_fields(_build())
        assert "auto_now_add" not in fields["updated_at"]
        assert "auto_now" not in fields["created_at"]

    def test_a_plain_temporal_field_carries_neither_flag(self):
        closed_at = _account_fields(_build())["closed_at"]
        assert closed_at == {"kind": "standard", "type": "DateTime"}

    def test_turning_a_flag_on_shows_in_the_diff(self):
        left = _build()
        right = copy.deepcopy(left)
        right_fields = _account_fields(right)
        right_fields["closed_at"]["auto_now"] = True

        result = diff_ir(left, right)

        cluster_delta = result["clusters"]["changed"][f"{__name__}.Account"]
        field_delta = cluster_delta["aggregate"]["fields"]["changed"]["closed_at"]
        assert field_delta == {"auto_now": {"left": None, "right": True}}
        assert result["summary"]["has_changes"] is True


class TestEnrichersSection:
    def test_section_is_absent_without_enrichers(self):
        assert "enrichers" not in _build()

    def test_each_kind_is_listed_by_qualified_name(self):
        ir = _build(
            aggregate=[stamp_actor], command=[add_request_id], event=[add_trace]
        )
        assert ir["enrichers"] == {
            "aggregate": [f"{__name__}.stamp_actor"],
            "command": [f"{__name__}.add_request_id"],
            "event": [f"{__name__}.add_trace"],
        }

    def test_a_kind_without_enrichers_is_left_out(self):
        ir = _build(aggregate=[stamp_actor])
        assert ir["enrichers"] == {"aggregate": [f"{__name__}.stamp_actor"]}

    def test_registration_order_is_kept(self):
        ir = _build(aggregate=[stamp_tenant, stamp_actor])
        assert ir["enrichers"]["aggregate"] == [
            f"{__name__}.stamp_tenant",
            f"{__name__}.stamp_actor",
        ]

    def test_a_callable_object_is_named_by_its_class(self):
        ir = _build(aggregate=[CallableEnricher()])
        assert ir["enrichers"]["aggregate"] == [f"{__name__}.CallableEnricher"]

    def test_enrichers_change_the_checksum(self):
        assert _build()["checksum"] != _build(aggregate=[stamp_actor])["checksum"]

    def test_ir_with_enrichers_and_flags_validates_against_the_schema(self):
        ir = _build(
            aggregate=[stamp_actor], command=[add_request_id], event=[add_trace]
        )
        jsonschema.validate(ir, _schema())


class TestSchemaRejectsMalformedEntries:
    def _errors(self, ir):
        validator = jsonschema.Draft202012Validator(_schema())
        return list(validator.iter_errors(ir))

    def test_a_non_boolean_flag_is_rejected(self):
        ir = _build()
        _account_fields(ir)["updated_at"]["auto_now"] = "yes"
        assert self._errors(ir)

    def test_an_unknown_enricher_kind_is_rejected(self):
        ir = _build(aggregate=[stamp_actor])
        ir["enrichers"]["query"] = ["app.stamp"]
        assert self._errors(ir)

    def test_an_empty_enricher_list_is_rejected(self):
        ir = _build(aggregate=[stamp_actor])
        ir["enrichers"]["command"] = []
        assert self._errors(ir)


class TestEnricherDiff:
    def test_no_enricher_change_reports_nothing(self):
        ir = _build(aggregate=[stamp_actor])
        result = diff_ir(ir, copy.deepcopy(ir))
        assert result["enrichers"] == {}
        assert result["summary"]["has_changes"] is False

    def test_adding_an_enricher_shows_in_the_diff(self):
        result = diff_ir(_build(), _build(aggregate=[stamp_actor]))
        assert result["enrichers"]["changed"] == {
            "aggregate": {"left": None, "right": [f"{__name__}.stamp_actor"]}
        }
        assert result["summary"]["has_changes"] is True

    def test_removing_an_enricher_shows_in_the_diff(self):
        result = diff_ir(_build(event=[add_trace]), _build())
        assert result["enrichers"]["changed"] == {
            "event": {"left": [f"{__name__}.add_trace"], "right": None}
        }

    def test_reordering_enrichers_shows_in_the_diff(self):
        result = diff_ir(
            _build(aggregate=[stamp_actor, stamp_tenant]),
            _build(aggregate=[stamp_tenant, stamp_actor]),
        )
        assert set(result["enrichers"]["changed"]) == {"aggregate"}
        assert result["summary"]["has_changes"] is True

    def test_text_diff_prints_the_enricher_change(self, tmp_path):
        left = tmp_path / "left.json"
        right = tmp_path / "right.json"
        left.write_text(json.dumps(_build()), encoding="utf-8")
        right.write_text(json.dumps(_build(aggregate=[stamp_actor])), encoding="utf-8")

        result = CliRunner().invoke(
            app, ["ir", "diff", "--left", str(left), "--right", str(right)]
        )

        output = " ".join(result.output.split())
        assert "Enrichers" in output
        assert f"aggregate: none → {__name__}.stamp_actor" in output
