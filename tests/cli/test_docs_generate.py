"""Tests for ``protean docs generate`` CLI command.

Covers option combinations, mutual exclusivity, error handling,
file output, and all generator types.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from protean.cli.docs import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Minimal IR fixtures
# ---------------------------------------------------------------------------


def _field(
    kind: str = "standard",
    type: str = "String",
    **kwargs: Any,
) -> dict[str, Any]:
    return {"kind": kind, "type": type, **kwargs}


def _event(
    type_str: str = "Ordering.OrderPlaced.v1",
    *,
    fields: dict[str, Any] | None = None,
    published: bool = False,
    is_fact_event: bool = False,
) -> dict[str, Any]:
    return {
        "__type__": type_str,
        "fields": fields or {"order_id": _field()},
        "published": published,
        "is_fact_event": is_fact_event,
    }


def _command(
    type_str: str = "Ordering.PlaceOrder.v1",
    *,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "__type__": type_str,
        "fields": fields or {"order_id": _field()},
    }


def _command_handler(
    *cmd_types: str,
) -> dict[str, Any]:
    handlers = {ct: ["handle"] for ct in cmd_types}
    return {"handlers": handlers}


def _cluster(
    *,
    aggregate_name: str = "Order",
    commands: dict[str, Any] | None = None,
    events: dict[str, Any] | None = None,
    command_handlers: dict[str, Any] | None = None,
    event_handlers: dict[str, Any] | None = None,
    entities: dict[str, Any] | None = None,
    value_objects: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "aggregate": {
            "name": aggregate_name,
            "element_type": "AGGREGATE",
            "fields": {"id": _field(kind="auto", type="Auto", identifier=True)},
        },
        "commands": commands or {},
        "events": events or {},
        "command_handlers": command_handlers or {},
        "event_handlers": event_handlers or {},
        "entities": entities or {},
        "value_objects": value_objects or {},
    }


def _ir(
    *,
    clusters: dict[str, Any] | None = None,
    flows: dict[str, Any] | None = None,
    projections: dict[str, Any] | None = None,
    contracts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ir_version": "0.1.0",
        "domain": {"name": "test"},
        "clusters": clusters or {},
        "flows": flows or {},
        "projections": projections or {},
        "contracts": contracts or {},
    }


def _minimal_ir() -> dict[str, Any]:
    """An IR with one cluster, one command, one event, and a command handler."""
    return _ir(
        clusters={
            "app.Order": _cluster(
                commands={
                    "app.PlaceOrder": _command("Ordering.PlaceOrder.v1"),
                },
                events={
                    "app.OrderPlaced": _event("Ordering.OrderPlaced.v1"),
                },
                command_handlers={
                    "app.OrderCommandHandler": _command_handler(
                        "Ordering.PlaceOrder.v1"
                    ),
                },
            ),
        },
    )


# ---------------------------------------------------------------------------
# Test: Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Tests for mutual exclusivity and invalid option combos."""

    def test_no_source_provided(self):
        """Error when neither --domain nor --ir is given."""
        result = runner.invoke(app, ["generate"])
        assert result.exit_code != 0
        assert "provide either --domain or --ir" in result.output

    def test_both_domain_and_ir(self, tmp_path):
        """Error when both --domain and --ir are given."""
        ir_file = tmp_path / "test.json"
        ir_file.write_text(json.dumps(_ir()), encoding="utf-8")

        result = runner.invoke(
            app,
            ["generate", "--domain=my_app", f"--ir={ir_file}"],
        )
        assert result.exit_code != 0
        assert "--domain and --ir are mutually exclusive" in result.output

    def test_invalid_type(self, tmp_path):
        """Error for an unrecognised --type value."""
        ir_file = tmp_path / "test.json"
        ir_file.write_text(json.dumps(_ir()), encoding="utf-8")

        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=bogus"],
        )
        assert result.exit_code != 0
        assert "invalid --type" in result.output

    def test_invalid_format(self, tmp_path):
        """Error for an unrecognised --format value."""
        ir_file = tmp_path / "test.json"
        ir_file.write_text(json.dumps(_ir()), encoding="utf-8")

        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--format=html"],
        )
        assert result.exit_code != 0
        assert "invalid --format" in result.output

    def test_cluster_with_wrong_type(self, tmp_path):
        """Error when --cluster is used with --type other than clusters/all."""
        ir_file = tmp_path / "test.json"
        ir_file.write_text(json.dumps(_ir()), encoding="utf-8")

        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=events", "--cluster=app.Order"],
        )
        assert result.exit_code != 0
        assert "--cluster can only be used with" in result.output

    def test_mermaid_format_with_catalog(self, tmp_path):
        """Error when --format=mermaid is used with --type=catalog."""
        ir_file = tmp_path / "test.json"
        ir_file.write_text(json.dumps(_ir()), encoding="utf-8")

        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=catalog", "--format=mermaid"],
        )
        assert result.exit_code != 0
        assert "--format=mermaid is not supported for --type=catalog" in result.output


# ---------------------------------------------------------------------------
# Test: IR file loading
# ---------------------------------------------------------------------------


class TestIRFileLoading:
    """Tests for loading IR from a JSON file."""

    def test_load_from_file(self, tmp_path):
        """Generate from a valid IR JSON file."""
        ir_data = _minimal_ir()
        ir_file = tmp_path / "test-ir.json"
        ir_file.write_text(json.dumps(ir_data), encoding="utf-8")

        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=clusters"],
        )
        assert result.exit_code == 0
        assert "classDiagram" in result.output

    def test_missing_file(self):
        """Error when the IR file doesn't exist."""
        result = runner.invoke(
            app,
            ["generate", "--ir=/nonexistent/path.json"],
        )
        assert result.exit_code != 0

    def test_invalid_json(self, tmp_path):
        """Error when the IR file contains invalid JSON."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{", encoding="utf-8")

        result = runner.invoke(
            app,
            ["generate", f"--ir={bad_file}"],
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Test: Domain loading
# ---------------------------------------------------------------------------


class TestDomainLoading:
    """Tests for loading IR from a live domain."""

    @patch("protean.cli._ir_utils.derive_domain")
    def test_load_from_domain(self, mock_derive):
        """Generate from a live domain."""
        mock_domain = mock_derive.return_value
        mock_domain.init.return_value = None
        mock_domain.to_ir.return_value = _minimal_ir()

        result = runner.invoke(
            app,
            ["generate", "--domain=my_app", "--type=events"],
        )
        assert result.exit_code == 0
        # Per-cluster event flows use flowchart TD
        assert "flowchart TD" in result.output
        mock_derive.assert_called_once_with("my_app")
        mock_domain.init.assert_called_once()

    @patch("protean.cli._ir_utils.derive_domain")
    def test_domain_not_found(self, mock_derive):
        """Error when the domain cannot be loaded."""
        from protean.exceptions import NoDomainException

        mock_derive.side_effect = NoDomainException("no such module")

        result = runner.invoke(
            app,
            ["generate", "--domain=nonexistent"],
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Test: Individual generator types
# ---------------------------------------------------------------------------


class TestGeneratorTypes:
    """Tests for each --type option."""

    @pytest.fixture()
    def ir_file(self, tmp_path) -> Path:
        ir_data = _minimal_ir()
        path = tmp_path / "test-ir.json"
        path.write_text(json.dumps(ir_data), encoding="utf-8")
        return path

    def test_type_clusters(self, ir_file):
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=clusters"],
        )
        assert result.exit_code == 0
        assert "classDiagram" in result.output
        # Should be in markdown format by default
        assert "```mermaid" in result.output

    def test_type_events(self, ir_file):
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=events"],
        )
        assert result.exit_code == 0
        # Per-cluster event flows use flowchart TD
        assert "flowchart TD" in result.output
        assert "```mermaid" in result.output

    def test_type_handlers(self, ir_file):
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=handlers"],
        )
        assert result.exit_code == 0
        # Per-cluster command handlers use flowchart LR
        assert "flowchart LR" in result.output
        assert "```mermaid" in result.output

    def test_type_catalog(self, ir_file):
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=catalog"],
        )
        assert result.exit_code == 0
        # Catalog outputs Markdown tables, not Mermaid
        assert "## Order" in result.output
        assert "PlaceOrder" in result.output

    def test_type_all(self, ir_file):
        """--type=all produces all four sections."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=all"],
        )
        assert result.exit_code == 0
        # All four sections present
        assert "classDiagram" in result.output
        assert "flowchart LR" in result.output
        assert "flowchart TD" in result.output
        # Catalog section (Markdown tables)
        assert "PlaceOrder" in result.output


# ---------------------------------------------------------------------------
# Test: Event model slice timeline (--type=event-model)
# ---------------------------------------------------------------------------


def _event_model_ir() -> dict[str, Any]:
    """One command -> event -> projection slice (the AC1 shape)."""
    ir = _ir(
        clusters={
            "app.Order": _cluster(
                commands={
                    "app.PlaceOrder": _command("Ordering.PlaceOrder.v1"),
                },
                events={
                    "app.OrderPlaced": _event("Ordering.OrderPlaced.v1"),
                },
            ),
        },
        projections={
            "app.OrderSummary": {
                "projection": {"fqn": "app.OrderSummary", "name": "OrderSummary"},
                "projectors": {
                    "app.OrderSummaryProjector": {
                        "element_type": "PROJECTOR",
                        "fqn": "app.OrderSummaryProjector",
                        "name": "OrderSummaryProjector",
                        "projector_for": "app.OrderSummary",
                        "handlers": {"Ordering.OrderPlaced.v1": ["on_placed"]},
                    }
                },
                "queries": {},
                "query_handlers": {},
            }
        },
    )
    return ir


class TestEventModelType:
    """Tests for the ``--type=event-model`` slice timeline."""

    @pytest.fixture()
    def ir_file(self, tmp_path) -> Path:
        path = tmp_path / "event-model-ir.json"
        path.write_text(json.dumps(_event_model_ir()), encoding="utf-8")
        return path

    def test_mermaid_renders_slice(self, ir_file):
        """AC1: the command -> event -> read-model slice renders as Mermaid."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=event-model", "--format=mermaid"],
        )
        assert result.exit_code == 0
        assert "flowchart LR" in result.output
        assert "cmd_app_PlaceOrder[/PlaceOrder/]" in result.output
        assert "agg_app_Order --> evt_app_OrderPlaced" in result.output
        assert (
            "evt_app_OrderPlaced --> rm_app_Order_app_OrderSummaryProjector"
            in result.output
        )
        # Raw Mermaid: no fences
        assert "```mermaid" not in result.output

    def test_markdown_renders_same_content_in_a_fence(self, ir_file):
        """AC2: markdown renders the same slice inside a titled mermaid fence."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=event-model", "--format=markdown"],
        )
        assert result.exit_code == 0
        assert "```mermaid" in result.output
        assert "## Event Model: Order" in result.output
        assert (
            "evt_app_OrderPlaced --> rm_app_Order_app_OrderSummaryProjector"
            in result.output
        )

    def test_markdown_leads_each_slice_with_gwt(self, ir_file):
        """Markdown emits the GWT block ahead of the diagram fence."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=event-model", "--format=markdown"],
        )
        assert result.exit_code == 0
        assert "## Event Model: Order" in result.output
        assert "> **Given** Order" in result.output
        assert "> **When** PlaceOrder" in result.output
        assert "> **Then** OrderPlaced" in result.output
        # The GWT leads: it appears before the diagram fence for the slice.
        assert result.output.index("> **Given** Order") < result.output.index(
            "```mermaid"
        )

    def test_markdown_interleaves_gwt_and_fence_per_slice(self, tmp_path):
        """Each slice leads with its own GWT then its own fence, in order."""
        ir = _ir(
            clusters={
                "app.Order": _cluster(
                    aggregate_name="Order",
                    commands={"app.PlaceOrder": _command("Ordering.PlaceOrder.v1")},
                    events={"app.OrderPlaced": _event("Ordering.OrderPlaced.v1")},
                ),
                "app.Shipment": _cluster(
                    aggregate_name="Shipment",
                    commands={"app.ShipOrder": _command("Shipping.ShipOrder.v1")},
                    events={"app.OrderShipped": _event("Shipping.OrderShipped.v1")},
                ),
            },
        )
        ir_path = tmp_path / "two-cluster-ir.json"
        ir_path.write_text(json.dumps(ir), encoding="utf-8")
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_path}", "--type=event-model", "--format=markdown"],
        )
        assert result.exit_code == 0
        out = result.output
        # Slices render in sorted FQN order: Order then Shipment. Each heading
        # is followed by its own GWT and then its own fence, before the next
        # heading, so no GWT block is orphaned or attached to the wrong slice.
        order_head = out.index("## Event Model: Order")
        order_given = out.index("> **Given** Order")
        order_when = out.index("> **When** PlaceOrder")
        order_fence = out.index("```mermaid", order_head)
        ship_head = out.index("## Event Model: Shipment")
        ship_given = out.index("> **Given** Shipment")
        ship_when = out.index("> **When** ShipOrder")
        ship_fence = out.index("```mermaid", ship_head)
        assert (
            order_head
            < order_given
            < order_when
            < order_fence
            < ship_head
            < ship_given
            < ship_when
            < ship_fence
        )

    def test_mermaid_has_no_gwt_prose(self, ir_file):
        """Mermaid mode is a bare flowchart: GWT is a Markdown-only feature."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=event-model", "--format=mermaid"],
        )
        assert result.exit_code == 0
        # The slice actually rendered (not empty or garbage output)...
        assert "flowchart LR" in result.output
        assert "agg_app_Order --> evt_app_OrderPlaced" in result.output
        # ...and it carries no GWT prose.
        assert "**Given**" not in result.output
        assert "**When**" not in result.output
        assert "**Then**" not in result.output

    def test_markdown_is_the_default_format(self, ir_file):
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=event-model"],
        )
        assert result.exit_code == 0
        assert "```mermaid" in result.output
        assert "## Event Model: Order" in result.output

    def test_write_to_file(self, ir_file, tmp_path):
        out_file = tmp_path / "event-model.md"
        result = runner.invoke(
            app,
            [
                "generate",
                f"--ir={ir_file}",
                "--type=event-model",
                f"--output={out_file}",
            ],
        )
        assert result.exit_code == 0
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "## Event Model: Order" in content

    def test_empty_ir_renders_sentinel(self, tmp_path):
        ir_file = tmp_path / "empty.json"
        ir_file.write_text(json.dumps(_ir()), encoding="utf-8")
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=event-model", "--format=mermaid"],
        )
        assert result.exit_code == 0
        assert result.output.strip() == "flowchart LR"

    def test_not_bundled_into_type_all(self, ir_file):
        """--type=all must not carry the event-model slice section."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=all"],
        )
        assert result.exit_code == 0
        assert "## Event Model:" not in result.output

    @patch("protean.cli._ir_utils.derive_domain")
    def test_from_domain(self, mock_derive):
        """The type is reachable through the --domain path too."""
        mock_domain = mock_derive.return_value
        mock_domain.init.return_value = None
        mock_domain.to_ir.return_value = _event_model_ir()

        result = runner.invoke(
            app,
            ["generate", "--domain=my_app", "--type=event-model", "--format=mermaid"],
        )
        assert result.exit_code == 0
        assert (
            "evt_app_OrderPlaced --> rm_app_Order_app_OrderSummaryProjector"
            in result.output
        )


# ---------------------------------------------------------------------------
# Test: Output format
# ---------------------------------------------------------------------------


class TestOutputFormat:
    """Tests for --format option."""

    @pytest.fixture()
    def ir_file(self, tmp_path) -> Path:
        ir_data = _minimal_ir()
        path = tmp_path / "test-ir.json"
        path.write_text(json.dumps(ir_data), encoding="utf-8")
        return path

    def test_markdown_format(self, ir_file):
        """Default markdown format wraps diagrams in fenced code blocks."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=events", "--format=markdown"],
        )
        assert result.exit_code == 0
        assert "```mermaid" in result.output
        # Per-cluster event flow titles use "Event Flow: <name>"
        assert "## Event Flow: Order" in result.output

    def test_mermaid_format(self, ir_file):
        """--format=mermaid outputs raw Mermaid syntax."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=events", "--format=mermaid"],
        )
        assert result.exit_code == 0
        assert "flowchart LR" in result.output
        # No markdown fences
        assert "```mermaid" not in result.output
        assert "## Event Flows" not in result.output

    def test_mermaid_format_handlers(self, ir_file):
        """--format=mermaid works for handlers."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=handlers", "--format=mermaid"],
        )
        assert result.exit_code == 0
        assert "flowchart TD" in result.output
        assert "```mermaid" not in result.output

    def test_mermaid_format_clusters(self, ir_file):
        """--format=mermaid works for clusters."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=clusters", "--format=mermaid"],
        )
        assert result.exit_code == 0
        assert "classDiagram" in result.output
        assert "```mermaid" not in result.output

    def test_mermaid_format_all(self, ir_file):
        """--format=mermaid with --type=all outputs diagrams raw, catalog as markdown."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=all", "--format=mermaid"],
        )
        assert result.exit_code == 0
        assert "classDiagram" in result.output
        assert "flowchart LR" in result.output
        assert "flowchart TD" in result.output
        # Mermaid fences not present for diagrams
        assert "```mermaid" not in result.output


# ---------------------------------------------------------------------------
# Test: Cluster filtering
# ---------------------------------------------------------------------------


class TestClusterFiltering:
    """Tests for the --cluster option."""

    @pytest.fixture()
    def multi_cluster_ir_file(self, tmp_path) -> Path:
        ir_data = _ir(
            clusters={
                "app.Order": _cluster(
                    aggregate_name="Order",
                    commands={
                        "app.PlaceOrder": _command("Ordering.PlaceOrder.v1"),
                    },
                    events={
                        "app.OrderPlaced": _event("Ordering.OrderPlaced.v1"),
                    },
                ),
                "app.Payment": _cluster(
                    aggregate_name="Payment",
                    commands={
                        "app.ProcessPayment": _command("Billing.ProcessPayment.v1"),
                    },
                    events={
                        "app.PaymentProcessed": _event("Billing.PaymentProcessed.v1"),
                    },
                ),
            }
        )
        path = tmp_path / "multi-ir.json"
        path.write_text(json.dumps(ir_data), encoding="utf-8")
        return path

    def test_filter_specific_cluster(self, multi_cluster_ir_file):
        """--cluster filters to a single cluster."""
        result = runner.invoke(
            app,
            [
                "generate",
                f"--ir={multi_cluster_ir_file}",
                "--type=clusters",
                "--cluster=app.Order",
            ],
        )
        assert result.exit_code == 0
        assert "Order" in result.output
        # Payment should NOT be in output
        assert "Payment" not in result.output

    def test_filter_nonexistent_cluster(self, multi_cluster_ir_file):
        """--cluster with non-matching FQN produces empty diagram."""
        result = runner.invoke(
            app,
            [
                "generate",
                f"--ir={multi_cluster_ir_file}",
                "--type=clusters",
                "--cluster=app.Nonexistent",
            ],
        )
        assert result.exit_code == 0
        # Should still output valid Mermaid (just empty)
        assert "classDiagram" in result.output

    def test_no_cluster_filter_shows_all(self, multi_cluster_ir_file):
        """Without --cluster, all clusters are shown."""
        result = runner.invoke(
            app,
            [
                "generate",
                f"--ir={multi_cluster_ir_file}",
                "--type=clusters",
            ],
        )
        assert result.exit_code == 0
        assert "Order" in result.output
        assert "Payment" in result.output

    def test_cluster_with_type_all(self, multi_cluster_ir_file):
        """--cluster works with --type=all (filters cluster section only)."""
        result = runner.invoke(
            app,
            [
                "generate",
                f"--ir={multi_cluster_ir_file}",
                "--type=all",
                "--cluster=app.Order",
            ],
        )
        assert result.exit_code == 0
        # Cluster section should be filtered
        # Event flows use TD (per-cluster), other sections also present
        assert "flowchart TD" in result.output
        assert "classDiagram" in result.output

    def test_cluster_filter_mermaid_format(self, multi_cluster_ir_file):
        """--cluster with --format=mermaid outputs raw Mermaid for filtered cluster."""
        result = runner.invoke(
            app,
            [
                "generate",
                f"--ir={multi_cluster_ir_file}",
                "--type=clusters",
                "--cluster=app.Order",
                "--format=mermaid",
            ],
        )
        assert result.exit_code == 0
        assert "classDiagram" in result.output
        assert "Order" in result.output
        assert "```mermaid" not in result.output


# ---------------------------------------------------------------------------
# Test: File output
# ---------------------------------------------------------------------------


class TestFileOutput:
    """Tests for the --output option."""

    @pytest.fixture()
    def ir_file(self, tmp_path) -> Path:
        ir_data = _minimal_ir()
        path = tmp_path / "test-ir.json"
        path.write_text(json.dumps(ir_data), encoding="utf-8")
        return path

    def test_write_to_file(self, ir_file, tmp_path):
        """--output writes to the specified file."""
        out_file = tmp_path / "output" / "docs.md"
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", f"--output={out_file}"],
        )
        assert result.exit_code == 0
        assert "Documentation written to" in result.output
        assert out_file.exists()

        content = out_file.read_text(encoding="utf-8")
        assert "classDiagram" in content

    def test_creates_parent_directories(self, ir_file, tmp_path):
        """--output creates intermediate directories."""
        out_file = tmp_path / "deep" / "nested" / "dir" / "docs.md"
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", f"--output={out_file}"],
        )
        assert result.exit_code == 0
        assert out_file.exists()

    def test_stdout_when_no_output(self, ir_file):
        """Without --output, content goes to stdout."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=events"],
        )
        assert result.exit_code == 0
        # Per-cluster event flows use flowchart TD
        assert "flowchart TD" in result.output


# ---------------------------------------------------------------------------
# Test: Empty IR
# ---------------------------------------------------------------------------


class TestEmptyIR:
    """Tests for generating docs from an empty IR."""

    @pytest.fixture()
    def empty_ir_file(self, tmp_path) -> Path:
        ir_data = _ir()
        path = tmp_path / "empty-ir.json"
        path.write_text(json.dumps(ir_data), encoding="utf-8")
        return path

    def test_clusters_empty(self, empty_ir_file):
        result = runner.invoke(
            app,
            ["generate", f"--ir={empty_ir_file}", "--type=clusters"],
        )
        assert result.exit_code == 0
        assert "classDiagram" in result.output

    def test_clusters_empty_mermaid(self, empty_ir_file):
        """Empty clusters with --format=mermaid produces raw classDiagram."""
        result = runner.invoke(
            app,
            [
                "generate",
                f"--ir={empty_ir_file}",
                "--type=clusters",
                "--format=mermaid",
            ],
        )
        assert result.exit_code == 0
        assert "classDiagram" in result.output
        assert "```mermaid" not in result.output

    def test_events_empty(self, empty_ir_file):
        result = runner.invoke(
            app,
            ["generate", f"--ir={empty_ir_file}", "--type=events"],
        )
        assert result.exit_code == 0
        assert "flowchart LR" in result.output

    def test_handlers_empty(self, empty_ir_file):
        result = runner.invoke(
            app,
            ["generate", f"--ir={empty_ir_file}", "--type=handlers"],
        )
        assert result.exit_code == 0
        assert "flowchart TD" in result.output

    def test_catalog_empty(self, empty_ir_file):
        result = runner.invoke(
            app,
            ["generate", f"--ir={empty_ir_file}", "--type=catalog"],
        )
        assert result.exit_code == 0
        # Empty catalog produces the title and a placeholder message
        assert "# Event & Command Catalog" in result.output
        assert "_No clusters found._" in result.output

    def test_all_empty(self, empty_ir_file):
        result = runner.invoke(
            app,
            ["generate", f"--ir={empty_ir_file}", "--type=all"],
        )
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Test: Full integration with example IR
# ---------------------------------------------------------------------------


class TestFullIntegration:
    """Tests using the bundled ordering-ir.json example.

    The fixture asserts the file exists so a missing or moved example
    causes a loud failure rather than a silent skip.
    """

    @pytest.fixture()
    def ordering_ir_path(self) -> Path:
        path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "protean"
            / "ir"
            / "examples"
            / "ordering-ir.json"
        )
        assert path.exists(), f"Bundled example IR not found at {path}"
        return path

    def test_all_from_example(self, ordering_ir_path):
        """Full generation from the ordering example."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ordering_ir_path}"],
        )
        assert result.exit_code == 0
        # All four sections
        assert "classDiagram" in result.output
        assert "flowchart LR" in result.output
        assert "flowchart TD" in result.output
        assert "# Event & Command Catalog" in result.output

    def test_mermaid_from_example(self, ordering_ir_path):
        """Mermaid output from the ordering example."""
        result = runner.invoke(
            app,
            [
                "generate",
                f"--ir={ordering_ir_path}",
                "--type=events",
                "--format=mermaid",
            ],
        )
        assert result.exit_code == 0
        assert "flowchart LR" in result.output
        assert "```mermaid" not in result.output

    def test_cluster_filter_from_example(self, ordering_ir_path):
        """Cluster filter with the ordering example."""
        result = runner.invoke(
            app,
            [
                "generate",
                f"--ir={ordering_ir_path}",
                "--type=clusters",
                "--cluster=ecommerce.ordering.Order",
            ],
        )
        assert result.exit_code == 0
        assert "Order" in result.output

    def test_file_output_from_example(self, ordering_ir_path, tmp_path):
        """Write full docs from ordering example to file."""
        out_file = tmp_path / "architecture.md"
        result = runner.invoke(
            app,
            [
                "generate",
                f"--ir={ordering_ir_path}",
                f"--output={out_file}",
            ],
        )
        assert result.exit_code == 0
        assert out_file.exists()

        content = out_file.read_text(encoding="utf-8")
        assert "classDiagram" in content
        assert "flowchart LR" in content
        assert "flowchart TD" in content
        assert "# Event & Command Catalog" in content
