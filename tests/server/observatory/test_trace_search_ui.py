"""Tests for Trace Search UI and Recent Traces List View.

Tests for:
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

    @pytest.mark.parametrize("tab_id", ["tab-events", "tab-traces"])
    def test_has_tab(self, client, tab_id):
        html = client.get("/timeline").text
        assert f'id="{tab_id}"' in html

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

    @pytest.mark.parametrize(
        "element_id",
        [
            "traces-view",
            "trace-search-aggregate-id",
            "trace-search-event-type",
            "trace-search-command-type",
            "trace-search-stream-category",
            "btn-clear-trace-search",
            "traces-tbody",
            "traces-empty",
        ],
    )
    def test_has_element(self, client, element_id):
        html = client.get("/timeline").text
        assert f'id="{element_id}"' in html

    def test_traces_view_starts_hidden(self, client):
        html = client.get("/timeline").text
        assert 'id="traces-view" class="hidden"' in html

    def test_traces_table_has_expected_columns(self, client):
        html = client.get("/timeline").text
        assert "Root Type" in html
        assert "Event Count" in html
        assert "Streams" in html
        assert "Started At" in html


# ---------------------------------------------------------------------------
# JavaScript references
# ---------------------------------------------------------------------------


class TestJavaScriptReferences:
    """The timeline.js file contains expected trace-related functions."""

    @pytest.mark.parametrize(
        "needle",
        [
            pytest.param("fetchRecentTraces", id="fetch_recent_traces"),
            pytest.param("searchTraces", id="search_traces"),
            pytest.param("_renderTracesTable", id="render_traces_table"),
            pytest.param("traces-view", id="traces_view_handling"),
            # _readURL handles ?view=traces
            pytest.param("'traces'", id="view_traces_deep_link"),
            pytest.param("tab-events", id="events_tab_binding"),
            pytest.param("tab-traces", id="traces_tab_binding"),
        ],
    )
    def test_js_contains(self, client, needle):
        resp = client.get("/static/js/timeline.js")
        assert resp.status_code == 200
        assert needle in resp.text


# ---------------------------------------------------------------------------
# Deep linking
# ---------------------------------------------------------------------------


class TestDeepLinking:
    """The timeline page supports ?view=traces deep linking via JS."""

    @pytest.mark.parametrize(
        "url",
        ["/timeline?view=traces", "/timeline?view=traces&aggregate_id=abc-123"],
    )
    def test_timeline_page_loads_with_traces_query(self, client, url):
        resp = client.get(url)
        assert resp.status_code == 200
        assert 'id="traces-view"' in resp.text
