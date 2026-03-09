"""Tests for CLI `protean ir diff` command."""

import json

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.ir.builder import IRBuilder

runner = CliRunner()


def _write_ir(tmp_path, filename, ir_dict):
    """Write an IR dict to a JSON file and return the path string."""
    path = tmp_path / filename
    path.write_text(json.dumps(ir_dict, indent=2))
    return str(path)


def _minimal_ir(**overrides):
    """Minimal IR dict for CLI tests."""
    ir = {
        "$schema": "https://protean.dev/ir/v0.1.0/schema.json",
        "checksum": "sha256:abc123",
        "clusters": {},
        "contracts": {"events": []},
        "diagnostics": [],
        "domain": {
            "camel_case_name": "Test",
            "command_processing": "sync",
            "event_processing": "sync",
            "identity_strategy": "uuid",
            "identity_type": "string",
            "name": "Test",
            "normalized_name": "test",
        },
        "elements": {},
        "flows": {"domain_services": {}, "process_managers": {}, "subscribers": {}},
        "generated_at": "2026-01-01T00:00:00",
        "ir_version": "0.1.0",
        "projections": {},
    }
    ir.update(overrides)
    return ir


def _make_cluster(
    name, fields=None, events=None, commands=None, event_handlers=None, **extra
):
    """Build a minimal cluster dict."""
    cluster = {
        "aggregate": {
            "element_type": "AGGREGATE",
            "fields": fields or {},
            "fqn": f"app.{name}",
            "identity_field": "id",
            "invariants": {"post": [], "pre": []},
            "module": "app",
            "name": name,
            "options": {
                "auto_add_id_field": True,
                "fact_events": False,
                "is_event_sourced": False,
                "limit": 100,
                "provider": "default",
                "schema_name": None,
                "stream_category": None,
            },
        },
        "application_services": {},
        "command_handlers": {},
        "commands": commands or {},
        "database_models": {},
        "entities": {},
        "event_handlers": event_handlers or {},
        "events": events or {},
        "repositories": {},
        "value_objects": {},
    }
    cluster.update(extra)
    return cluster


@pytest.fixture()
def ir_pair(tmp_path):
    """Create two IR JSON files with a known difference."""
    from tests.ir.elements import build_cluster_test_domain, build_handler_test_domain

    ir1 = IRBuilder(build_cluster_test_domain()).build()
    ir2 = IRBuilder(build_handler_test_domain()).build()

    return (
        _write_ir(tmp_path, "left.json", ir1),
        _write_ir(tmp_path, "right.json", ir2),
    )


@pytest.fixture()
def identical_pair(tmp_path):
    """Create two identical IR JSON files."""
    from tests.ir.elements import build_cluster_test_domain

    ir = IRBuilder(build_cluster_test_domain()).build()

    return (
        _write_ir(tmp_path, "left.json", ir),
        _write_ir(tmp_path, "right.json", ir),
    )


@pytest.mark.no_test_domain
class TestDiffJSON:
    def test_json_output_is_valid(self, ir_pair):
        left, right = ir_pair
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right, "-f", "json"]
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "summary" in parsed
        assert "clusters" in parsed

    def test_json_has_changes(self, ir_pair):
        left, right = ir_pair
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right, "-f", "json"]
        )
        parsed = json.loads(result.output)
        assert parsed["summary"]["has_changes"] is True

    def test_json_no_changes(self, identical_pair):
        left, right = identical_pair
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right, "-f", "json"]
        )
        parsed = json.loads(result.output)
        assert parsed["summary"]["has_changes"] is False


@pytest.mark.no_test_domain
class TestDiffText:
    def test_text_output_shows_changes(self, ir_pair):
        left, right = ir_pair
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert result.exit_code == 0
        assert "IR Diff" in result.output

    def test_text_output_no_changes(self, identical_pair):
        left, right = identical_pair
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert result.exit_code == 0
        assert "No changes" in result.output

    def test_text_is_default_format(self, ir_pair):
        left, right = ir_pair
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        # Default format is text, not JSON
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.output)


@pytest.mark.no_test_domain
class TestDiffTextCoverage:
    """Exercise all text output paths for coverage."""

    def test_text_shows_added_cluster(self, tmp_path):
        left = _write_ir(tmp_path, "left.json", _minimal_ir())
        right = _write_ir(
            tmp_path,
            "right.json",
            _minimal_ir(clusters={"app.Order": _make_cluster("Order")}),
        )
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert result.exit_code == 0
        assert "Clusters" in result.output
        assert "Order" in result.output

    def test_text_shows_removed_cluster(self, tmp_path):
        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(clusters={"app.Order": _make_cluster("Order")}),
        )
        right = _write_ir(tmp_path, "right.json", _minimal_ir())
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "Order" in result.output

    def test_text_shows_field_changes(self, tmp_path):
        left_cluster = _make_cluster(
            "Order",
            fields={
                "name": {"kind": "standard", "type": "String", "max_length": 100},
                "legacy": {"kind": "standard", "type": "String"},
            },
        )
        right_cluster = _make_cluster(
            "Order",
            fields={
                "name": {"kind": "standard", "type": "String", "max_length": 200},
                "email": {"kind": "standard", "type": "String", "required": True},
            },
        )
        left = _write_ir(
            tmp_path, "left.json", _minimal_ir(clusters={"app.Order": left_cluster})
        )
        right = _write_ir(
            tmp_path, "right.json", _minimal_ir(clusters={"app.Order": right_cluster})
        )
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        output = result.output
        assert "field: email" in output  # added
        assert "field: legacy" in output  # removed
        assert "max_length" in output  # changed

    def test_text_shows_option_changes(self, tmp_path):
        left_opts = {
            "auto_add_id_field": True,
            "fact_events": False,
            "is_event_sourced": False,
            "limit": 100,
            "provider": "default",
            "schema_name": None,
            "stream_category": None,
        }
        right_opts = dict(left_opts, is_event_sourced=True)
        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(
                clusters={"app.Order": _make_cluster("Order", **{"options": None})}
            ),
        )
        # Need to set options in the cluster properly
        left_cluster = _make_cluster("Order")
        left_cluster["aggregate"]["options"] = left_opts
        right_cluster = _make_cluster("Order")
        right_cluster["aggregate"]["options"] = right_opts
        left = _write_ir(
            tmp_path, "left.json", _minimal_ir(clusters={"app.Order": left_cluster})
        )
        right = _write_ir(
            tmp_path, "right.json", _minimal_ir(clusters={"app.Order": right_cluster})
        )
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "option" in result.output
        assert "is_event_sourced" in result.output

    def test_text_shows_handler_changes(self, tmp_path):
        eh_left = {
            "element_type": "EVENT_HANDLER",
            "fqn": "app.OrderHandler",
            "handlers": {},
            "module": "app",
            "name": "OrderHandler",
            "part_of": "app.Order",
        }
        eh_right = dict(eh_left, handlers={"Test.OrderPlaced.v1": ["on_placed"]})
        left_cluster = _make_cluster(
            "Order", event_handlers={"app.OrderHandler": eh_left}
        )
        right_cluster = _make_cluster(
            "Order", event_handlers={"app.OrderHandler": eh_right}
        )
        left = _write_ir(
            tmp_path, "left.json", _minimal_ir(clusters={"app.Order": left_cluster})
        )
        right = _write_ir(
            tmp_path, "right.json", _minimal_ir(clusters={"app.Order": right_cluster})
        )
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "handles" in result.output

    def test_text_shows_invariant_changes(self, tmp_path):
        left_cluster = _make_cluster("Order")
        left_cluster["aggregate"]["invariants"] = {"pre": [], "post": []}
        right_cluster = _make_cluster("Order")
        right_cluster["aggregate"]["invariants"] = {
            "pre": [],
            "post": ["total_positive"],
        }
        left = _write_ir(
            tmp_path, "left.json", _minimal_ir(clusters={"app.Order": left_cluster})
        )
        right = _write_ir(
            tmp_path, "right.json", _minimal_ir(clusters={"app.Order": right_cluster})
        )
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "invariant" in result.output
        assert "total_positive" in result.output

    def test_text_shows_breaking_changes(self, tmp_path):
        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(
                contracts={
                    "events": [
                        {"__type__": "Test.OrderPlaced.v1", "fqn": "app.OrderPlaced"}
                    ]
                }
            ),
        )
        right = _write_ir(tmp_path, "right.json", _minimal_ir())
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "Breaking" in result.output

    def test_text_shows_contract_additions(self, tmp_path):
        left = _write_ir(tmp_path, "left.json", _minimal_ir())
        right = _write_ir(
            tmp_path,
            "right.json",
            _minimal_ir(
                contracts={
                    "events": [
                        {"__type__": "Test.OrderPlaced.v1", "fqn": "app.OrderPlaced"}
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "Contracts" in result.output
        assert "published event" in result.output

    def test_text_shows_diagnostic_changes(self, tmp_path):
        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(
                diagnostics=[
                    {
                        "code": "UNUSED_COMMAND",
                        "element": "app.PlaceOrder",
                        "level": "warning",
                        "message": "No handler",
                    }
                ]
            ),
        )
        right = _write_ir(
            tmp_path,
            "right.json",
            _minimal_ir(
                diagnostics=[
                    {
                        "code": "UNHANDLED_EVENT",
                        "element": "app.OrderPlaced",
                        "level": "warning",
                        "message": "No handler",
                    }
                ]
            ),
        )
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "Diagnostics" in result.output
        assert "resolved" in result.output

    def test_text_shows_domain_config_changes(self, tmp_path):
        left_ir = _minimal_ir()
        right_ir = _minimal_ir()
        right_ir["domain"]["event_processing"] = "async"
        left = _write_ir(tmp_path, "left.json", left_ir)
        right = _write_ir(tmp_path, "right.json", right_ir)
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "Domain Config" in result.output
        assert "event_processing" in result.output

    def test_text_shows_projection_changes(self, tmp_path):
        proj_group = {
            "projection": {
                "element_type": "PROJECTION",
                "fields": {},
                "fqn": "app.Dashboard",
                "module": "app",
                "name": "Dashboard",
            },
            "projectors": {},
            "queries": {},
            "query_handlers": {},
        }
        left = _write_ir(tmp_path, "left.json", _minimal_ir())
        right = _write_ir(
            tmp_path,
            "right.json",
            _minimal_ir(projections={"app.Dashboard": proj_group}),
        )
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "Projections" in result.output
        assert "Dashboard" in result.output

    def test_text_shows_flow_changes(self, tmp_path):
        subscriber = {
            "element_type": "SUBSCRIBER",
            "fqn": "app.PaymentSub",
            "module": "app",
            "name": "PaymentSub",
            "broker": "default",
            "stream": "payments",
        }
        left = _write_ir(tmp_path, "left.json", _minimal_ir())
        right = _write_ir(
            tmp_path,
            "right.json",
            _minimal_ir(
                flows={
                    "domain_services": {},
                    "process_managers": {},
                    "subscribers": {"app.PaymentSub": subscriber},
                }
            ),
        )
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "Flows" in result.output
        assert "PaymentSub" in result.output

    def test_text_shows_removed_handler_wiring(self, tmp_path):
        eh_left = {
            "element_type": "EVENT_HANDLER",
            "fqn": "app.OrderHandler",
            "handlers": {"Test.OrderPlaced.v1": ["on_placed"]},
            "module": "app",
            "name": "OrderHandler",
            "part_of": "app.Order",
        }
        eh_right = dict(eh_left, handlers={})
        left_cluster = _make_cluster(
            "Order", event_handlers={"app.OrderHandler": eh_left}
        )
        right_cluster = _make_cluster(
            "Order", event_handlers={"app.OrderHandler": eh_right}
        )
        left = _write_ir(
            tmp_path, "left.json", _minimal_ir(clusters={"app.Order": left_cluster})
        )
        right = _write_ir(
            tmp_path, "right.json", _minimal_ir(clusters={"app.Order": right_cluster})
        )
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "handles" in result.output

    def test_text_shows_removed_invariant(self, tmp_path):
        left_cluster = _make_cluster("Order")
        left_cluster["aggregate"]["invariants"] = {"pre": ["check_stock"], "post": []}
        right_cluster = _make_cluster("Order")
        right_cluster["aggregate"]["invariants"] = {"pre": [], "post": []}
        left = _write_ir(
            tmp_path, "left.json", _minimal_ir(clusters={"app.Order": left_cluster})
        )
        right = _write_ir(
            tmp_path, "right.json", _minimal_ir(clusters={"app.Order": right_cluster})
        )
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "invariant" in result.output
        assert "check_stock" in result.output

    def test_text_shows_contract_removal(self, tmp_path):
        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(
                contracts={
                    "events": [
                        {"__type__": "Test.OrderPlaced.v1", "fqn": "app.OrderPlaced"},
                        {"__type__": "Test.OrderShipped.v1", "fqn": "app.OrderShipped"},
                    ]
                }
            ),
        )
        right = _write_ir(
            tmp_path,
            "right.json",
            _minimal_ir(
                contracts={
                    "events": [
                        {"__type__": "Test.OrderPlaced.v1", "fqn": "app.OrderPlaced"}
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "Contracts" in result.output
        assert "published event" in result.output

    def test_text_shows_event_subsection_changes(self, tmp_path):
        """Events added within a cluster show in text output."""
        event = {
            "__type__": "Test.OrderPlaced.v1",
            "__version__": 1,
            "element_type": "EVENT",
            "fields": {},
            "fqn": "app.OrderPlaced",
            "is_fact_event": False,
            "module": "app",
            "name": "OrderPlaced",
            "part_of": "app.Order",
        }
        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(clusters={"app.Order": _make_cluster("Order")}),
        )
        right = _write_ir(
            tmp_path,
            "right.json",
            _minimal_ir(
                clusters={
                    "app.Order": _make_cluster(
                        "Order", events={"app.OrderPlaced": event}
                    )
                }
            ),
        )
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert "events" in result.output
        assert "OrderPlaced" in result.output


@pytest.mark.no_test_domain
class TestDiffArgumentValidation:
    def test_missing_right_aborts(self, tmp_path):
        left = tmp_path / "left.json"
        left.write_text("{}")
        result = runner.invoke(app, ["ir", "diff", "-l", str(left)])
        assert result.exit_code != 0

    def test_both_left_and_domain_aborts(self, tmp_path):
        left = tmp_path / "left.json"
        right = tmp_path / "right.json"
        left.write_text("{}")
        right.write_text("{}")
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", str(left), "-d", "some_domain", "-r", str(right)],
        )
        assert result.exit_code != 0

    def test_neither_left_nor_domain_aborts(self, tmp_path):
        right = tmp_path / "right.json"
        right.write_text("{}")
        result = runner.invoke(app, ["ir", "diff", "-r", str(right)])
        assert result.exit_code != 0

    def test_nonexistent_file_aborts(self):
        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "-l",
                "/nonexistent/left.json",
                "-r",
                "/nonexistent/right.json",
            ],
        )
        assert result.exit_code != 0

    def test_invalid_json_aborts(self, tmp_path):
        left = tmp_path / "left.json"
        right = tmp_path / "right.json"
        left.write_text("not json")
        right.write_text("{}")
        result = runner.invoke(app, ["ir", "diff", "-l", str(left), "-r", str(right)])
        assert result.exit_code != 0
