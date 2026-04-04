"""Tests for swimlane layout and fan-out polish (issue #861).

Covers:
- Swimlane CSS classes present in stylesheet
- Legend, timeline axis, mini-map CSS classes
- Fan-out indicator CSS class
- Lane accent bar CSS class
- Graph help text updated with swimlane mention
- CausationNode tree structure supports fan-out (multiple children)
- Tree depth and breadth calculations
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from protean.domain import Domain
from protean.port.event_store import CausationNode
from protean.server.observatory import Observatory

pytestmark = pytest.mark.no_test_domain


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def standalone_domain(tmp_path):
    """Create a standalone domain with in-memory adapters."""
    domain = Domain(name="SwimLaneTests", root_path=str(tmp_path))
    domain._initialize()
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain


@pytest.fixture
def observatory(standalone_domain):
    return Observatory(domains=[standalone_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


# ---------------------------------------------------------------------------
# Helper: build trees for testing
# ---------------------------------------------------------------------------


def _make_fan_out_tree() -> CausationNode:
    """Build a CausationNode tree with fan-out (one parent, 3 children)."""
    root = CausationNode(
        message_id=str(uuid.uuid4()),
        message_type="Test.PlaceOrder.v1",
        kind="COMMAND",
        stream="order-abc123",
        time=datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc).isoformat(),
        global_position=1,
        handler="PlaceOrderHandler",
        duration_ms=45.2,
        delta_ms=None,
    )

    for i in range(3):
        child = CausationNode(
            message_id=str(uuid.uuid4()),
            message_type=f"Test.Event{i}.v1",
            kind="EVENT",
            stream=f"{'order' if i == 0 else 'inventory'}-item{i}",
            time=datetime(2026, 4, 1, 10, 0, i + 1, tzinfo=timezone.utc).isoformat(),
            global_position=2 + i,
            handler=f"Handler{i}",
            duration_ms=10.0 + i,
            delta_ms=5.0 * (i + 1),
        )
        root.children.append(child)

    return root


def _make_deep_tree(depth: int) -> CausationNode:
    """Build a linear CausationNode chain of a given depth."""
    root = CausationNode(
        message_id=str(uuid.uuid4()),
        message_type="Test.Start.v1",
        kind="COMMAND",
        stream="workflow-root",
        time=datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc).isoformat(),
        global_position=1,
        handler="StartHandler",
        duration_ms=10.0,
        delta_ms=None,
    )

    current = root
    for i in range(1, depth):
        child = CausationNode(
            message_id=str(uuid.uuid4()),
            message_type=f"Test.Step{i}.v1",
            kind="EVENT" if i % 2 == 1 else "COMMAND",
            stream=f"workflow-step{i}",
            time=datetime(2026, 4, 1, 10, 0, i, tzinfo=timezone.utc).isoformat(),
            global_position=1 + i,
            handler=f"StepHandler{i}",
            duration_ms=5.0 + i,
            delta_ms=2.0 * i,
        )
        current.children.append(child)
        current = child

    return root


def _count_nodes(node: CausationNode) -> int:
    """Count total nodes in a tree."""
    count = 1
    for child in node.children:
        count += _count_nodes(child)
    return count


def _compute_depth(node: CausationNode) -> int:
    """Compute the depth of a tree."""
    if not node.children:
        return 1
    return 1 + max(_compute_depth(c) for c in node.children)


def _compute_max_breadth(node: CausationNode) -> int:
    """Compute the maximum fan-out (max children count) in a tree."""
    max_b = len(node.children)
    for child in node.children:
        child_b = _compute_max_breadth(child)
        if child_b > max_b:
            max_b = child_b
    return max_b


def _collect_stream_categories(node: CausationNode) -> set[str]:
    """Collect unique stream categories from a tree."""
    cats = set()
    stream = node.stream or ""
    idx = stream.find("-")
    if idx > 0:
        cats.add(stream[:idx])
    for child in node.children:
        cats.update(_collect_stream_categories(child))
    return cats


# ---------------------------------------------------------------------------
# Swimlane CSS classes
# ---------------------------------------------------------------------------


class TestSwimlaneCSSClasses:
    """The CSS must include styles for swimlane elements."""

    def test_swimlane_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-swimlane" in css

    def test_swimlane_label_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-swimlane-label" in css

    def test_lane_accent_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-lane-accent" in css


# ---------------------------------------------------------------------------
# Fan-out CSS and indicator
# ---------------------------------------------------------------------------


class TestFanOutCSS:
    """The CSS must include styles for fan-out indicators."""

    def test_fanout_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-fanout" in css


# ---------------------------------------------------------------------------
# Timeline axis CSS
# ---------------------------------------------------------------------------


class TestTimelineAxisCSS:
    """The CSS must include styles for the timeline axis."""

    def test_timeline_axis_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-timeline-axis" in css

    def test_axis_line_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-axis-line" in css

    def test_axis_tick_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-axis-tick" in css

    def test_axis_label_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-axis-label" in css


# ---------------------------------------------------------------------------
# Legend CSS
# ---------------------------------------------------------------------------


class TestLegendCSS:
    """The CSS must include styles for the legend."""

    def test_legend_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-legend" in css

    def test_legend_bg_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-legend-bg" in css

    def test_legend_text_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-legend-text" in css


# ---------------------------------------------------------------------------
# Mini-map CSS
# ---------------------------------------------------------------------------


class TestMinimapCSS:
    """The CSS must include styles for the mini-map."""

    def test_minimap_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-minimap" in css

    def test_minimap_bg_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-minimap-bg" in css

    def test_minimap_node_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-minimap-node" in css

    def test_minimap_link_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-minimap-link" in css

    def test_minimap_viewport_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-minimap-viewport" in css


# ---------------------------------------------------------------------------
# Graph help text
# ---------------------------------------------------------------------------


class TestGraphHelpText:
    """The graph help text must mention swimlanes."""

    def test_help_text_mentions_swimlanes(self, client):
        html = client.get("/timeline").text
        idx = html.index('id="graph-help-text"')
        # Read forward to find the content
        close_tag = html.index("</div>", idx)
        snippet = html[idx:close_tag]
        assert "Swimlane" in snippet or "swimlane" in snippet


# ---------------------------------------------------------------------------
# JS module includes new features
# ---------------------------------------------------------------------------


class TestCausationGraphJSFeatures:
    """The JS module must include swimlane, legend, minimap, and timeline code."""

    def test_js_has_swimlane_function(self, client):
        js = client.get("/static/js/causation-graph.js").text
        assert "_renderSwimlanes" in js

    def test_js_has_legend_function(self, client):
        js = client.get("/static/js/causation-graph.js").text
        assert "_renderLegend" in js

    def test_js_has_minimap_function(self, client):
        js = client.get("/static/js/causation-graph.js").text
        assert "_renderMinimap" in js

    def test_js_has_timeline_axis_function(self, client):
        js = client.get("/static/js/causation-graph.js").text
        assert "_renderTimelineAxis" in js

    def test_js_has_progressive_threshold(self, client):
        js = client.get("/static/js/causation-graph.js").text
        assert "PROGRESSIVE_THRESHOLD" in js

    def test_js_has_lane_map_builder(self, client):
        js = client.get("/static/js/causation-graph.js").text
        assert "_buildLaneMap" in js

    def test_js_has_fanout_indicator(self, client):
        js = client.get("/static/js/causation-graph.js").text
        assert "cg-fanout" in js

    def test_js_has_lane_accent(self, client):
        js = client.get("/static/js/causation-graph.js").text
        assert "cg-lane-accent" in js


# ---------------------------------------------------------------------------
# Fan-out tree structure
# ---------------------------------------------------------------------------


class TestFanOutTreeStructure:
    """The CausationNode tree must support fan-out (multiple children)."""

    def test_root_has_multiple_children(self):
        tree = _make_fan_out_tree()
        assert len(tree.children) == 3

    def test_fan_out_children_have_distinct_streams(self):
        tree = _make_fan_out_tree()
        streams = {c.stream for c in tree.children}
        assert len(streams) == 3

    def test_fan_out_children_have_delta_ms(self):
        tree = _make_fan_out_tree()
        for child in tree.children:
            assert child.delta_ms is not None

    def test_fan_out_children_have_handlers(self):
        tree = _make_fan_out_tree()
        for child in tree.children:
            assert child.handler is not None


# ---------------------------------------------------------------------------
# Tree depth and breadth calculations
# ---------------------------------------------------------------------------


class TestTreeMetrics:
    """Verify tree depth and breadth calculations are correct."""

    def test_single_node_depth(self):
        node = CausationNode(
            message_id="a",
            message_type="T.A.v1",
            kind="COMMAND",
            stream="s-1",
            time=None,
            global_position=1,
        )
        assert _compute_depth(node) == 1

    def test_linear_chain_depth(self):
        tree = _make_deep_tree(5)
        assert _compute_depth(tree) == 5

    def test_fan_out_depth(self):
        tree = _make_fan_out_tree()
        assert _compute_depth(tree) == 2

    def test_fan_out_breadth(self):
        tree = _make_fan_out_tree()
        assert _compute_max_breadth(tree) == 3

    def test_linear_chain_breadth(self):
        tree = _make_deep_tree(5)
        assert _compute_max_breadth(tree) == 1

    def test_total_node_count_fan_out(self):
        tree = _make_fan_out_tree()
        assert _count_nodes(tree) == 4

    def test_total_node_count_deep(self):
        tree = _make_deep_tree(10)
        assert _count_nodes(tree) == 10

    def test_stream_categories_fan_out(self):
        tree = _make_fan_out_tree()
        cats = _collect_stream_categories(tree)
        assert "order" in cats
        assert "inventory" in cats
        assert len(cats) == 2

    def test_stream_categories_single_aggregate(self):
        tree = _make_deep_tree(3)
        cats = _collect_stream_categories(tree)
        assert cats == {"workflow"}
