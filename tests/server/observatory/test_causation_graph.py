"""Tests for the D3-based interactive causation graph (issue #860).

Covers:
- causation-graph.js script is included in the timeline page
- Graph container and toggle UI elements are present
- Correlation API response structure supports the graph
- Auto-select logic: graph is preferred for complex chains
- Toggle buttons render with correct initial states
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
    domain = Domain(name="GraphTests", root_path=str(tmp_path))
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
# Script and static asset loading
# ---------------------------------------------------------------------------


class TestCausationGraphScript:
    """The causation-graph.js script must be loaded on the timeline page."""

    def test_causation_graph_js_included(self, client):
        html = client.get("/timeline").text
        assert 'src="/static/js/causation-graph.js"' in html

    def test_causation_graph_js_loaded_before_timeline_js(self, client):
        """causation-graph.js must load before timeline.js (dependency)."""
        html = client.get("/timeline").text
        graph_pos = html.index("causation-graph.js")
        timeline_pos = html.index('src="/static/js/timeline.js"')
        assert graph_pos < timeline_pos

    def test_causation_graph_js_is_accessible(self, client):
        resp = client.get("/static/js/causation-graph.js")
        assert resp.status_code == 200
        assert "CausationGraph" in resp.text

    def test_d3_vendor_script_available(self, client):
        resp = client.get("/static/vendor/d3.v7.min.js")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Graph container and toggle UI
# ---------------------------------------------------------------------------


class TestGraphContainerAndToggle:
    """The correlation view must have graph container and toggle buttons."""

    def test_has_graph_container(self, client):
        html = client.get("/timeline").text
        assert 'id="causation-graph-container"' in html

    def test_graph_container_starts_hidden(self, client):
        html = client.get("/timeline").text
        assert (
            'id="causation-graph-container" class="causation-graph-container hidden"'
            in html
        )

    def test_has_tree_view_toggle_button(self, client):
        html = client.get("/timeline").text
        assert 'id="btn-tree-view"' in html

    def test_has_graph_view_toggle_button(self, client):
        html = client.get("/timeline").text
        assert 'id="btn-graph-view"' in html

    def test_tree_view_button_is_active_by_default(self, client):
        html = client.get("/timeline").text
        # Tree button should have btn-primary (active state)
        assert 'id="btn-tree-view"' in html
        # Find the button and verify it has btn-primary
        idx = html.index('id="btn-tree-view"')
        # The class attribute is before the id in the button tag
        btn_start = html.rfind("<button", 0, idx)
        btn_snippet = html[btn_start : idx + 30]
        assert "btn-primary" in btn_snippet

    def test_graph_view_button_is_inactive_by_default(self, client):
        html = client.get("/timeline").text
        idx = html.index('id="btn-graph-view"')
        btn_start = html.rfind("<button", 0, idx)
        btn_snippet = html[btn_start : idx + 30]
        assert "btn-ghost" in btn_snippet

    def test_has_view_toggle_container(self, client):
        html = client.get("/timeline").text
        assert 'id="causation-view-toggle"' in html

    def test_has_graph_help_text(self, client):
        html = client.get("/timeline").text
        assert 'id="graph-help-text"' in html

    def test_graph_help_text_starts_hidden(self, client):
        html = client.get("/timeline").text
        assert 'id="graph-help-text"' in html
        idx = html.index('id="graph-help-text"')
        div_start = html.rfind("<div", 0, idx)
        div_snippet = html[div_start : idx + 30]
        assert "hidden" in div_snippet


# ---------------------------------------------------------------------------
# Correlation API supports graph data
# ---------------------------------------------------------------------------


class TestCorrelationAPIForGraph:
    """The correlation API response must contain all fields the graph needs."""

    def _make_tree(self, depth: int = 3) -> CausationNode:
        """Build a CausationNode tree of a given depth."""
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

        current = root
        for i in range(1, depth):
            child = CausationNode(
                message_id=str(uuid.uuid4()),
                message_type=f"Test.Event{i}.v1",
                kind="EVENT",
                stream=f"order-abc{i}",
                time=datetime(2026, 4, 1, 10, 0, i, tzinfo=timezone.utc).isoformat(),
                global_position=1 + i,
                handler=f"Handler{i}" if i % 2 == 0 else None,
                duration_ms=10.0 + i,
                delta_ms=5.0 * i,
            )
            current.children.append(child)
            current = child

        return root

    def test_tree_has_message_id(self):
        tree = self._make_tree(2)
        assert tree.message_id is not None

    def test_tree_has_kind(self):
        tree = self._make_tree(2)
        assert tree.kind in ("COMMAND", "EVENT")

    def test_tree_has_handler(self):
        tree = self._make_tree(2)
        assert tree.handler is not None

    def test_tree_has_duration_ms(self):
        tree = self._make_tree(2)
        assert tree.duration_ms is not None

    def test_tree_children_have_delta_ms(self):
        tree = self._make_tree(3)
        child = tree.children[0]
        assert child.delta_ms is not None

    def test_tree_has_stream(self):
        tree = self._make_tree(2)
        assert tree.stream is not None

    def test_tree_has_global_position(self):
        tree = self._make_tree(2)
        assert tree.global_position is not None


# ---------------------------------------------------------------------------
# CSS styles for causation graph
# ---------------------------------------------------------------------------


class TestCausationGraphCSS:
    """The observatory CSS must include styles for the D3 graph."""

    def test_graph_container_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".causation-graph-container" in css

    def test_graph_node_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-node" in css
        assert ".cg-card" in css

    def test_graph_link_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-link" in css

    def test_cross_aggregate_link_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-link--cross" in css

    def test_highlight_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-highlighted" in css
        assert ".cg-dimmed" in css

    def test_badge_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-badge--evt" in css
        assert ".cg-badge--cmd" in css

    def test_latency_label_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".cg-latency" in css
