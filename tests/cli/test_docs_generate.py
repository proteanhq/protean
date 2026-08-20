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

import protean
from protean.cli.docs import app
from protean.ir.generators.llms import generate_llms_txt

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


def _multi_element_ir(*, swap: bool = False) -> dict[str, Any]:
    """An IR with multiple clusters, commands, events, handlers, and
    projections, all inserted out of sorted order.

    ``swap`` reverses every dict's insertion order. Because the generator sorts
    every traversal, both orderings must render byte-identical output, so this
    fixture is what actually exercises the sorting.
    """

    def _d(items: list[tuple[str, Any]]) -> dict[str, Any]:
        return dict(reversed(items) if swap else items)

    zebra = _cluster(
        aggregate_name="Zebra",
        commands=_d(
            [
                ("app.ShipZebra", _command("Z.ShipZebra.v1")),
                ("app.CancelZebra", _command("Z.CancelZebra.v1")),
            ]
        ),
        events=_d(
            [
                ("app.ZebraShipped", _event("Z.ZebraShipped.v1")),
                ("app.ZebraCancelled", _event("Z.ZebraCancelled.v1")),
            ]
        ),
        command_handlers=_d(
            [("app.ZebraCommandHandler", _command_handler("Z.ShipZebra.v1"))]
        ),
        event_handlers=_d([("app.ZebraEventHandler", {})]),
    )
    apple = _cluster(
        aggregate_name="Apple",
        commands=_d([("app.PickApple", _command("A.PickApple.v1"))]),
    )
    return _ir(
        clusters=_d([("app.Zebra", zebra), ("app.Apple", apple)]),
        projections=_d(
            [
                ("app.ZSummary", {"projection": {"name": "ZSummary"}}),
                ("app.ASummary", {"projection": {"name": "ASummary"}}),
            ]
        ),
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
# Test: llms.txt context pack (--type=llms)
# ---------------------------------------------------------------------------


class TestLlmsType:
    """Tests for the ``--type=llms`` versioned context pack."""

    @pytest.fixture()
    def ir_file(self, tmp_path) -> Path:
        path = tmp_path / "test-ir.json"
        path.write_text(json.dumps(_minimal_ir()), encoding="utf-8")
        return path

    def test_framework_layer_runs_with_no_source(self):
        """--type=llms needs neither --domain nor --ir: it emits the framework layer."""
        result = runner.invoke(app, ["generate", "--type=llms"])
        assert result.exit_code == 0
        # H1 names Protean and carries the installed version.
        assert f"# Protean {protean.__version__}" in result.output
        # Core-documentation links to the areas --type=all covers.
        assert "## Core documentation" in result.output
        assert (
            "https://docs.proteanhq.com/guides/domain-definition/aggregates/"
            in result.output
        )
        assert (
            "https://docs.proteanhq.com/guides/domain-definition/events/"
            in result.output
        )
        assert (
            "https://docs.proteanhq.com/guides/change-state/command-handlers/"
            in result.output
        )
        assert (
            "https://docs.proteanhq.com/guides/consume-state/event-handlers/"
            in result.output
        )
        assert "https://docs.proteanhq.com/guides/evolving-events/" in result.output

    def test_no_source_run_has_no_project_overlay(self):
        """With no source, only the framework layer renders: no project overlay."""
        result = runner.invoke(app, ["generate", "--type=llms"])
        assert result.exit_code == 0
        assert "## Project" not in result.output

    def test_project_overlay_lists_ir_elements(self, ir_file):
        """With an IR, the overlay names the project's aggregate, command, event, handler."""
        result = runner.invoke(app, ["generate", f"--ir={ir_file}", "--type=llms"])
        assert result.exit_code == 0
        # Framework layer is still present...
        assert f"# Protean {protean.__version__}" in result.output
        # ...and the overlay names the project and its elements.
        assert "## Project: test" in result.output
        assert "**Order** (`app.Order`)" in result.output
        assert "Commands: PlaceOrder" in result.output
        assert "Events: OrderPlaced" in result.output
        assert "Handlers: OrderCommandHandler" in result.output
        # The minimal IR has no projections, so the subsection is absent.
        assert "### Projections" not in result.output

    def test_overlay_lists_projections(self, tmp_path):
        """A projection in the IR renders under a Projections subsection."""
        ir_file = tmp_path / "em-ir.json"
        ir_file.write_text(json.dumps(_event_model_ir()), encoding="utf-8")
        result = runner.invoke(app, ["generate", f"--ir={ir_file}", "--type=llms"])
        assert result.exit_code == 0
        assert "### Projections" in result.output
        assert "**OrderSummary** (`app.OrderSummary`)" in result.output

    def test_version_string_is_named(self):
        """The literal installed version substring appears in the output."""
        result = runner.invoke(app, ["generate", "--type=llms"])
        assert result.exit_code == 0
        assert protean.__version__ in result.output

    def test_overlay_renders_elements_in_sorted_order(self):
        """Clusters, commands, events, handlers, and projections render in
        sorted order regardless of the IR's insertion order.

        The fixture inserts every element out of order, so this fails if any
        traversal drops its ``sorted()``.
        """
        out = generate_llms_txt(_multi_element_ir(), version="9.9.9")
        # Non-empty guard: both clusters actually rendered.
        assert "app.Apple" in out and "app.Zebra" in out
        # Clusters sorted by FQN: Apple before Zebra despite Zebra inserted first.
        assert out.index("app.Apple") < out.index("app.Zebra")
        # Commands sorted within the Zebra cluster.
        assert out.index("CancelZebra") < out.index("ShipZebra")
        # Events sorted within the Zebra cluster.
        assert out.index("ZebraCancelled") < out.index("ZebraShipped")
        # Command and event handlers merged and sorted (exercises event_handlers).
        assert "Handlers: ZebraCommandHandler, ZebraEventHandler" in out
        # Projections sorted by FQN.
        assert out.index("ASummary") < out.index("ZSummary")

    def test_byte_stable_across_insertion_order_and_volatile_fields(self):
        """The same project renders identical bytes no matter the IR dict's
        insertion order or its volatile top-level fields."""
        ir_a = _multi_element_ir(swap=False)
        ir_a["generated_at"] = "2020-01-01T00:00:00Z"
        ir_a["checksum"] = "aaaa"
        ir_b = _multi_element_ir(swap=True)
        ir_b["generated_at"] = "2099-12-31T23:59:59Z"
        ir_b["checksum"] = "zzzz"

        out_a = generate_llms_txt(ir_a, version="9.9.9")
        out_b = generate_llms_txt(ir_b, version="9.9.9")
        # Non-empty guard: the overlay actually rendered content.
        assert "app.Zebra" in out_a and "app.Apple" in out_a
        # Same content, different insertion order and volatile fields -> same bytes.
        assert out_a == out_b
        # Volatile timestamps never leak into the render.
        assert "2020-01-01" not in out_a
        assert "2099-12-31" not in out_b

    def test_byte_stable_no_source(self):
        """The framework layer renders identical, non-empty bytes each time."""
        first = generate_llms_txt(None, version="9.9.9")
        second = generate_llms_txt(None, version="9.9.9")
        assert first == second
        # Non-vacuous: the framework layer actually carries the version and a link.
        assert "# Protean 9.9.9" in first
        assert (
            "https://docs.proteanhq.com/guides/domain-definition/aggregates/" in first
        )

    def test_overlay_falls_back_to_fqn_and_renders_bare_project_heading(self):
        """No domain name renders a bare '## Project'; an unnamed aggregate and
        projection fall back to their FQN short name, and empty element lines
        are omitted."""
        ir = _ir(
            clusters={
                "app.Widget": {
                    "aggregate": {},  # no name -> fall back to short_name
                    "commands": {},
                    "events": {},
                    "command_handlers": {},
                    "event_handlers": {},
                },
            },
            projections={
                "app.WidgetView": {"projection": {}},  # no name -> fall back
            },
        )
        ir["domain"] = {}  # no name -> bare heading
        out = generate_llms_txt(ir, version="9.9.9")
        assert "## Project\n" in out
        assert "## Project:" not in out
        assert "**Widget** (`app.Widget`)" in out
        assert "**WidgetView** (`app.WidgetView`)" in out
        # No commands/events/handlers on the cluster -> those lines are omitted.
        assert "Commands:" not in out
        assert "Events:" not in out
        assert "Handlers:" not in out

    def test_both_domain_and_ir_still_aborts(self, ir_file):
        """--type=llms keeps --domain and --ir mutually exclusive."""
        result = runner.invoke(
            app,
            ["generate", "--type=llms", "--domain=my_app", f"--ir={ir_file}"],
        )
        assert result.exit_code != 0
        assert "--domain and --ir are mutually exclusive" in result.output

    def test_cluster_option_rejected(self):
        """--cluster is not valid for --type=llms."""
        result = runner.invoke(app, ["generate", "--type=llms", "--cluster=app.Order"])
        assert result.exit_code != 0
        assert "--cluster can only be used with" in result.output

    def test_annotations_option_rejected(self, ir_file):
        """--annotations is only valid for --type=event-model."""
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=llms", "--annotations=x.toml"],
        )
        assert result.exit_code != 0
        assert "--annotations can only be used with --type=event-model" in result.output

    def test_mermaid_format_rejected(self):
        """llms emits a Markdown context pack, so --format=mermaid is refused."""
        result = runner.invoke(app, ["generate", "--type=llms", "--format=mermaid"])
        assert result.exit_code != 0
        assert "--format=mermaid is not supported for --type=llms" in result.output

    def test_no_source_relaxation_is_scoped_to_llms(self):
        """A non-llms type with no source still aborts: the relaxation is llms-only."""
        result = runner.invoke(app, ["generate", "--type=catalog"])
        assert result.exit_code != 0
        assert "provide either --domain or --ir" in result.output

    def test_llms_not_bundled_into_type_all(self, ir_file):
        """--type=all must not carry the llms framework layer."""
        result = runner.invoke(app, ["generate", f"--ir={ir_file}", "--type=all"])
        assert result.exit_code == 0
        assert "## Core documentation" not in result.output
        assert f"# Protean {protean.__version__}" not in result.output

    def test_write_to_file(self, ir_file, tmp_path):
        """--type=llms honors --output."""
        out_file = tmp_path / "llms.txt"
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=llms", f"--output={out_file}"],
        )
        assert result.exit_code == 0
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert f"# Protean {protean.__version__}" in content
        assert "## Project: test" in content

    def test_empty_ir_overlay_reports_no_clusters(self, tmp_path):
        """An IR with no clusters still renders the overlay with a sentinel."""
        ir_file = tmp_path / "empty.json"
        ir_file.write_text(json.dumps(_ir()), encoding="utf-8")
        result = runner.invoke(app, ["generate", f"--ir={ir_file}", "--type=llms"])
        assert result.exit_code == 0
        assert "## Project: test" in result.output
        assert "_No aggregate clusters._" in result.output

    def test_bare_empty_ir_file_still_renders_overlay(self, tmp_path):
        """An IR file holding just `{}` is a valid source, so the overlay
        renders with its sentinel instead of being silently skipped."""
        ir_file = tmp_path / "bare.json"
        ir_file.write_text("{}", encoding="utf-8")
        result = runner.invoke(app, ["generate", f"--ir={ir_file}", "--type=llms"])
        assert result.exit_code == 0
        # No domain name in the IR -> bare heading, but the overlay is there.
        assert "## Project\n" in result.output
        assert "_No aggregate clusters._" in result.output

    def test_empty_dict_ir_differs_from_no_source(self):
        """`{}` (a source that happens to be empty) and None (no source at all)
        are different inputs: only the former gets a project overlay."""
        with_source = generate_llms_txt({}, version="9.9.9")
        no_source = generate_llms_txt(None, version="9.9.9")
        assert "## Project" in with_source
        assert "_No aggregate clusters._" in with_source
        assert "## Project" not in no_source
        # Both still carry the framework layer.
        assert "# Protean 9.9.9" in with_source
        assert "# Protean 9.9.9" in no_source


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
# Test: Event-model annotations (--annotations)
# ---------------------------------------------------------------------------


def _write_ir(tmp_path: Path, name: str = "event-model-ir.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(_event_model_ir()), encoding="utf-8")
    return path


class TestEventModelAnnotations:
    """Tests for the ``--annotations`` layer on ``--type=event-model``."""

    def _run(self, ir_file: Path, *extra: str):
        return runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", "--type=event-model", *extra],
        )

    def test_ac1_aggregate_note_merges_into_its_slice(self, tmp_path):
        """A note keyed by the aggregate FQN renders in that slice section."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        ann.write_text(
            '[annotations."app.Order"]\n'
            'note = "Orders are the fulfillment boundary."\n',
            encoding="utf-8",
        )
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code == 0
        assert "## Event Model: Order" in result.output
        assert "Orders are the fulfillment boundary." in result.output
        # The note leads the diagram fence, sitting after the GWT.
        assert result.output.index("Orders are the fulfillment boundary.") < (
            result.output.index("```mermaid")
        )

    def test_ac1_note_absent_from_other_slices(self, tmp_path):
        """A note keyed to one aggregate does not appear in a sibling slice."""
        ir = _ir(
            clusters={
                "app.Order": _cluster(
                    aggregate_name="Order",
                    events={"app.OrderPlaced": _event("Ordering.OrderPlaced.v1")},
                ),
                "app.Shipment": _cluster(
                    aggregate_name="Shipment",
                    events={"app.OrderShipped": _event("Shipping.OrderShipped.v1")},
                ),
            },
        )
        ir_file = tmp_path / "two.json"
        ir_file.write_text(json.dumps(ir), encoding="utf-8")
        ann = tmp_path / "annotations.toml"
        ann.write_text(
            '[annotations."app.Order"]\nnote = "Only for Order."\n',
            encoding="utf-8",
        )
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code == 0
        order_section = result.output.index("## Event Model: Order")
        shipment_section = result.output.index("## Event Model: Shipment")
        note_at = result.output.index("Only for Order.")
        # The note sits inside the Order section, before the Shipment heading.
        assert order_section < note_at < shipment_section

    def test_note_renders_owner_when_present(self, tmp_path):
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        ann.write_text(
            '[annotations."app.Order"]\n'
            'note = "The boundary."\n'
            'owner = "Fulfillment"\n',
            encoding="utf-8",
        )
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code == 0
        assert "> **Note:** The boundary." in result.output
        assert "> **Owner:** Fulfillment" in result.output

    def test_ac4_unmatched_annotation_is_reported(self, tmp_path):
        """A key matching no element lands in the unmatched report."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        ann.write_text(
            '[annotations."app.Ghost"]\nnote = "Orphaned by a rename."\n',
            encoding="utf-8",
        )
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code == 0
        assert "## Unmatched annotations" in result.output
        assert "- `app.Ghost`" in result.output

    def test_ac4_unmatched_report_does_not_disturb_matched_slices(self, tmp_path):
        """A stray key adds only the report; the slices match the no-key render."""
        ir_file = _write_ir(tmp_path)
        baseline = self._run(ir_file)
        assert baseline.exit_code == 0

        ann = tmp_path / "annotations.toml"
        ann.write_text(
            '[annotations."app.Ghost"]\nnote = "Orphaned."\n',
            encoding="utf-8",
        )
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code == 0
        # Everything up to the appended report is byte-identical to the
        # no-annotation render.
        head = result.output[: result.output.index("## Unmatched annotations")]
        assert head.rstrip("\n") == baseline.output.rstrip("\n")

    def test_ac5_no_annotations_render_is_byte_identical(self, tmp_path):
        """With no annotations file, the render carries no annotation artifacts."""
        ir_file = _write_ir(tmp_path)
        no_file = self._run(ir_file)
        empty_file = tmp_path / "empty.toml"
        empty_file.write_text("[annotations]\n", encoding="utf-8")
        with_empty = self._run(ir_file, f"--annotations={empty_file}")
        assert no_file.exit_code == 0
        assert with_empty.exit_code == 0
        assert no_file.output == with_empty.output
        assert "**Note:**" not in no_file.output
        assert "Unmatched annotations" not in no_file.output

    def test_ac6_malformed_file_aborts_naming_the_file(self, tmp_path):
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        ann.write_text("this is = = not valid toml", encoding="utf-8")
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code != 0
        # rich wraps the path across lines; join before checking.
        assert str(ann) in result.output.replace("\n", "")
        assert "Invalid TOML" in result.output

    def test_ac6_malformed_file_writes_no_output(self, tmp_path):
        """A parse error aborts before the --output target is written."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        ann.write_text("broken = = toml", encoding="utf-8")
        out_file = tmp_path / "out.md"
        result = self._run(ir_file, f"--annotations={ann}", f"--output={out_file}")
        assert result.exit_code != 0
        # The abort names the reason, not just a non-zero exit: this pins the
        # parse-abort path rather than any non-zero exit (e.g. an unknown option).
        assert "Invalid TOML" in result.output
        assert not out_file.exists()

    def test_invalid_entry_shape_aborts(self, tmp_path):
        """An entry without a string note is rejected, naming the file."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        # note is a number, not a string.
        ann.write_text('[annotations."app.Order"]\nnote = 42\n', encoding="utf-8")
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code != 0
        assert str(ann) in result.output.replace("\n", "")
        assert "string 'note'" in result.output

    def test_non_utf8_file_aborts_naming_the_file(self, tmp_path):
        """A mis-encoded file aborts with a message naming the file (AC6)."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        # A latin-1 accented byte (0xe9) is not valid UTF-8.
        ann.write_bytes(b'[annotations."app.Order"]\nnote = "caf\xe9"\n')
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code != 0
        assert str(ann) in result.output.replace("\n", "")
        assert "not valid UTF-8" in result.output

    def test_empty_note_aborts(self, tmp_path):
        """A whitespace-only note is rejected: note is a required content field."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        ann.write_text('[annotations."app.Order"]\nnote = "   "\n', encoding="utf-8")
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code != 0
        assert str(ann) in result.output.replace("\n", "")
        assert "non-empty string 'note'" in result.output

    def test_note_keyed_by_a_drawn_consumer_renders(self, tmp_path):
        """A note keyed by a projector FQN renders in the slice that draws it."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        ann.write_text(
            '[annotations."app.OrderSummaryProjector"]\n'
            'note = "Feeds the ops dashboard."\n',
            encoding="utf-8",
        )
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code == 0
        assert "Feeds the ops dashboard." in result.output
        assert "## Unmatched annotations" not in result.output

    def test_owner_newline_stays_inside_the_blockquote(self, tmp_path):
        """An owner with an embedded newline cannot forge a top-level heading."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        ann.write_text(
            '[annotations."app.Order"]\n'
            'note = "The boundary."\n'
            'owner = "Alice\\n## Forged Heading"\n',
            encoding="utf-8",
        )
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code == 0
        assert "> ## Forged Heading" in result.output
        # The forged heading never appears as a live top-level heading.
        assert "\n## Forged Heading" not in result.output

    def test_invalid_owner_type_aborts(self, tmp_path):
        """An owner that is not a string is rejected, naming the file."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        ann.write_text(
            '[annotations."app.Order"]\nnote = "x"\nowner = 7\n',
            encoding="utf-8",
        )
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code != 0
        assert str(ann) in result.output.replace("\n", "")
        assert "'owner'" in result.output

    def test_annotations_key_not_a_table_aborts(self, tmp_path):
        """A top-level `annotations` that is not a table is rejected."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        ann.write_text('annotations = "just a string"\n', encoding="utf-8")
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code != 0
        assert "'annotations'" in result.output
        assert "must be a table" in result.output

    def test_entry_not_a_table_aborts(self, tmp_path):
        """An annotation value that is not a table is rejected."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        # A bare key under [annotations] parses to a string value, not a table.
        ann.write_text(
            '[annotations]\n"app.Order" = "just a string"\n', encoding="utf-8"
        )
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code != 0
        assert "must be a table" in result.output

    def test_unreadable_path_aborts(self, tmp_path):
        """A path that exists but cannot be read as a file aborts cleanly."""
        ir_file = _write_ir(tmp_path)
        # A directory passes the exists() check but fails read_bytes().
        ann_dir = tmp_path / "annotations.toml"
        ann_dir.mkdir()
        result = self._run(ir_file, f"--annotations={ann_dir}")
        assert result.exit_code != 0
        assert "Could not read" in result.output

    def test_missing_explicit_path_aborts(self, tmp_path):
        """An explicit --annotations path that does not exist is an error."""
        ir_file = _write_ir(tmp_path)
        missing = tmp_path / "nope.toml"
        result = self._run(ir_file, f"--annotations={missing}")
        assert result.exit_code != 0
        assert str(missing) in result.output.replace("\n", "")
        assert "not found" in result.output

    def test_ac7_override_reads_the_given_path(self, tmp_path):
        """--annotations at a non-default path renders its notes."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "custom" / "notes.toml"
        ann.parent.mkdir()
        ann.write_text(
            '[annotations."app.Order"]\nnote = "From a custom path."\n',
            encoding="utf-8",
        )
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code == 0
        assert "From a custom path." in result.output

    def test_default_path_is_read_when_present(self, tmp_path, monkeypatch):
        """.protean/annotations.toml is read without --annotations."""
        monkeypatch.chdir(tmp_path)
        ir_file = Path("ir.json")
        ir_file.write_text(json.dumps(_event_model_ir()), encoding="utf-8")
        protean_dir = Path(".protean")
        protean_dir.mkdir()
        (protean_dir / "annotations.toml").write_text(
            '[annotations."app.Order"]\nnote = "From the default path."\n',
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            ["generate", "--ir=ir.json", "--type=event-model"],
        )
        assert result.exit_code == 0
        assert "From the default path." in result.output

    def test_default_path_absent_is_the_silent_no_annotations_case(
        self, tmp_path, monkeypatch
    ):
        """With no .protean/annotations.toml and no override, nothing is read."""
        monkeypatch.chdir(tmp_path)
        ir_file = Path("ir.json")
        ir_file.write_text(json.dumps(_event_model_ir()), encoding="utf-8")
        assert not Path(".protean").exists()
        result = runner.invoke(
            app,
            ["generate", "--ir=ir.json", "--type=event-model"],
        )
        assert result.exit_code == 0
        assert "**Note:**" not in result.output
        assert "Unmatched annotations" not in result.output

    def test_override_wins_over_the_default_path(self, tmp_path, monkeypatch):
        """When --annotations is given, the default path is not read."""
        monkeypatch.chdir(tmp_path)
        ir_file = Path("ir.json")
        ir_file.write_text(json.dumps(_event_model_ir()), encoding="utf-8")
        protean_dir = Path(".protean")
        protean_dir.mkdir()
        (protean_dir / "annotations.toml").write_text(
            '[annotations."app.Order"]\nnote = "DEFAULT PATH NOTE."\n',
            encoding="utf-8",
        )
        override = Path("override.toml")
        override.write_text(
            '[annotations."app.Order"]\nnote = "OVERRIDE NOTE."\n',
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            [
                "generate",
                "--ir=ir.json",
                "--type=event-model",
                "--annotations=override.toml",
            ],
        )
        assert result.exit_code == 0
        assert "OVERRIDE NOTE." in result.output
        assert "DEFAULT PATH NOTE." not in result.output

    def test_annotations_rejected_for_other_types(self, tmp_path):
        """--annotations only applies to --type=event-model."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        ann.write_text('[annotations."app.Order"]\nnote = "x"\n', encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "generate",
                f"--ir={ir_file}",
                "--type=clusters",
                f"--annotations={ann}",
            ],
        )
        assert result.exit_code != 0
        assert "--annotations can only be used with --type=event-model" in result.output

    def test_dotted_fqn_key_matches(self, tmp_path):
        """A realistic dotted, quoted FQN key attaches to its element."""
        ir = _ir(
            clusters={
                "myproj.example.aggregate.Order": _cluster(
                    aggregate_name="Order",
                    events={"app.OrderPlaced": _event("Ordering.OrderPlaced.v1")},
                ),
            },
        )
        ir_file = tmp_path / "dotted.json"
        ir_file.write_text(json.dumps(ir), encoding="utf-8")
        ann = tmp_path / "annotations.toml"
        ann.write_text(
            '[annotations."myproj.example.aggregate.Order"]\n'
            'note = "Keyed by the full dotted FQN."\n',
            encoding="utf-8",
        )
        result = self._run(ir_file, f"--annotations={ann}")
        assert result.exit_code == 0
        assert "Keyed by the full dotted FQN." in result.output
        assert "Unmatched annotations" not in result.output

    def test_mermaid_mode_keeps_flowchart_and_appends_report(self, tmp_path):
        """Mermaid mode leaves the flowchart body and appends only the report."""
        ir_file = _write_ir(tmp_path)
        ann = tmp_path / "annotations.toml"
        ann.write_text(
            '[annotations."app.Order"]\nnote = "Matched note."\n'
            '[annotations."app.Ghost"]\nnote = "Stray note."\n',
            encoding="utf-8",
        )
        result = self._run(ir_file, "--format=mermaid", f"--annotations={ann}")
        assert result.exit_code == 0
        # The flowchart body is unchanged: no note prose inside it.
        assert "flowchart LR" in result.output
        assert "Matched note." not in result.output
        # Only the unmatched report is appended, after the flowchart.
        assert "## Unmatched annotations" in result.output
        assert "- `app.Ghost`" in result.output
        assert result.output.index("flowchart LR") < result.output.index(
            "## Unmatched annotations"
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
