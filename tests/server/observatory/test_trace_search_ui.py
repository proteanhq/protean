"""Tests for Trace Search UI and Recent Traces List View (#858).

Covers:
- Timeline page renders with Events/Traces tab bar
- Traces view section with search inputs and results table
- Deep link ?view=traces works
- Deep link ?view=traces&aggregate_id=... populates search fields
- Tab switching JavaScript references
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from protean.domain import Domain
from protean.server.observatory import Observatory

pytestmark = pytest.mark.no_test_domain


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    """Create an Observatory test client with a standalone domain."""
    domain = Domain(name="TraceUITests", root_path=str(tmp_path))
    domain._initialize()
    domain.init(traverse=False)

    with domain.domain_context():
        obs = Observatory(domains=[domain])
        yield TestClient(obs.app)


# ---------------------------------------------------------------------------
# Tab bar
# ---------------------------------------------------------------------------


class TestTabBar:
    """The timeline page has an Events/Traces tab bar."""

    def test_has_events_tab(self, client):
        html = client.get("/timeline").text
        assert 'id="tab-events"' in html

    def test_has_traces_tab(self, client):
        html = client.get("/timeline").text
        assert 'id="tab-traces"' in html

    def test_events_tab_is_active_by_default(self, client):
        html = client.get("/timeline").text
        assert 'id="tab-events"' in html
        # The tab-active class should be on the events tab
        # Extract the events tab element
        idx = html.index('id="tab-events"')
        # Look backward for the opening tag
        start = html.rfind("<button", 0, idx)
        end = html.index(">", idx)
        tag = html[start : end + 1]
        assert "tab-active" in tag

    def test_traces_tab_not_active_by_default(self, client):
        html = client.get("/timeline").text
        idx = html.index('id="tab-traces"')
        start = html.rfind("<button", 0, idx)
        end = html.index(">", idx)
        tag = html[start : end + 1]
        assert "tab-active" not in tag


# ---------------------------------------------------------------------------
# Traces view section
# ---------------------------------------------------------------------------


class TestTracesViewSection:
    """The traces view section has search inputs and results table."""

    def test_has_traces_view_container(self, client):
        html = client.get("/timeline").text
        assert 'id="traces-view"' in html

    def test_traces_view_starts_hidden(self, client):
        html = client.get("/timeline").text
        assert 'id="traces-view" class="hidden"' in html

    def test_has_aggregate_id_search_input(self, client):
        html = client.get("/timeline").text
        assert 'id="trace-search-aggregate-id"' in html

    def test_has_event_type_search_input(self, client):
        html = client.get("/timeline").text
        assert 'id="trace-search-event-type"' in html

    def test_has_command_type_search_input(self, client):
        html = client.get("/timeline").text
        assert 'id="trace-search-command-type"' in html

    def test_has_stream_category_search_input(self, client):
        html = client.get("/timeline").text
        assert 'id="trace-search-stream-category"' in html

    def test_has_clear_search_button(self, client):
        html = client.get("/timeline").text
        assert 'id="btn-clear-trace-search"' in html

    def test_has_traces_table(self, client):
        html = client.get("/timeline").text
        assert 'id="traces-tbody"' in html

    def test_traces_table_has_expected_columns(self, client):
        html = client.get("/timeline").text
        assert "Root Type" in html
        assert "Event Count" in html
        assert "Streams" in html
        assert "Started At" in html

    def test_has_traces_empty_placeholder(self, client):
        html = client.get("/timeline").text
        assert 'id="traces-empty"' in html


# ---------------------------------------------------------------------------
# JavaScript references
# ---------------------------------------------------------------------------


class TestJavaScriptReferences:
    """The timeline.js file contains expected trace-related functions."""

    def test_js_has_fetch_recent_traces(self, client):
        resp = client.get("/static/js/timeline.js")
        assert resp.status_code == 200
        assert "fetchRecentTraces" in resp.text

    def test_js_has_search_traces(self, client):
        resp = client.get("/static/js/timeline.js")
        assert resp.status_code == 200
        assert "searchTraces" in resp.text

    def test_js_has_render_traces_table(self, client):
        resp = client.get("/static/js/timeline.js")
        assert resp.status_code == 200
        assert "_renderTracesTable" in resp.text

    def test_js_has_traces_view_handling(self, client):
        resp = client.get("/static/js/timeline.js")
        assert resp.status_code == 200
        assert "traces-view" in resp.text

    def test_js_handles_view_traces_deep_link(self, client):
        resp = client.get("/static/js/timeline.js")
        assert resp.status_code == 200
        # Check that the _readURL function handles ?view=traces
        assert "'traces'" in resp.text

    def test_js_has_tab_event_binding(self, client):
        resp = client.get("/static/js/timeline.js")
        assert resp.status_code == 200
        assert "tab-events" in resp.text
        assert "tab-traces" in resp.text


# ---------------------------------------------------------------------------
# Deep linking
# ---------------------------------------------------------------------------


class TestDeepLinking:
    """The timeline page supports ?view=traces deep linking via JS."""

    def test_timeline_page_loads_with_view_traces_param(self, client):
        """The page should load successfully even with ?view=traces."""
        resp = client.get("/timeline?view=traces")
        assert resp.status_code == 200
        # The traces view container should be in the HTML
        assert 'id="traces-view"' in resp.text

    def test_timeline_page_loads_with_traces_search_params(self, client):
        """The page should load with search parameters in the URL."""
        resp = client.get("/timeline?view=traces&aggregate_id=abc-123")
        assert resp.status_code == 200
        assert 'id="traces-view"' in resp.text
