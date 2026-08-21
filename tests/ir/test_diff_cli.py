"""Tests for CLI `protean ir diff` command."""

import copy
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.ir.builder import IRBuilder

runner = CliRunner()


def _write_ir(tmp_path, filename, ir_dict):
    """Write an IR dict to a JSON file and return the path string."""
    path = tmp_path / filename
    path.write_text(json.dumps(ir_dict, indent=2), encoding="utf-8")
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
        assert result.exit_code in (0, 1, 2)
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
        assert result.exit_code in (1, 2)
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
        assert result.exit_code in (1, 2)
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
            _minimal_ir(clusters={"app.Order": _make_cluster("Order", options=None)}),
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

    def test_base_without_domain_aborts(self, tmp_path):
        result = runner.invoke(app, ["ir", "diff", "--base", "HEAD"])
        assert result.exit_code != 0

    def test_base_with_left_aborts(self, tmp_path):
        left = tmp_path / "left.json"
        left.write_text("{}")
        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "--base",
                "HEAD",
                "-l",
                str(left),
                "-d",
                "some_domain",
            ],
        )
        assert result.exit_code != 0

    def test_base_with_right_aborts(self, tmp_path):
        right = tmp_path / "right.json"
        right.write_text("{}")
        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "--base",
                "HEAD",
                "-r",
                str(right),
                "-d",
                "some_domain",
            ],
        )
        assert result.exit_code != 0


# ------------------------------------------------------------------
# CI Exit Codes
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDiffExitCodes:
    """CI-friendly exit codes: 0 = no changes, 1 = breaking, 2 = non-breaking."""

    def test_exit_0_when_no_changes(self, tmp_path):
        ir = _minimal_ir()
        left = _write_ir(tmp_path, "left.json", ir)
        right = _write_ir(tmp_path, "right.json", ir)
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right, "-f", "json"]
        )
        assert result.exit_code == 0

    def test_exit_1_when_breaking_changes(self, tmp_path):
        """Removing a published event is breaking → exit 1."""
        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(
                contracts={
                    "events": [
                        {
                            "__type__": "Test.OrderPlaced.v1",
                            "fqn": "app.OrderPlaced",
                            "type": "Test.OrderPlaced.v1",
                        }
                    ]
                }
            ),
        )
        right = _write_ir(tmp_path, "right.json", _minimal_ir())
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right, "-f", "json"]
        )
        assert result.exit_code == 1

    def test_exit_2_when_non_breaking_changes_only(self, tmp_path):
        """Adding a new cluster is safe → exit 2."""
        left = _write_ir(tmp_path, "left.json", _minimal_ir())
        right = _write_ir(
            tmp_path,
            "right.json",
            _minimal_ir(clusters={"app.Order": _make_cluster("Order")}),
        )
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right, "-f", "json"]
        )
        assert result.exit_code == 2

    def test_exit_1_for_element_removal(self, tmp_path):
        """Removing a cluster (aggregate) is breaking → exit 1."""
        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(clusters={"app.Order": _make_cluster("Order")}),
        )
        right = _write_ir(tmp_path, "right.json", _minimal_ir())
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right, "-f", "json"]
        )
        assert result.exit_code == 1

    def test_exit_2_for_added_optional_field(self, tmp_path):
        """Adding an optional field is safe → exit 2."""
        left_cluster = _make_cluster("Order", fields={})
        right_cluster = _make_cluster(
            "Order",
            fields={"notes": {"kind": "standard", "type": "String"}},
        )
        left = _write_ir(
            tmp_path, "left.json", _minimal_ir(clusters={"app.Order": left_cluster})
        )
        right = _write_ir(
            tmp_path, "right.json", _minimal_ir(clusters={"app.Order": right_cluster})
        )
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right, "-f", "json"]
        )
        assert result.exit_code == 2

    def test_exit_codes_work_with_text_format(self, tmp_path):
        """Exit codes work for text format too, not just JSON."""
        ir = _minimal_ir()
        left = _write_ir(tmp_path, "left.json", ir)
        right = _write_ir(tmp_path, "right.json", ir)
        result = runner.invoke(app, ["ir", "diff", "-l", left, "-r", right])
        assert result.exit_code == 0


# ------------------------------------------------------------------
# Auto-baseline: --domain only (no --left/--right)
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDiffAutoBaseline:
    """Auto-baseline mode: `protean ir diff --domain my_app`."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        from tests.shared import change_working_directory_to

        self._original_path = sys.path[:]
        self._cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = self._original_path
        os.chdir(self._cwd)

    def _live_ir(self) -> dict:
        from protean.utils.domain_discovery import derive_domain

        domain = derive_domain("publishing7.py")
        domain.init(traverse=False)
        return IRBuilder(domain).build()

    def test_auto_baseline_no_changes(self):
        live_ir = self._live_ir()
        self._protean_dir.mkdir(parents=True)
        (self._protean_dir / "ir.json").write_text(
            json.dumps(live_ir), encoding="utf-8"
        )

        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
                "-f",
                "json",
            ],
        )
        parsed = json.loads(result.output)
        assert parsed["summary"]["has_changes"] is False
        assert result.exit_code == 0

    def test_auto_baseline_detects_changes(self):
        # Store a different IR as baseline
        stale_ir = self._live_ir()
        stale_ir["clusters"] = {}  # Remove all clusters
        stale_ir["checksum"] = "sha256:fake"
        self._protean_dir.mkdir(parents=True)
        (self._protean_dir / "ir.json").write_text(
            json.dumps(stale_ir), encoding="utf-8"
        )

        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
                "-f",
                "json",
            ],
        )
        parsed = json.loads(result.output)
        assert parsed["summary"]["has_changes"] is True

    def test_auto_baseline_aborts_when_no_ir_file(self):
        # No .protean/ir.json exists
        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        assert result.exit_code != 0
        assert "No materialized IR" in result.output

    def test_auto_baseline_aborts_on_invalid_json(self):
        """ValueError from load_stored_ir is caught and produces a clean error."""
        self._protean_dir.mkdir(parents=True)
        (self._protean_dir / "ir.json").write_text("{ bad json }", encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        assert result.exit_code != 0
        assert "Invalid JSON" in result.output

    def test_auto_baseline_text_output(self):
        live_ir = self._live_ir()
        self._protean_dir.mkdir(parents=True)
        (self._protean_dir / "ir.json").write_text(
            json.dumps(live_ir), encoding="utf-8"
        )

        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        assert "No changes" in result.output
        assert result.exit_code == 0


# ------------------------------------------------------------------
# Git baseline: --domain --base <commit>
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDiffGitBaseline:
    """Git baseline mode: `protean ir diff --domain my_app --base HEAD`."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from tests.shared import change_working_directory_to

        self._original_path = sys.path[:]
        self._cwd = Path.cwd()
        change_working_directory_to("test7")
        yield
        sys.path[:] = self._original_path
        os.chdir(self._cwd)

    def _live_ir(self) -> dict:
        from protean.utils.domain_discovery import derive_domain

        domain = derive_domain("publishing7.py")
        domain.init(traverse=False)
        return IRBuilder(domain).build()

    def test_base_head_no_changes(self):
        """When the baseline IR matches the live domain → exit 0."""
        live_ir = self._live_ir()

        with patch("protean.ir.git.load_ir_from_commit", return_value=live_ir):
            result = runner.invoke(
                app,
                ["ir", "diff", "-d", "publishing7.py", "--base", "HEAD", "-f", "json"],
            )
            parsed = json.loads(result.output)
            assert parsed["summary"]["has_changes"] is False
            assert result.exit_code == 0

    def test_base_detects_changes(self):
        """When the baseline IR differs from live domain → changes detected."""
        stale_ir = _minimal_ir()  # Minimal IR with no clusters

        with patch("protean.ir.git.load_ir_from_commit", return_value=stale_ir):
            result = runner.invoke(
                app,
                ["ir", "diff", "-d", "publishing7.py", "--base", "HEAD", "-f", "json"],
            )
            parsed = json.loads(result.output)
            assert parsed["summary"]["has_changes"] is True

    def test_base_aborts_on_missing_commit(self):
        """GitError when loading baseline → non-zero exit."""
        from protean.ir.git import GitError

        with patch(
            "protean.ir.git.load_ir_from_commit",
            side_effect=GitError("commit not found"),
        ):
            result = runner.invoke(
                app,
                ["ir", "diff", "-d", "publishing7.py", "--base", "nonexistent_ref_xyz"],
            )
            assert result.exit_code != 0

    def test_base_custom_dir(self):
        """--dir changes the path passed to load_ir_from_commit."""
        stale_ir = _minimal_ir()

        with patch(
            "protean.ir.git.load_ir_from_commit", return_value=stale_ir
        ) as mock_load:
            result = runner.invoke(
                app,
                [
                    "ir",
                    "diff",
                    "-d",
                    "publishing7.py",
                    "--base",
                    "HEAD",
                    "--dir",
                    "custom_ir",
                    "-f",
                    "json",
                ],
            )
            parsed = json.loads(result.output)
            assert "summary" in parsed
            # Verify that --dir was passed through to the git loader
            mock_load.assert_called_once()
            call_args = mock_load.call_args
            assert "custom_ir" in call_args[0][1]  # path argument

    def test_base_event_model_format(self):
        """--base renders the event-model format over the same git loader."""
        stale_ir = _minimal_ir()  # empty baseline → live domain adds slices

        with patch("protean.ir.git.load_ir_from_commit", return_value=stale_ir):
            result = runner.invoke(
                app,
                [
                    "ir",
                    "diff",
                    "-d",
                    "publishing7.py",
                    "--base",
                    "HEAD",
                    "--format=event-model",
                ],
                env={"COLUMNS": "200"},
            )
            assert result.exit_code != 0
            assert "Model changes:" in result.output


# ------------------------------------------------------------------
# Module-level import tests for new exports
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestIRModuleGitExports:
    """Verify new git-related exports from protean.ir."""

    def test_import_git_error(self):
        from protean.ir import GitError

        assert GitError is not None
        assert issubclass(GitError, Exception)

    def test_import_load_ir_from_commit(self):
        from protean.ir import load_ir_from_commit

        assert load_ir_from_commit is not None
        assert callable(load_ir_from_commit)


@pytest.mark.no_test_domain
class TestAvroVerdictCLI:
    """`protean ir diff` surfaces the Avro compatibility verdict."""

    def _agg_ir(self, tmp_path, filename, fields):
        return _write_ir(
            tmp_path,
            filename,
            _minimal_ir(clusters={"app.Order": _make_cluster("Order", fields=fields)}),
        )

    def test_json_verdict_full_for_added_optional(self, tmp_path):
        left = self._agg_ir(tmp_path, "left.json", {})
        right = self._agg_ir(
            tmp_path, "right.json", {"note": {"kind": "standard", "type": "String"}}
        )
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right, "--format", "json"]
        )
        data = json.loads(result.output)
        assert data["compatibility"]["avro_verdict"] == "FULL"
        assert result.exit_code == 2  # non-breaking changes present

    def test_json_verdict_forward_for_added_required_no_default(self, tmp_path):
        left = self._agg_ir(tmp_path, "left.json", {})
        right = self._agg_ir(
            tmp_path,
            "right.json",
            {"amount": {"kind": "standard", "type": "Float", "required": True}},
        )
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right, "--format", "json"]
        )
        data = json.loads(result.output)
        assert data["compatibility"]["avro_verdict"] == "FORWARD"
        assert result.exit_code == 1  # breaking under strict default

    def test_json_verdict_none_for_type_change(self, tmp_path):
        left = self._agg_ir(
            tmp_path,
            "left.json",
            {"amount": {"kind": "standard", "type": "Integer", "required": True}},
        )
        right = self._agg_ir(
            tmp_path,
            "right.json",
            {"amount": {"kind": "standard", "type": "Float", "required": True}},
        )
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right, "--format", "json"]
        )
        data = json.loads(result.output)
        assert data["compatibility"]["avro_verdict"] == "NONE"

    def test_text_shows_verdict_and_direction_break(self, tmp_path):
        left = self._agg_ir(tmp_path, "left.json", {})
        right = self._agg_ir(
            tmp_path,
            "right.json",
            {"amount": {"kind": "standard", "type": "Float", "required": True}},
        )
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right], env={"COLUMNS": "200"}
        )
        assert "Avro compatibility" in result.output
        assert "FORWARD" in result.output
        # Adding a required field with no default breaks BACKWARD; the
        # explanation line names the direction.
        assert "breaks BACKWARD" in result.output

    def test_json_has_per_element_verdicts(self, tmp_path):
        left = self._agg_ir(tmp_path, "left.json", {})
        right = self._agg_ir(
            tmp_path, "right.json", {"note": {"kind": "standard", "type": "String"}}
        )
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right, "--format", "json"]
        )
        data = json.loads(result.output)
        assert data["compatibility"]["avro_verdicts"] == {"app.Order": "FULL"}

    def test_text_no_changes_omits_verdict(self, tmp_path):
        ir = self._agg_ir(tmp_path, "same.json", {})
        result = runner.invoke(app, ["ir", "diff", "-l", ir, "-r", ir])
        assert result.exit_code == 0
        # No changes → the verdict block is suppressed (vacuously FULL is noise).
        assert "Avro compatibility" not in result.output

    def test_text_full_verdict_notes_breaking_visibility_flip(self, tmp_path):
        # A public→internal flip is breaking but Avro-neutral → FULL with a note.
        def _event(published):
            entry = {
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
            if published:
                entry["published"] = True
            return entry

        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(
                clusters={
                    "app.Order": _make_cluster(
                        "Order", events={"app.OrderPlaced": _event(True)}
                    )
                }
            ),
        )
        right = _write_ir(
            tmp_path,
            "right.json",
            _minimal_ir(
                clusters={
                    "app.Order": _make_cluster(
                        "Order", events={"app.OrderPlaced": _event(False)}
                    )
                }
            ),
        )
        result = runner.invoke(
            app, ["ir", "diff", "-l", left, "-r", right], env={"COLUMNS": "200"}
        )
        assert "Avro compatibility" in result.output
        assert "FULL" in result.output
        assert "payload-compatible" in result.output


# ------------------------------------------------------------------
# Model diff: --format=event-model
# ------------------------------------------------------------------


def _em_command(name, fields=None):
    """Minimal command element for a cluster."""
    return {
        "element_type": "COMMAND",
        "fqn": f"app.{name}",
        "module": "app",
        "name": name,
        "fields": fields or {},
    }


def _em_command_handler(name):
    """Minimal command handler — the wiring the event model does not draw."""
    return {
        "element_type": "COMMAND_HANDLER",
        "fqn": f"app.{name}",
        "module": "app",
        "name": name,
        "handlers": {},
    }


def _em_type(name, version=1):
    """The `__type__` a consumer's handler map keys on for event *name*.

    Consumers are matched to events by `__type__`, not by FQN, so a fixture
    whose handler map keys on anything else describes a consumer no slice
    draws.
    """
    return f"Test.{name}.v{version}"


def _em_event(name, fields=None, is_fact_event=False, version=1):
    """Minimal event element for a cluster."""
    return {
        "element_type": "EVENT",
        "fqn": f"app.{name}",
        "module": "app",
        "name": name,
        "__type__": _em_type(name, version),
        "fields": fields or {},
        "is_fact_event": is_fact_event,
    }


def _em_event_handler(name, handlers=None):
    """Minimal event handler — an automation the event model draws."""
    return {
        "element_type": "EVENT_HANDLER",
        "fqn": f"app.{name}",
        "module": "app",
        "name": name,
        "handlers": handlers or {},
    }


def _em_projector(name, projection_name, handlers=None):
    """Minimal projector — the read model's consumer node the diagram draws."""
    return {
        "element_type": "PROJECTOR",
        "fqn": f"app.{name}",
        "module": "app",
        "name": name,
        "projector_for": f"app.{projection_name}",
        "handlers": handlers or {},
    }


def _em_process_manager(name, handlers=None):
    """Minimal process manager — a cross-cluster automation under flows."""
    return {
        "element_type": "PROCESS_MANAGER",
        "fqn": f"app.{name}",
        "module": "app",
        "name": name,
        "handlers": handlers or {},
    }


def _em_projection_group(name, fields=None, projectors=None):
    """Minimal projection group (a read model)."""
    return {
        "projection": {
            "element_type": "PROJECTION",
            "fields": fields or {},
            "fqn": f"app.{name}",
            "module": "app",
            "name": name,
        },
        "projectors": projectors or {},
        "queries": {},
        "query_handlers": {},
    }


def _added_lines(output):
    return [ln for ln in output.splitlines() if ln.strip().startswith("+")]


def _removed_lines(output):
    return [ln for ln in output.splitlines() if ln.strip().startswith("-")]


def _changed_lines(output):
    return [ln for ln in output.splitlines() if ln.strip().startswith("~")]


@pytest.mark.no_test_domain
class TestDiffEventModelFormat:
    """`protean ir diff --format=event-model` renders the diff in slices."""

    def test_added_command_is_one_named_added_slice(self, tmp_path):
        # AC #1: a new command (and its handler) in an existing cluster is one
        # added slice, named for the command. The command handler is wiring the
        # event model never draws, so it must not add a second line.
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
                        "Order",
                        commands={"app.ShipOrder": _em_command("ShipOrder")},
                        command_handlers={
                            "app.ShipHandler": _em_command_handler("ShipHandler")
                        },
                    )
                }
            ),
        )
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        assert result.exit_code != 0
        assert _added_lines(result.output) == ["  + slice ShipOrder"]
        assert "ShipHandler" not in result.output

    def test_new_cluster_expands_to_one_slice_per_command(self, tmp_path):
        # AC #2: a whole new cluster collapses to one diff entry, so the
        # renderer reads the right snapshot and reports every command as an
        # added slice, named.
        left = _write_ir(tmp_path, "left.json", _minimal_ir())
        right = _write_ir(
            tmp_path,
            "right.json",
            _minimal_ir(
                clusters={
                    "app.Order": _make_cluster(
                        "Order",
                        commands={
                            "app.PlaceOrder": _em_command("PlaceOrder"),
                            "app.ShipOrder": _em_command("ShipOrder"),
                        },
                    )
                }
            ),
        )
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        added = _added_lines(result.output)
        assert len(added) == 2, added
        assert any("PlaceOrder" in ln for ln in added)
        assert any("ShipOrder" in ln for ln in added)
        assert all("new cluster Order" in ln for ln in added)

    def test_command_less_new_cluster_names_the_aggregate(self, tmp_path):
        # A new cluster with no command has no trigger to name, so the
        # aggregate is named instead — the new cluster is never silent.
        left = _write_ir(tmp_path, "left.json", _minimal_ir())
        right = _write_ir(
            tmp_path,
            "right.json",
            _minimal_ir(clusters={"app.Order": _make_cluster("Order")}),
        )
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        assert _added_lines(result.output) == ["  + slice Order (new cluster)"]

    def test_removed_cluster_expands_to_one_slice_per_command(self, tmp_path):
        # The mirror of the new-cluster expansion: a whole removed cluster
        # collapses to one diff entry, so the renderer reads the left snapshot
        # and reports every command it had as a removed slice, named. Collapsing
        # a multi-command cluster to a single aggregate line would lose triggers.
        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(
                clusters={
                    "app.Order": _make_cluster(
                        "Order",
                        commands={
                            "app.PlaceOrder": _em_command("PlaceOrder"),
                            "app.ShipOrder": _em_command("ShipOrder"),
                        },
                    )
                }
            ),
        )
        right = _write_ir(tmp_path, "right.json", _minimal_ir())
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        removed = _removed_lines(result.output)
        assert len(removed) == 2, removed
        assert any("PlaceOrder" in ln for ln in removed)
        assert any("ShipOrder" in ln for ln in removed)
        assert all("removed cluster Order" in ln for ln in removed)

    def test_command_less_removed_cluster_names_the_aggregate(self, tmp_path):
        # A removed cluster with no command has no trigger to name, so the
        # aggregate is named instead — the removed cluster is never silent.
        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(clusters={"app.Order": _make_cluster("Order")}),
        )
        right = _write_ir(tmp_path, "right.json", _minimal_ir())
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        assert _removed_lines(result.output) == ["  - slice Order (removed cluster)"]

    def test_removed_projection_is_removed_read_model(self, tmp_path):
        # AC #3.
        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(
                projections={"app.OrderSummary": _em_projection_group("OrderSummary")}
            ),
        )
        right = _write_ir(tmp_path, "right.json", _minimal_ir())
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        assert _removed_lines(result.output) == ["  - read model OrderSummary"]

    def test_projection_gains_field_is_changed_read_model(self, tmp_path):
        # AC #4: names the slice and the field.
        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(
                projections={"app.OrderSummary": _em_projection_group("OrderSummary")}
            ),
        )
        right = _write_ir(
            tmp_path,
            "right.json",
            _minimal_ir(
                projections={
                    "app.OrderSummary": _em_projection_group(
                        "OrderSummary",
                        fields={"total": {"kind": "standard", "type": "Integer"}},
                    )
                }
            ),
        )
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        assert "Changed:" in result.output
        assert "read model OrderSummary: field total added" in result.output

    def test_identical_snapshots_report_no_model_changes(self, tmp_path):
        # AC #5.
        ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", commands={"app.PlaceOrder": _em_command("PlaceOrder")}
                )
            }
        )
        left = _write_ir(tmp_path, "left.json", ir)
        right = _write_ir(tmp_path, "right.json", ir)
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        assert result.exit_code == 0
        assert "No model changes." in result.output

    def test_non_slice_change_does_not_fabricate_a_slice(self, tmp_path):
        # A domain-metadata attribute is a real IR change (non-zero exit) but
        # not a model change, so the slice view stays honest: no fabricated
        # slice, just "No model changes.".
        left = _write_ir(tmp_path, "left.json", _minimal_ir())
        right_ir = _minimal_ir()
        right_ir["domain"]["command_processing"] = "async"
        right = _write_ir(tmp_path, "right.json", right_ir)
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        assert result.exit_code != 0
        assert "No model changes." in result.output
        assert "slice" not in result.output

    def test_exit_code_parity_with_text_across_change_classes(self, tmp_path):
        # AC #6: same inputs, same exit code, whichever format.
        added_cmd_right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", commands={"app.ShipOrder": _em_command("ShipOrder")}
                )
            }
        )
        cases = {
            "added_command": (
                _minimal_ir(clusters={"app.Order": _make_cluster("Order")}),
                added_cmd_right,
            ),
            "removed_projection": (
                _minimal_ir(
                    projections={
                        "app.OrderSummary": _em_projection_group("OrderSummary")
                    }
                ),
                _minimal_ir(),
            ),
            "changed_field": (
                _minimal_ir(
                    projections={
                        "app.OrderSummary": _em_projection_group("OrderSummary")
                    }
                ),
                _minimal_ir(
                    projections={
                        "app.OrderSummary": _em_projection_group(
                            "OrderSummary",
                            fields={"total": {"kind": "standard", "type": "Integer"}},
                        )
                    }
                ),
            ),
        }
        assert cases, "Expected parity cases but got none"
        for label, (left_ir, right_ir) in cases.items():
            left = _write_ir(tmp_path, f"{label}_left.json", left_ir)
            right = _write_ir(tmp_path, f"{label}_right.json", right_ir)
            text = runner.invoke(
                app, ["ir", "diff", "-l", left, "-r", right, "-f", "text"]
            )
            event_model = runner.invoke(
                app, ["ir", "diff", "-l", left, "-r", right, "--format=event-model"]
            )
            assert text.exit_code == event_model.exit_code, (
                f"{label}: text={text.exit_code} event-model={event_model.exit_code}"
            )
            # Witness that the renderer actually ran: every case here is a real
            # model change, so the event-model output must carry the header. A
            # bare exit-code check would still pass if the branch fell through
            # to the text renderer.
            assert "Model changes:" in event_model.output, label

    def test_exit_code_parity_under_warn_strictness(self, tmp_path):
        # AC #6: a breaking change (removed cluster) exits 0 under warn
        # strictness, and both formats agree.
        protean_dir = tmp_path / ".protean"
        protean_dir.mkdir()
        (protean_dir / "config.toml").write_text(
            '[compatibility]\nstrictness = "warn"\n', encoding="utf-8"
        )
        left = _write_ir(
            tmp_path,
            "left.json",
            _minimal_ir(clusters={"app.Order": _make_cluster("Order")}),
        )
        right = _write_ir(tmp_path, "right.json", _minimal_ir())
        text = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "-l",
                left,
                "-r",
                right,
                "--dir",
                str(protean_dir),
                "-f",
                "text",
            ],
        )
        event_model = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "-l",
                left,
                "-r",
                right,
                "--dir",
                str(protean_dir),
                "--format=event-model",
            ],
        )
        assert text.exit_code == 0
        assert event_model.exit_code == 0
        # The removed cluster is a removed slice, so the renderer ran and
        # printed it even though the exit code is 0 under warn strictness. This
        # cluster has no command, so it is named by its aggregate.
        assert "Model changes:" in event_model.output
        assert _removed_lines(event_model.output) == [
            "  - slice Order (removed cluster)"
        ]


@pytest.mark.no_test_domain
class TestDiffEventModelClusterChanges:
    """The changed-cluster render path: intrinsic participants and the filter."""

    def _run(self, tmp_path, left_ir, right_ir):
        left = _write_ir(tmp_path, "left.json", left_ir)
        right = _write_ir(tmp_path, "right.json", right_ir)
        return runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )

    def test_changed_cluster_reports_each_intrinsic_participant(self, tmp_path):
        # An existing cluster whose aggregate, an event, and a command each
        # change: every moved participant is named under Changed, and the whole
        # cluster-change path (aggregate/event/command) is exercised.
        left_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={"status": {"kind": "standard", "type": "String"}},
                    events={"app.OrderPlaced": _em_event("OrderPlaced")},
                    commands={
                        "app.PlaceOrder": _em_command(
                            "PlaceOrder",
                            fields={"qty": {"kind": "standard", "type": "Integer"}},
                        )
                    },
                )
            }
        )
        right_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={
                        "status": {"kind": "standard", "type": "String"},
                        "total": {"kind": "standard", "type": "Integer"},
                    },
                    events={
                        "app.OrderPlaced": _em_event(
                            "OrderPlaced",
                            fields={"at": {"kind": "standard", "type": "DateTime"}},
                        ),
                        "app.OrderShipped": _em_event("OrderShipped"),
                    },
                    commands={
                        "app.PlaceOrder": _em_command(
                            "PlaceOrder",
                            fields={
                                "qty": {"kind": "standard", "type": "Integer"},
                                "note": {"kind": "standard", "type": "String"},
                            },
                        )
                    },
                )
            }
        )
        result = self._run(tmp_path, left_ir, right_ir)
        changed = "\n".join(_changed_lines(result.output))
        assert "slice Order: aggregate field total added" in changed
        assert "slice Order: event OrderPlaced field at added" in changed
        assert "slice Order: event OrderShipped added" in changed
        assert "slice Order: command PlaceOrder field note added" in changed

    def test_fact_events_are_filtered_non_fact_events_are_reported(self, tmp_path):
        # Added and changed fact events are dropped (the diagram never draws
        # them); a non-fact event added alongside them is reported. The cluster
        # keeps a command on both sides so the change is a cluster change.
        left_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={
                        "app.FactOrder": _em_event(
                            "FactOrder",
                            fields={"a": {"kind": "standard", "type": "String"}},
                            is_fact_event=True,
                        )
                    },
                )
            }
        )
        right_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={
                        # A changed fact event: its new field must not surface.
                        "app.FactOrder": _em_event(
                            "FactOrder",
                            fields={
                                "a": {"kind": "standard", "type": "String"},
                                "b": {"kind": "standard", "type": "String"},
                            },
                            is_fact_event=True,
                        ),
                        # An added fact event: dropped.
                        "app.FactShipped": _em_event("FactShipped", is_fact_event=True),
                        # An added non-fact event: reported.
                        "app.OrderShipped": _em_event("OrderShipped"),
                    },
                )
            }
        )
        result = self._run(tmp_path, left_ir, right_ir)
        assert "event OrderShipped added" in result.output
        assert "FactShipped" not in result.output
        assert "FactOrder" not in result.output

    def test_a_removed_fact_event_is_not_reported(self, tmp_path):
        # A removed event's fact flag can only be read from the left snapshot.
        # The diagram never drew the fact event, so losing it is not a model
        # change; losing the non-fact event beside it is.
        left_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={
                        "app.FactOrder": _em_event("FactOrder", is_fact_event=True),
                        "app.OrderShipped": _em_event("OrderShipped"),
                    },
                )
            }
        )
        right_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={},
                )
            }
        )
        result = self._run(tmp_path, left_ir, right_ir)
        changed = "\n".join(_changed_lines(result.output))
        assert "slice Order: event OrderShipped removed" in changed
        assert "FactOrder" not in result.output

    def test_an_event_turning_into_a_fact_event_leaves_the_model(self, tmp_path):
        # The event still exists, so the diff calls it changed. The model draws
        # it on the left and not on the right, so the slice loses a node, which
        # reads as removed, with the reason.
        left_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={"app.OrderPlaced": _em_event("OrderPlaced")},
                )
            }
        )
        right_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={
                        "app.OrderPlaced": _em_event("OrderPlaced", is_fact_event=True)
                    },
                )
            }
        )
        result = self._run(tmp_path, left_ir, right_ir)
        changed = "\n".join(_changed_lines(result.output))
        assert "slice Order: event OrderPlaced removed (now a fact event)" in changed

    def test_a_fact_event_turning_into_an_event_joins_the_model(self, tmp_path):
        # The mirror image: the slice gains a node it did not draw before.
        left_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={
                        "app.OrderPlaced": _em_event("OrderPlaced", is_fact_event=True)
                    },
                )
            }
        )
        right_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={"app.OrderPlaced": _em_event("OrderPlaced")},
                )
            }
        )
        result = self._run(tmp_path, left_ir, right_ir)
        changed = "\n".join(_changed_lines(result.output))
        assert (
            "slice Order: event OrderPlaced added (no longer a fact event)" in changed
        )

    def test_an_event_type_change_is_a_changed_event(self, tmp_path):
        # `__type__` is what every consumer routes on, so a version bump rewires
        # the slice even though no field moved. It is not a field change, so it
        # renders as a bare "changed" instead of vanishing.
        left_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={"app.OrderPlaced": _em_event("OrderPlaced")},
                )
            }
        )
        right_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={"app.OrderPlaced": _em_event("OrderPlaced", version=2)},
                )
            }
        )
        result = self._run(tmp_path, left_ir, right_ir)
        assert "slice Order: event OrderPlaced changed" in "\n".join(
            _changed_lines(result.output)
        )

    def test_an_aggregate_invariant_or_option_change_is_a_changed_slice(self, tmp_path):
        # The aggregate is a node the slice draws, so a change to it is a model
        # change whether or not it touched a field. Reporting only field deltas
        # printed "No model changes." over a changed invariant.
        left_cluster = _make_cluster(
            "Order", commands={"app.PlaceOrder": _em_command("PlaceOrder")}
        )
        right_cluster = copy.deepcopy(left_cluster)
        right_cluster["aggregate"]["invariants"]["post"] = ["total_is_positive"]
        right_cluster["aggregate"]["options"]["limit"] = 50
        result = self._run(
            tmp_path,
            _minimal_ir(clusters={"app.Order": left_cluster}),
            _minimal_ir(clusters={"app.Order": right_cluster}),
        )
        assert "slice Order: aggregate changed" in "\n".join(
            _changed_lines(result.output)
        )

    def test_a_command_option_change_is_a_changed_slice(self, tmp_path):
        # Same for the command that triggers the slice.
        left_command = _em_command("PlaceOrder")
        right_command = dict(left_command, options={"part_of": "app.Order"})
        result = self._run(
            tmp_path,
            _minimal_ir(
                clusters={
                    "app.Order": _make_cluster(
                        "Order", commands={"app.PlaceOrder": left_command}
                    )
                }
            ),
            _minimal_ir(
                clusters={
                    "app.Order": _make_cluster(
                        "Order", commands={"app.PlaceOrder": right_command}
                    )
                }
            ),
        )
        assert "slice Order: command PlaceOrder changed" in "\n".join(
            _changed_lines(result.output)
        )

    def test_a_method_edges_only_change_is_not_a_model_change(self, tmp_path):
        # `method_edges` is the fail-open raise/invoke derivation the event
        # model generators deliberately do not read, so a delta confined to it
        # draws nothing different.
        left_cluster = _make_cluster(
            "Order", commands={"app.PlaceOrder": _em_command("PlaceOrder")}
        )
        left_cluster["aggregate"]["method_edges"] = {"place": {"raises": []}}
        right_cluster = copy.deepcopy(left_cluster)
        right_cluster["aggregate"]["method_edges"] = {
            "place": {"raises": ["app.OrderPlaced"]}
        }
        result = self._run(
            tmp_path,
            _minimal_ir(clusters={"app.Order": left_cluster}),
            _minimal_ir(clusters={"app.Order": right_cluster}),
        )
        assert result.output.strip() == "No model changes."


@pytest.mark.no_test_domain
class TestDiffEventModelAutomationRouting:
    """Automations added/removed route to Added/Removed, not to Changed."""

    def _run(self, tmp_path, left_ir, right_ir):
        left = _write_ir(tmp_path, "left.json", left_ir)
        right = _write_ir(tmp_path, "right.json", right_ir)
        return runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )

    def _order_cluster(self, event_handlers=None):
        """An Order cluster raising one drawn event, for consumers to match."""
        return _make_cluster(
            "Order",
            commands={"app.PlaceOrder": _em_command("PlaceOrder")},
            events={"app.OrderPlaced": _em_event("OrderPlaced")},
            event_handlers=event_handlers or {},
        )

    def test_event_handler_add_and_remove_route_to_added_and_removed(self, tmp_path):
        # An event handler is an automation. Adding one is a new consumer (the
        # Added section), removing one is a lost consumer (the Removed section),
        # not a self-contradictory "~ ... added" line under Changed.
        handlers = {_em_type("OrderPlaced"): ["on_placed"]}
        left_ir = _minimal_ir(
            clusters={
                "app.Order": self._order_cluster(
                    event_handlers={
                        "app.OldHandler": _em_event_handler("OldHandler", handlers)
                    }
                )
            }
        )
        right_ir = _minimal_ir(
            clusters={
                "app.Order": self._order_cluster(
                    event_handlers={
                        "app.NewHandler": _em_event_handler("NewHandler", handlers)
                    }
                )
            }
        )
        result = self._run(tmp_path, left_ir, right_ir)
        assert "  + automation NewHandler" in _added_lines(result.output)
        assert "  - automation OldHandler" in _removed_lines(result.output)
        assert not any("Handler" in ln for ln in _changed_lines(result.output))

    def test_handler_matching_no_drawn_event_is_not_reported(self, tmp_path):
        # An event handler is a node in a slice only where its handler map
        # matches a non-fact event. One with an empty map, and one wired to a
        # fact event, are drawn nowhere, so gaining them is not a model change.
        left_ir = _minimal_ir(clusters={"app.Order": self._order_cluster()})
        right_ir = _minimal_ir(
            clusters={
                "app.Order": self._order_cluster(
                    event_handlers={
                        "app.Unwired": _em_event_handler("Unwired"),
                        "app.FactOnly": _em_event_handler(
                            "FactOnly", {_em_type("OrderArchived"): ["on_archived"]}
                        ),
                    }
                )
            }
        )
        result = self._run(tmp_path, left_ir, right_ir)
        assert result.output.strip() == "No model changes."

    def test_added_process_manager_routes_to_added(self, tmp_path):
        # A brand-new process manager is a new automation, so it lands under
        # Added with a "+" — not under Changed with a "~".
        cluster = {"app.Order": self._order_cluster()}
        left_ir = _minimal_ir(clusters=cluster)
        right_ir = _minimal_ir(
            clusters=cluster,
            flows={
                "domain_services": {},
                "process_managers": {
                    "app.FulfillmentPM": _em_process_manager(
                        "FulfillmentPM", {_em_type("OrderPlaced"): {"start": True}}
                    )
                },
                "subscribers": {},
            },
        )
        result = self._run(tmp_path, left_ir, right_ir)
        assert "  + automation FulfillmentPM" in _added_lines(result.output)
        assert not any("FulfillmentPM" in ln for ln in _changed_lines(result.output))

    def test_a_rewired_handler_is_a_changed_automation(self, tmp_path):
        # The node moves to a different event, which is a change the diagram
        # shows, so the handler belongs under Changed.
        cluster = self._order_cluster(
            event_handlers={
                "app.Notifier": _em_event_handler(
                    "Notifier", {_em_type("OrderPlaced"): ["on_placed"]}
                )
            }
        )
        left_ir = _minimal_ir(clusters={"app.Order": cluster})
        right_ir = copy.deepcopy(left_ir)
        right_ir["clusters"]["app.Order"]["event_handlers"]["app.Notifier"][
            "handlers"
        ] = {_em_type("OrderPlaced", version=2): ["on_placed"]}
        right_ir["clusters"]["app.Order"]["events"]["app.OrderPlaced"] = _em_event(
            "OrderPlaced", version=2
        )
        result = self._run(tmp_path, left_ir, right_ir)
        assert "  ~ automation Notifier" in _changed_lines(result.output)

    def test_a_method_edges_only_change_on_a_handler_is_not_a_model_change(
        self, tmp_path
    ):
        # An event handler carries `method_edges` too. The renderer routes a
        # handler by its `handlers` map and never reads that derivation, so a
        # delta confined to it moves no node and is not an automation change.
        cluster = self._order_cluster(
            event_handlers={
                "app.Notifier": _em_event_handler(
                    "Notifier", {_em_type("OrderPlaced"): ["on_placed"]}
                )
            }
        )
        left_ir = _minimal_ir(clusters={"app.Order": cluster})
        right_ir = copy.deepcopy(left_ir)
        right_ir["clusters"]["app.Order"]["event_handlers"]["app.Notifier"][
            "method_edges"
        ] = {"on_placed": {"invokes": ["app.Order.ship"]}}
        result = self._run(tmp_path, left_ir, right_ir)
        assert result.output.strip() == "No model changes."

    def test_a_renamed_handler_method_is_not_a_model_change(self, tmp_path):
        # The renderer routes a handler by the event `__type__` keys in its
        # `handlers` map and never reads the mapped method names. Renaming the
        # method while the same event still routes to the same handler moves no
        # node, so it is not an automation change.
        cluster = self._order_cluster(
            event_handlers={
                "app.Notifier": _em_event_handler(
                    "Notifier", {_em_type("OrderPlaced"): ["on_placed"]}
                )
            }
        )
        left_ir = _minimal_ir(clusters={"app.Order": cluster})
        right_ir = copy.deepcopy(left_ir)
        right_ir["clusters"]["app.Order"]["event_handlers"]["app.Notifier"][
            "handlers"
        ] = {_em_type("OrderPlaced"): ["handle_placed"]}
        result = self._run(tmp_path, left_ir, right_ir)
        assert result.output.strip() == "No model changes."

    def test_a_process_manager_lifecycle_flip_is_a_changed_automation(self, tmp_path):
        # A process manager's `start`/`end` lifecycle is drawn (in its node
        # label and on the edge into it), so flipping it under the same event is
        # a change the diagram shows.
        cluster = {"app.Order": self._order_cluster()}
        left_ir = _minimal_ir(
            clusters=cluster,
            flows={
                "domain_services": {},
                "process_managers": {
                    "app.FulfillmentPM": _em_process_manager(
                        "FulfillmentPM", {_em_type("OrderPlaced"): {"start": True}}
                    )
                },
                "subscribers": {},
            },
        )
        right_ir = copy.deepcopy(left_ir)
        right_ir["flows"]["process_managers"]["app.FulfillmentPM"]["handlers"] = {
            _em_type("OrderPlaced"): {"start": False, "end": True}
        }
        result = self._run(tmp_path, left_ir, right_ir)
        assert "  ~ automation FulfillmentPM" in _changed_lines(result.output)

    def test_a_process_manager_method_rename_is_not_a_model_change(self, tmp_path):
        # The same event, same lifecycle, only the mapped method names differ.
        # The renderer never reads those names, so the diagram is unchanged.
        cluster = {"app.Order": self._order_cluster()}
        left_ir = _minimal_ir(
            clusters=cluster,
            flows={
                "domain_services": {},
                "process_managers": {
                    "app.FulfillmentPM": _em_process_manager(
                        "FulfillmentPM",
                        {_em_type("OrderPlaced"): {"start": True, "methods": ["on_a"]}},
                    )
                },
                "subscribers": {},
            },
        )
        right_ir = copy.deepcopy(left_ir)
        right_ir["flows"]["process_managers"]["app.FulfillmentPM"]["handlers"] = {
            _em_type("OrderPlaced"): {"start": True, "methods": ["on_b"]}
        }
        result = self._run(tmp_path, left_ir, right_ir)
        assert result.output.strip() == "No model changes."

    def test_handlers_of_a_whole_new_cluster_are_added_automations(self, tmp_path):
        # A whole new cluster collapses to one diff entry, so its event
        # handlers are never in `clusters.changed`. They are drawn nodes all
        # the same, and are enumerated from the right snapshot.
        left_ir = _minimal_ir()
        right_ir = _minimal_ir(
            clusters={
                "app.Order": self._order_cluster(
                    event_handlers={
                        "app.Notifier": _em_event_handler(
                            "Notifier", {_em_type("OrderPlaced"): ["on_placed"]}
                        ),
                        "app.Unwired": _em_event_handler("Unwired"),
                    }
                )
            }
        )
        result = self._run(tmp_path, left_ir, right_ir)
        added = _added_lines(result.output)
        assert "  + automation Notifier" in added
        # The unwired handler is a node in no slice, so it stays out.
        assert not any("Unwired" in ln for ln in result.output.splitlines())

    def test_handlers_of_a_whole_removed_cluster_are_removed_automations(
        self, tmp_path
    ):
        # The mirror case, read from the left snapshot: the cluster and every
        # automation it defined are gone from the diagram.
        left_ir = _minimal_ir(
            clusters={
                "app.Order": self._order_cluster(
                    event_handlers={
                        "app.Notifier": _em_event_handler(
                            "Notifier", {_em_type("OrderPlaced"): ["on_placed"]}
                        )
                    }
                )
            }
        )
        right_ir = _minimal_ir()
        result = self._run(tmp_path, left_ir, right_ir)
        assert "  - automation Notifier" in _removed_lines(result.output)

    def test_process_manager_matching_no_drawn_event_is_not_reported(self, tmp_path):
        # Same predicate for a process manager: one that starts on an event no
        # cluster raises has no node in any slice.
        cluster = {"app.Order": self._order_cluster()}
        left_ir = _minimal_ir(clusters=cluster)
        right_ir = _minimal_ir(
            clusters=cluster,
            flows={
                "domain_services": {},
                "process_managers": {
                    "app.OrphanPM": _em_process_manager(
                        "OrphanPM", {_em_type("NothingRaisesThis"): {"start": True}}
                    )
                },
                "subscribers": {},
            },
        )
        result = self._run(tmp_path, left_ir, right_ir)
        assert result.output.strip() == "No model changes."


@pytest.mark.no_test_domain
class TestDiffEventModelProjectors:
    """A read model changes when its projector (consumer node) is rewired."""

    def test_projector_add_remove_and_rewire_are_reported(self, tmp_path):
        # The projection's own fields are identical on both sides, so the only
        # signal is the projectors. A projector is the read model's node in the
        # slice, so one that appears or disappears is a node the diagram gained
        # or lost, and one rewired to a different event is a changed node.
        clusters = {
            "app.Order": _make_cluster(
                "Order",
                commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                events={
                    "app.OrderPlaced": _em_event("OrderPlaced"),
                    "app.OrderShipped": _em_event("OrderShipped"),
                },
            )
        }
        left_ir = _minimal_ir(
            clusters=clusters,
            projections={
                "app.OrderSummary": _em_projection_group(
                    "OrderSummary",
                    projectors={
                        "app.Proj1": _em_projector(
                            "Proj1",
                            "OrderSummary",
                            handlers={_em_type("OrderPlaced"): ["on_placed"]},
                        ),
                        "app.ProjGone": _em_projector(
                            "ProjGone",
                            "OrderSummary",
                            handlers={_em_type("OrderPlaced"): ["on_placed"]},
                        ),
                    },
                )
            },
        )
        right_ir = _minimal_ir(
            clusters=clusters,
            projections={
                "app.OrderSummary": _em_projection_group(
                    "OrderSummary",
                    projectors={
                        "app.Proj1": _em_projector(
                            "Proj1",
                            "OrderSummary",
                            handlers={_em_type("OrderShipped"): ["on_shipped"]},
                        ),
                        "app.ProjNew": _em_projector(
                            "ProjNew",
                            "OrderSummary",
                            handlers={_em_type("OrderShipped"): ["on_shipped"]},
                        ),
                    },
                )
            },
        )
        left = _write_ir(tmp_path, "left.json", left_ir)
        right = _write_ir(tmp_path, "right.json", right_ir)
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        assert "No model changes." not in result.output
        changed = "\n".join(_changed_lines(result.output))
        assert "read model OrderSummary: projector Proj1 changed" in changed
        assert "  + read model OrderSummary: projector ProjNew" in _added_lines(
            result.output
        )
        assert "  - read model OrderSummary: projector ProjGone" in _removed_lines(
            result.output
        )

    def test_a_projector_matching_no_drawn_event_is_not_reported(self, tmp_path):
        # A projector is drawn only where it matches a non-fact event, the same
        # rule as any other consumer. One wired to a fact event, and one wired
        # to nothing, are nodes in no slice.
        clusters = {
            "app.Order": _make_cluster(
                "Order",
                commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                events={
                    "app.OrderPlaced": _em_event("OrderPlaced"),
                    "app.FactOrder": _em_event("FactOrder", is_fact_event=True),
                },
            )
        }
        left_ir = _minimal_ir(
            clusters=clusters,
            projections={
                "app.OrderSummary": _em_projection_group(
                    "OrderSummary",
                    projectors={
                        "app.Proj1": _em_projector(
                            "Proj1",
                            "OrderSummary",
                            handlers={_em_type("OrderPlaced"): ["on_placed"]},
                        )
                    },
                )
            },
        )
        right_ir = copy.deepcopy(left_ir)
        right_ir["projections"]["app.OrderSummary"]["projectors"].update(
            {
                "app.ProjFactOnly": _em_projector(
                    "ProjFactOnly",
                    "OrderSummary",
                    handlers={_em_type("FactOrder"): ["on_fact"]},
                ),
                "app.ProjUnwired": _em_projector("ProjUnwired", "OrderSummary"),
            }
        )
        left = _write_ir(tmp_path, "left.json", left_ir)
        right = _write_ir(tmp_path, "right.json", right_ir)
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        assert result.output.strip() == "No model changes."

    def test_a_projector_method_edges_only_change_is_not_a_read_model_change(
        self, tmp_path
    ):
        # A projector carries `method_edges` like any other element. The
        # renderer draws a projector from its `handlers` map alone, so a delta
        # confined to that derivation is not a change to the read model.
        left_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={"app.OrderPlaced": _em_event("OrderPlaced")},
                )
            },
            projections={
                "app.OrderSummary": _em_projection_group(
                    "OrderSummary",
                    projectors={
                        "app.Proj1": _em_projector(
                            "Proj1",
                            "OrderSummary",
                            handlers={_em_type("OrderPlaced"): ["on_placed"]},
                        )
                    },
                )
            },
        )
        right_ir = copy.deepcopy(left_ir)
        right_ir["projections"]["app.OrderSummary"]["projectors"]["app.Proj1"][
            "method_edges"
        ] = {"on_placed": {"invokes": ["app.Order.ship"]}}
        left = _write_ir(tmp_path, "left.json", left_ir)
        right = _write_ir(tmp_path, "right.json", right_ir)
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        assert result.output.strip() == "No model changes."

    def test_a_projector_method_rename_is_not_a_read_model_change(self, tmp_path):
        # A projector is drawn from the event `__type__` keys in its `handlers`
        # map; the mapped method names are not read. Renaming the method under
        # the same event leaves the read model's node unchanged.
        left_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={"app.OrderPlaced": _em_event("OrderPlaced")},
                )
            },
            projections={
                "app.OrderSummary": _em_projection_group(
                    "OrderSummary",
                    projectors={
                        "app.Proj1": _em_projector(
                            "Proj1",
                            "OrderSummary",
                            handlers={_em_type("OrderPlaced"): ["on_placed"]},
                        )
                    },
                )
            },
        )
        right_ir = copy.deepcopy(left_ir)
        right_ir["projections"]["app.OrderSummary"]["projectors"]["app.Proj1"][
            "handlers"
        ] = {_em_type("OrderPlaced"): ["handle_placed"]}
        left = _write_ir(tmp_path, "left.json", left_ir)
        right = _write_ir(tmp_path, "right.json", right_ir)
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        assert result.output.strip() == "No model changes."

    def test_a_read_model_option_change_is_a_changed_read_model(self, tmp_path):
        # The read model is a participant the slice draws, so a change to it
        # counts even when no field moved.
        left_ir = _minimal_ir(
            projections={"app.OrderSummary": _em_projection_group("OrderSummary")}
        )
        right_ir = copy.deepcopy(left_ir)
        right_ir["projections"]["app.OrderSummary"]["projection"]["options"] = {
            "provider": "memory"
        }
        left = _write_ir(tmp_path, "left.json", left_ir)
        right = _write_ir(tmp_path, "right.json", right_ir)
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )
        assert "read model OrderSummary: changed" in "\n".join(
            _changed_lines(result.output)
        )


@pytest.mark.no_test_domain
class TestDiffEventModelConsumerTopology:
    """A consumer comes and goes with the events around it, not just its own delta."""

    def _run(self, tmp_path, left_ir, right_ir):
        left = _write_ir(tmp_path, "left.json", left_ir)
        right = _write_ir(tmp_path, "right.json", right_ir)
        return runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "--format=event-model"],
            env={"COLUMNS": "200"},
        )

    def _wired_ir(self, events=None):
        """An Order cluster plus a handler and a projector wired to OrderPlaced."""
        handlers = {_em_type("OrderPlaced"): ["on_placed"]}
        return _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events=events
                    if events is not None
                    else {"app.OrderPlaced": _em_event("OrderPlaced")},
                    event_handlers={
                        "app.Notifier": _em_event_handler("Notifier", handlers)
                    },
                )
            },
            projections={
                "app.OrderSummary": _em_projection_group(
                    "OrderSummary",
                    projectors={
                        "app.Proj1": _em_projector(
                            "Proj1", "OrderSummary", handlers=handlers
                        )
                    },
                )
            },
        )

    def test_an_event_becoming_a_fact_event_removes_its_consumers(self, tmp_path):
        # The consumers themselves are identical on both sides. The event they
        # match turns into a fact event, which the diagram does not draw, so
        # both consumer nodes disappear from the slice.
        left_ir = self._wired_ir()
        right_ir = self._wired_ir(
            events={"app.OrderPlaced": _em_event("OrderPlaced", is_fact_event=True)}
        )
        result = self._run(tmp_path, left_ir, right_ir)
        removed = _removed_lines(result.output)
        assert "  - automation Notifier" in removed
        assert "  - read model OrderSummary: projector Proj1" in removed
        assert not any("Notifier" in ln for ln in _changed_lines(result.output))
        assert not any("Proj1" in ln for ln in _changed_lines(result.output))

    def test_an_event_leaving_fact_status_adds_its_consumers(self, tmp_path):
        # The mirror case: the event becomes drawable, so the consumers that
        # already matched it gain their nodes.
        left_ir = self._wired_ir(
            events={"app.OrderPlaced": _em_event("OrderPlaced", is_fact_event=True)}
        )
        right_ir = self._wired_ir()
        result = self._run(tmp_path, left_ir, right_ir)
        added = _added_lines(result.output)
        assert "  + automation Notifier" in added
        assert "  + read model OrderSummary: projector Proj1" in added

    def test_removing_the_only_matched_event_removes_its_consumers(self, tmp_path):
        # Nothing about the handler or the projector changed; the event they
        # both hang off is gone, so their nodes are gone with it.
        left_ir = self._wired_ir()
        right_ir = self._wired_ir(events={})
        result = self._run(tmp_path, left_ir, right_ir)
        removed = _removed_lines(result.output)
        assert "  - automation Notifier" in removed
        assert "  - read model OrderSummary: projector Proj1" in removed

    def test_an_empty_handler_map_gaining_a_live_route_is_an_added_automation(
        self, tmp_path
    ):
        # The handler is drawn nowhere on the left, so its first live route is a
        # node the diagram gained, not a changed node.
        left_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    event_handlers={"app.Notifier": _em_event_handler("Notifier")},
                )
            }
        )
        right_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={"app.OrderPlaced": _em_event("OrderPlaced")},
                    event_handlers={
                        "app.Notifier": _em_event_handler(
                            "Notifier", {_em_type("OrderPlaced"): ["on_placed"]}
                        )
                    },
                )
            }
        )
        result = self._run(tmp_path, left_ir, right_ir)
        assert "  + automation Notifier" in _added_lines(result.output)
        assert not any("Notifier" in ln for ln in _changed_lines(result.output))

    def test_a_route_to_an_undrawn_event_is_not_a_model_change(self, tmp_path):
        # Both consumers keep their live route to OrderPlaced and gain a second
        # one: to a fact event, and to a type no cluster raises. Neither is
        # drawn, so no edge and no node moved.
        left_ir = self._wired_ir(
            events={
                "app.OrderPlaced": _em_event("OrderPlaced"),
                "app.OrderArchived": _em_event("OrderArchived", is_fact_event=True),
            }
        )
        right_ir = copy.deepcopy(left_ir)
        extra = {
            _em_type("OrderPlaced"): ["on_placed"],
            _em_type("OrderArchived"): ["on_archived"],
            _em_type("NothingRaisesThis"): ["on_nothing"],
        }
        right_ir["clusters"]["app.Order"]["event_handlers"]["app.Notifier"][
            "handlers"
        ] = extra
        right_ir["projections"]["app.OrderSummary"]["projectors"]["app.Proj1"][
            "handlers"
        ] = extra
        result = self._run(tmp_path, left_ir, right_ir)
        assert result.output.strip() == "No model changes."

    def test_dropping_a_route_to_an_undrawn_event_is_not_a_model_change(self, tmp_path):
        # The mirror case: the route that goes away named a fact event, so the
        # left-hand diagram never drew it either.
        right_ir = self._wired_ir(
            events={
                "app.OrderPlaced": _em_event("OrderPlaced"),
                "app.OrderArchived": _em_event("OrderArchived", is_fact_event=True),
            }
        )
        left_ir = copy.deepcopy(right_ir)
        left_ir["clusters"]["app.Order"]["event_handlers"]["app.Notifier"][
            "handlers"
        ] = {
            _em_type("OrderPlaced"): ["on_placed"],
            _em_type("OrderArchived"): ["on_archived"],
        }
        result = self._run(tmp_path, left_ir, right_ir)
        assert result.output.strip() == "No model changes."

    def test_dropping_a_drawn_route_is_a_changed_automation(self, tmp_path):
        # The handler keeps a live route to OrderPlaced, so its node stays, but
        # it loses the edge from OrderShipped. That edge was drawn, so the
        # handler is a changed consumer.
        left_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={
                        "app.OrderPlaced": _em_event("OrderPlaced"),
                        "app.OrderShipped": _em_event("OrderShipped"),
                    },
                    event_handlers={
                        "app.Notifier": _em_event_handler(
                            "Notifier",
                            {
                                _em_type("OrderPlaced"): ["on_placed"],
                                _em_type("OrderShipped"): ["on_shipped"],
                            },
                        )
                    },
                )
            }
        )
        right_ir = copy.deepcopy(left_ir)
        right_ir["clusters"]["app.Order"]["event_handlers"]["app.Notifier"][
            "handlers"
        ] = {_em_type("OrderPlaced"): ["on_placed"]}
        result = self._run(tmp_path, left_ir, right_ir)
        assert "  ~ automation Notifier" in _changed_lines(result.output)

    def test_a_whole_new_projection_is_reported_once(self, tmp_path):
        # The "read model OrderSummary" line already says the read model is
        # new, so its projector does not repeat it.
        left_ir = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                    events={"app.OrderPlaced": _em_event("OrderPlaced")},
                )
            }
        )
        right_ir = copy.deepcopy(left_ir)
        right_ir["projections"] = {
            "app.OrderSummary": _em_projection_group(
                "OrderSummary",
                projectors={
                    "app.Proj1": _em_projector(
                        "Proj1",
                        "OrderSummary",
                        handlers={_em_type("OrderPlaced"): ["on_placed"]},
                    )
                },
            )
        }
        result = self._run(tmp_path, left_ir, right_ir)
        assert _added_lines(result.output) == ["  + read model OrderSummary"]

    def test_a_handler_moved_to_another_cluster_is_a_changed_automation(self, tmp_path):
        # The handler keeps its FQN and is drawn on both sides, so it is neither
        # gained nor lost, but it hangs off a different aggregate's event now.
        # The diff reports that as a removed handler under Order plus an added
        # one under Shipment, never as a change, so the node move is only
        # visible in the slices the two snapshots draw it in.
        def _ir(order_handlers, shipment_handlers):
            return _minimal_ir(
                clusters={
                    "app.Order": _make_cluster(
                        "Order",
                        commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                        events={"app.OrderPlaced": _em_event("OrderPlaced")},
                        event_handlers=order_handlers,
                    ),
                    "app.Shipment": _make_cluster(
                        "Shipment",
                        commands={"app.ShipOrder": _em_command("ShipOrder")},
                        events={"app.OrderShipped": _em_event("OrderShipped")},
                        event_handlers=shipment_handlers,
                    ),
                }
            )

        notifier_on_order = {
            "app.Notifier": _em_event_handler(
                "Notifier", {_em_type("OrderPlaced"): ["on_placed"]}
            )
        }
        notifier_on_shipment = {
            "app.Notifier": _em_event_handler(
                "Notifier", {_em_type("OrderShipped"): ["on_shipped"]}
            )
        }
        result = self._run(
            tmp_path,
            _ir(notifier_on_order, {}),
            _ir({}, notifier_on_shipment),
        )
        assert "  ~ automation Notifier" in _changed_lines(result.output)

    def test_a_consumer_losing_one_of_its_two_slices_is_reported(self, tmp_path):
        # Both consumers are wired to an event in each of two clusters, so each
        # is drawn twice. Order's event goes away, which costs them their node
        # in that slice while their node in the Shipment slice stays. Nothing in
        # either consumer's own delta moved, so only the slices they are drawn
        # in say so.
        handlers = {
            _em_type("OrderPlaced"): ["on_placed"],
            _em_type("OrderShipped"): ["on_shipped"],
        }

        def _ir(order_events):
            return _minimal_ir(
                clusters={
                    "app.Order": _make_cluster(
                        "Order",
                        commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                        events=order_events,
                        event_handlers={
                            "app.Notifier": _em_event_handler("Notifier", handlers)
                        },
                    ),
                    "app.Shipment": _make_cluster(
                        "Shipment",
                        commands={"app.ShipOrder": _em_command("ShipOrder")},
                        events={"app.OrderShipped": _em_event("OrderShipped")},
                    ),
                },
                projections={
                    "app.OrderSummary": _em_projection_group(
                        "OrderSummary",
                        projectors={
                            "app.Proj1": _em_projector(
                                "Proj1", "OrderSummary", handlers=handlers
                            )
                        },
                    )
                },
            )

        result = self._run(
            tmp_path,
            _ir({"app.OrderPlaced": _em_event("OrderPlaced")}),
            _ir({}),
        )
        changed = _changed_lines(result.output)
        assert "  ~ automation Notifier" in changed
        assert "  ~ read model OrderSummary: projector Proj1 changed" in changed

    def test_a_pm_lifecycle_flip_on_an_undrawn_route_is_a_changed_automation(
        self, tmp_path
    ):
        # A process manager's node label carries the lifecycle across all of its
        # routes, drawn or not. The flip here is on a route to an event no
        # cluster raises, so no edge moves, but the label the PM is drawn with
        # in the Order slice goes from "(start)" to "(start, end)".
        cluster = {
            "app.Order": _make_cluster(
                "Order",
                commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                events={"app.OrderPlaced": _em_event("OrderPlaced")},
            )
        }
        left_ir = _minimal_ir(
            clusters=cluster,
            flows={
                "domain_services": {},
                "process_managers": {
                    "app.FulfillmentPM": _em_process_manager(
                        "FulfillmentPM",
                        {
                            _em_type("OrderPlaced"): {"start": True},
                            _em_type("NothingRaisesThis"): {"end": False},
                        },
                    )
                },
                "subscribers": {},
            },
        )
        right_ir = copy.deepcopy(left_ir)
        right_ir["flows"]["process_managers"]["app.FulfillmentPM"]["handlers"][
            _em_type("NothingRaisesThis")
        ] = {"end": True}
        result = self._run(tmp_path, left_ir, right_ir)
        assert "  ~ automation FulfillmentPM" in _changed_lines(result.output)

    def test_a_projector_retargeted_to_another_projection_is_reported(self, tmp_path):
        # Both read models stay and the projector keeps its route, so it is
        # drawn in the same slice on both sides. What changed is the projection
        # it feeds, which the node label carries ("Proj1 → OldView" becomes
        # "Proj1 → NewView"). The diff reports it as removed from one projection
        # group and added to the other, so only the label says the node moved.
        clusters = {
            "app.Order": _make_cluster(
                "Order",
                commands={"app.PlaceOrder": _em_command("PlaceOrder")},
                events={"app.OrderPlaced": _em_event("OrderPlaced")},
            )
        }

        def _projector(projection_name):
            return _em_projector(
                "Proj1",
                projection_name,
                handlers={_em_type("OrderPlaced"): ["on_placed"]},
            )

        left_ir = _minimal_ir(
            clusters=clusters,
            projections={
                "app.OldView": _em_projection_group(
                    "OldView", projectors={"app.Proj1": _projector("OldView")}
                ),
                "app.NewView": _em_projection_group("NewView"),
            },
        )
        right_ir = _minimal_ir(
            clusters=clusters,
            projections={
                "app.OldView": _em_projection_group("OldView"),
                "app.NewView": _em_projection_group(
                    "NewView", projectors={"app.Proj1": _projector("NewView")}
                ),
            },
        )
        result = self._run(tmp_path, left_ir, right_ir)
        assert "  ~ read model NewView: projector Proj1 changed" in _changed_lines(
            result.output
        )
        assert not any("Proj1" in ln for ln in _added_lines(result.output))
        assert not any("Proj1" in ln for ln in _removed_lines(result.output))


@pytest.mark.no_test_domain
class TestDiffFormatValidation:
    """`ir diff` rejects an unknown --format instead of falling through."""

    def test_bogus_format_is_rejected(self, tmp_path):
        left = _write_ir(tmp_path, "left.json", _minimal_ir())
        right = _write_ir(tmp_path, "right.json", _minimal_ir())
        result = runner.invoke(
            app,
            ["ir", "diff", "-l", left, "-r", right, "-f", "bogus"],
            env={"COLUMNS": "200"},
        )
        assert result.exit_code != 0
        assert "invalid --format" in result.output
        assert "event-model" in result.output
