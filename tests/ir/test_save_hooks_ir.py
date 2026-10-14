"""IR extraction of ``auto_now`` / ``auto_now_add`` field
flags and of registered aggregate, command and event enrichers.

Both are sparse. A field entry carries a flag only when it is set, and the
``domain`` section lists an enricher kind only when one is registered, so
domains that use neither keep a byte-identical IR and checksum.
"""

import functools
import json
import re

import jsonschema
import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.domain import Domain
from protean.fields import Date, DateTime, Identifier, String
from protean.ir import SCHEMA_PATH
from protean.ir.builder import IRBuilder
from protean.ir.diff import diff_ir

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
ENRICHER_KEYS = ("aggregate_enrichers", "command_enrichers", "event_enrichers")


def stamp_audit(aggregate):
    pass


def stamp_tenant(aggregate):
    pass


def add_user(command):
    return {}


def add_trace(event, aggregate):
    return {}


class CallableEnricher:
    def __call__(self, aggregate):
        pass


class EnricherHolder:
    def stamp(self, aggregate):
        pass


def _make_nested_enricher():
    def nested(aggregate):
        pass

    return nested


def _moduleless_enricher(aggregate):
    pass


_moduleless_enricher.__module__ = None


def _order_cls(*, created_flag=None, updated_flag=None):
    """Build an ``Order`` aggregate class with optional flags on its dates.

    Every call returns a class with the same qualified name, so two IRs built
    from it differ only in the flags.
    """
    created_kwargs = {created_flag: True} if created_flag else {}
    updated_kwargs = {updated_flag: True} if updated_flag else {}

    class Order(BaseAggregate):
        name = String(max_length=50)
        created_at = DateTime(**created_kwargs)
        updated_on = Date(**updated_kwargs)

    return Order


def _build_ir(order_cls=None, *, enrichers=()):
    order_cls = order_cls or _order_cls()
    domain = Domain(name="IRSaveHooks")
    domain.register(order_cls)

    class OrderPlaced(BaseEvent):
        order_id = Identifier()

    class PlaceOrder(BaseCommand):
        order_id = Identifier()

    domain.register(OrderPlaced, part_of=order_cls)
    domain.register(PlaceOrder, part_of=order_cls)
    for kind, fn in enrichers:
        getattr(domain, f"register_{kind}_enricher")(fn)
    with domain.domain_context():
        domain.init(traverse=False)
        return IRBuilder(domain).build()


def _order_fields(ir):
    for cluster in ir["clusters"].values():
        if cluster["aggregate"]["name"] == "Order":
            return cluster["aggregate"]["fields"]
    pytest.fail("Order cluster not found")


def _qualname(fn):
    return f"{fn.__module__}.{fn.__qualname__}"


@pytest.mark.no_test_domain
class TestAutoNowFlags:
    def test_datetime_auto_now(self):
        fields = _order_fields(_build_ir(_order_cls(created_flag="auto_now")))
        assert fields["created_at"]["auto_now"] is True
        assert "auto_now_add" not in fields["created_at"]

    def test_datetime_auto_now_add(self):
        fields = _order_fields(_build_ir(_order_cls(created_flag="auto_now_add")))
        assert fields["created_at"]["auto_now_add"] is True
        assert "auto_now" not in fields["created_at"]

    def test_date_auto_now(self):
        fields = _order_fields(_build_ir(_order_cls(updated_flag="auto_now")))
        assert fields["updated_on"]["auto_now"] is True
        assert "auto_now_add" not in fields["updated_on"]

    def test_date_auto_now_add(self):
        fields = _order_fields(_build_ir(_order_cls(updated_flag="auto_now_add")))
        assert fields["updated_on"]["auto_now_add"] is True
        assert "auto_now" not in fields["updated_on"]

    def test_plain_date_fields_carry_neither_flag(self):
        fields = _order_fields(_build_ir())
        for name in ("created_at", "updated_on"):
            assert "auto_now" not in fields[name]
            assert "auto_now_add" not in fields[name]


@pytest.mark.no_test_domain
class TestEnrichers:
    def test_each_kind_lists_qualified_name(self):
        ir = _build_ir(
            enrichers=[
                ("aggregate", stamp_audit),
                ("command", add_user),
                ("event", add_trace),
            ]
        )
        assert ir["domain"]["aggregate_enrichers"] == [
            "tests.ir.test_save_hooks_ir.stamp_audit"
        ]
        assert ir["domain"]["command_enrichers"] == [
            "tests.ir.test_save_hooks_ir.add_user"
        ]
        assert ir["domain"]["event_enrichers"] == [
            "tests.ir.test_save_hooks_ir.add_trace"
        ]

    def test_registration_order_is_kept(self):
        ir = _build_ir(
            enrichers=[("aggregate", stamp_tenant), ("aggregate", stamp_audit)]
        )
        assert ir["domain"]["aggregate_enrichers"] == [
            _qualname(stamp_tenant),
            _qualname(stamp_audit),
        ]

    def test_callable_instance_named_by_its_class(self):
        ir = _build_ir(enrichers=[("aggregate", CallableEnricher())])
        assert ir["domain"]["aggregate_enrichers"] == [
            "tests.ir.test_save_hooks_ir.CallableEnricher"
        ]

    def test_bound_method_uses_its_qualified_name(self):
        ir = _build_ir(enrichers=[("aggregate", EnricherHolder().stamp)])
        assert ir["domain"]["aggregate_enrichers"] == [
            "tests.ir.test_save_hooks_ir.EnricherHolder.stamp"
        ]

    def test_nested_function_uses_its_qualified_name(self):
        ir = _build_ir(enrichers=[("aggregate", _make_nested_enricher())])
        assert ir["domain"]["aggregate_enrichers"] == [
            "tests.ir.test_save_hooks_ir._make_nested_enricher.<locals>.nested"
        ]

    def test_partial_named_by_the_function_it_wraps(self):
        ir = _build_ir(
            enrichers=[("aggregate", functools.partial(functools.partial(stamp_audit)))]
        )
        assert ir["domain"]["aggregate_enrichers"] == [
            "tests.ir.test_save_hooks_ir.stamp_audit"
        ]

    def test_function_without_a_module_named_by_its_type(self):
        ir = _build_ir(enrichers=[("aggregate", _moduleless_enricher)])
        assert ir["domain"]["aggregate_enrichers"] == ["builtins.function"]

    def test_no_enrichers_no_keys(self):
        ir = _build_ir()
        for key in ENRICHER_KEYS:
            assert key not in ir["domain"]

    def test_only_registered_kind_appears(self):
        ir = _build_ir(enrichers=[("event", add_trace)])
        assert "event_enrichers" in ir["domain"]
        assert "aggregate_enrichers" not in ir["domain"]
        assert "command_enrichers" not in ir["domain"]

    def test_enrichers_change_the_checksum(self):
        assert (
            _build_ir()["checksum"]
            != _build_ir(enrichers=[("aggregate", stamp_audit)])["checksum"]
        )

    def test_enricher_free_domain_section_keeps_its_original_keys(self):
        assert set(_build_ir()["domain"]) == {
            "camel_case_name",
            "command_processing",
            "event_processing",
            "identity_strategy",
            "identity_type",
            "name",
            "normalized_name",
        }


@pytest.mark.no_test_domain
class TestDiff:
    def _field_change(self, result, field):
        changed = result["clusters"]["changed"]
        assert changed, "no cluster changes reported"
        (cluster,) = changed.values()
        return cluster["aggregate"]["fields"]["changed"][field]

    def test_flag_added(self):
        left = _build_ir(_order_cls())
        right = _build_ir(_order_cls(created_flag="auto_now"))
        result = diff_ir(left, right)
        change = self._field_change(result, "created_at")
        assert change == {"auto_now": {"left": None, "right": True}}
        assert result["summary"]["has_changes"] is True
        assert result["summary"]["has_breaking_changes"] is False

    def test_flag_removed(self):
        left = _build_ir(_order_cls(created_flag="auto_now_add"))
        right = _build_ir(_order_cls())
        result = diff_ir(left, right)
        change = self._field_change(result, "created_at")
        assert change == {"auto_now_add": {"left": True, "right": None}}
        assert result["summary"]["has_changes"] is True
        assert result["summary"]["has_breaking_changes"] is False

    def test_flag_swapped(self):
        left = _build_ir(_order_cls(created_flag="auto_now_add"))
        right = _build_ir(_order_cls(created_flag="auto_now"))
        change = self._field_change(diff_ir(left, right), "created_at")
        assert change == {
            "auto_now": {"left": None, "right": True},
            "auto_now_add": {"left": True, "right": None},
        }

    def test_enricher_added(self):
        left = _build_ir()
        right = _build_ir(enrichers=[("aggregate", stamp_audit)])
        result = diff_ir(left, right)
        assert result["domain"]["changed"] == {
            "aggregate_enrichers": {"left": None, "right": [_qualname(stamp_audit)]}
        }
        assert result["summary"]["has_changes"] is True

    def test_enricher_removed(self):
        left = _build_ir(enrichers=[("command", add_user)])
        right = _build_ir()
        result = diff_ir(left, right)
        assert result["domain"]["changed"] == {
            "command_enrichers": {"left": [_qualname(add_user)], "right": None}
        }
        assert result["summary"]["has_changes"] is True
        assert result["summary"]["has_breaking_changes"] is False

    def test_swapped_partial_enricher_is_reported(self):
        left = _build_ir(enrichers=[("aggregate", functools.partial(stamp_audit))])
        right = _build_ir(enrichers=[("aggregate", functools.partial(stamp_tenant))])
        result = diff_ir(left, right)
        assert result["domain"]["changed"] == {
            "aggregate_enrichers": {
                "left": [_qualname(stamp_audit)],
                "right": [_qualname(stamp_tenant)],
            }
        }

    def test_enricher_reordered(self):
        left = _build_ir(
            enrichers=[("aggregate", stamp_audit), ("aggregate", stamp_tenant)]
        )
        right = _build_ir(
            enrichers=[("aggregate", stamp_tenant), ("aggregate", stamp_audit)]
        )
        result = diff_ir(left, right)
        change = result["domain"]["changed"]["aggregate_enrichers"]
        assert change["left"] == [_qualname(stamp_audit), _qualname(stamp_tenant)]
        assert change["right"] == [_qualname(stamp_tenant), _qualname(stamp_audit)]
        assert result["summary"]["has_changes"] is True

    def test_identical_builds_show_no_change(self):
        enrichers = [("event", add_trace)]
        result = diff_ir(
            _build_ir(_order_cls(created_flag="auto_now"), enrichers=enrichers),
            _build_ir(_order_cls(created_flag="auto_now"), enrichers=enrichers),
        )
        assert result["summary"]["has_changes"] is False


@pytest.mark.no_test_domain
class TestDiffCli:
    def test_text_output_shows_enricher_names(self, tmp_path):
        left = tmp_path / "left.json"
        right = tmp_path / "right.json"
        left.write_text(json.dumps(_build_ir()), encoding="utf-8")
        right.write_text(
            json.dumps(_build_ir(enrichers=[("aggregate", stamp_audit)])),
            encoding="utf-8",
        )
        result = CliRunner().invoke(
            app, ["ir", "diff", "-l", str(left), "-r", str(right)]
        )
        # Exit code 2 means "changes found, none breaking".
        assert result.exit_code == 2, result.output
        output = re.sub(r"\s+", "", ANSI_ESCAPE.sub("", result.output))
        assert "DomainConfig" in output
        assert (
            "~aggregate_enrichers:None→['tests.ir.test_save_hooks_ir.stamp_audit']"
            in output
        )

    def test_text_output_keeps_square_brackets_in_values(self, tmp_path):
        left = tmp_path / "left.json"
        right = tmp_path / "right.json"
        ir = _build_ir()
        left.write_text(json.dumps(ir), encoding="utf-8")
        ir["domain"]["name"] = "Shop[red]Front"
        right.write_text(json.dumps(ir), encoding="utf-8")
        result = CliRunner().invoke(
            app, ["ir", "diff", "-l", str(left), "-r", str(right)]
        )
        assert result.exit_code == 2, result.output
        output = re.sub(r"\s+", "", ANSI_ESCAPE.sub("", result.output))
        assert "~name:IRSaveHooks→Shop[red]Front" in output


def _schema():
    return json.loads(SCHEMA_PATH.read_text())


@pytest.mark.no_test_domain
class TestSchema:
    def test_ir_with_hooks_validates(self):
        ir = _build_ir(
            _order_cls(created_flag="auto_now_add", updated_flag="auto_now"),
            enrichers=[
                ("aggregate", stamp_audit),
                ("command", add_user),
                ("event", add_trace),
            ],
        )
        fields = _order_fields(ir)
        assert fields["created_at"]["auto_now_add"] is True
        assert fields["updated_on"]["auto_now"] is True
        for key in ENRICHER_KEYS:
            assert ir["domain"][key]
        jsonschema.validate(ir, _schema())

    def test_non_boolean_flag_is_rejected(self):
        ir = _build_ir(_order_cls(created_flag="auto_now"))
        _order_fields(ir)["created_at"]["auto_now"] = "yes"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(ir, _schema())

    def test_non_string_enricher_is_rejected(self):
        ir = _build_ir(enrichers=[("event", add_trace)])
        ir["domain"]["event_enrichers"] = [42]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(ir, _schema())

    def test_empty_enricher_list_is_rejected(self):
        ir = _build_ir()
        ir["domain"]["aggregate_enrichers"] = []
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(ir, _schema())

    def test_empty_enricher_name_is_rejected(self):
        ir = _build_ir(enrichers=[("command", add_user)])
        ir["domain"]["command_enrichers"] = [""]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(ir, _schema())
