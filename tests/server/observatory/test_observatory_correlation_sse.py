"""Tests for live SSE updates on the correlation view.

Covers:
- Correlation SSE listener filtering by correlation_id and view state
- Debounce coalescing of rapid SSE events
- Live badge display and staleness timeout
- CausationGraph.update() method for animated tree diffing
- CSS animations for new graph nodes and links
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
def standalone_domain(tmp_path):
    """Create a standalone domain with in-memory adapters."""
    domain = Domain(name="CorrelationSSETests", root_path=str(tmp_path))
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


@pytest.fixture
def timeline_html(client):
    return client.get("/timeline").text


@pytest.fixture
def timeline_js(client):
    return client.get("/static/js/timeline.js").text


@pytest.fixture
def graph_js(client):
    return client.get("/static/js/causation-graph.js").text


@pytest.fixture
def timeline_css(client):
    return client.get("/static/css/observatory.css").text


# ---------------------------------------------------------------------------
# HTML — Live badge element
# ---------------------------------------------------------------------------


class TestLiveBadgeHTML:
    """The correlation view has a Live badge for real-time activity."""

    def test_has_live_badge_element(self, timeline_html):
        assert 'id="correlation-live-badge"' in timeline_html

    def test_live_badge_starts_hidden(self, timeline_html):
        idx = timeline_html.index('id="correlation-live-badge"')
        tag_start = timeline_html.rfind("<", 0, idx)
        tag_end = timeline_html.index(">", idx)
        tag = timeline_html[tag_start : tag_end + 1]
        assert "hidden" in tag

    def test_live_badge_has_success_style(self, timeline_html):
        idx = timeline_html.index('id="correlation-live-badge"')
        tag_start = timeline_html.rfind("<", 0, idx)
        tag_end = timeline_html.index(">", idx)
        tag = timeline_html[tag_start : tag_end + 1]
        assert "badge-success" in tag

    def test_live_badge_has_aria_live(self, timeline_html):
        idx = timeline_html.index('id="correlation-live-badge"')
        tag_start = timeline_html.rfind("<", 0, idx)
        tag_end = timeline_html.index(">", idx)
        tag = timeline_html[tag_start : tag_end + 1]
        assert 'aria-live="polite"' in tag

    def test_live_badge_contains_live_text(self, timeline_html):
        """Badge displays the word 'Live'."""
        idx = timeline_html.index('id="correlation-live-badge"')
        # Find the outermost closing </span> (skip nested child spans)
        search_from = idx
        for _ in range(3):  # Skip past inner spans
            search_from = timeline_html.index("</span>", search_from) + 7
        content = timeline_html[idx:search_from]
        assert "Live" in content

    def test_live_badge_has_pulse_animation(self, timeline_html):
        idx = timeline_html.index('id="correlation-live-badge"')
        tag_start = timeline_html.rfind("<", 0, idx)
        tag_end = timeline_html.index(">", idx)
        tag = timeline_html[tag_start : tag_end + 1]
        assert "animate-pulse" in tag


# ---------------------------------------------------------------------------
# JavaScript — Correlation SSE listener
# ---------------------------------------------------------------------------


class TestCorrelationSSEListener:
    """Verify JS registers an SSE listener for correlation view updates."""

    def test_registers_correlation_sse_on_trace(self, timeline_js):
        assert "Observatory.sse.onTrace(_onCorrelationTraceEvent)" in timeline_js

    def test_has_correlation_trace_event_handler(self, timeline_js):
        assert "_onCorrelationTraceEvent" in timeline_js

    def test_only_handles_correlation_view(self, timeline_js):
        """SSE handler only processes events when in correlation view."""
        assert "_currentView !== 'correlation'" in timeline_js

    def test_checks_correlation_id_match(self, timeline_js):
        """SSE handler only processes events with matching correlation_id."""
        assert "trace.correlation_id !== _currentCorrelationId" in timeline_js

    def test_requires_current_correlation_id(self, timeline_js):
        """SSE handler skips if no active correlation_id."""
        assert "if (!_currentCorrelationId) return" in timeline_js

    def test_filters_live_trace_events(self, timeline_js):
        """SSE handler only processes recognized trace event types."""
        assert "_LIVE_TRACE_EVENTS[trace.event]" in timeline_js


# ---------------------------------------------------------------------------
# JavaScript — Correlation SSE debounce
# ---------------------------------------------------------------------------


class TestCorrelationSSEDebounce:
    """Verify debounce coalesces rapid SSE events into single re-fetch."""

    def test_has_correlation_debounce_timer(self, timeline_js):
        assert "_correlationSseDebounceTimer" in timeline_js

    def test_clears_debounce_on_each_event(self, timeline_js):
        assert "clearTimeout(_correlationSseDebounceTimer)" in timeline_js

    def test_debounce_calls_fetch_latest_correlation(self, timeline_js):
        assert "_fetchLatestCorrelation()" in timeline_js

    def test_debounce_uses_300ms(self, timeline_js):
        """Debounce interval matches existing timeline pattern (300ms)."""
        # Find the correlation debounce setTimeout
        idx = timeline_js.index("_correlationSseDebounceTimer = setTimeout")
        # Check the nearby 300 value
        snippet = timeline_js[idx : idx + 200]
        assert "300" in snippet


# ---------------------------------------------------------------------------
# JavaScript — Fetch latest correlation
# ---------------------------------------------------------------------------


class TestFetchLatestCorrelation:
    """Verify JS re-fetches correlation data on SSE trigger."""

    def test_has_fetch_latest_correlation(self, timeline_js):
        assert "async function _fetchLatestCorrelation" in timeline_js

    def test_fetches_correlation_endpoint(self, timeline_js):
        assert "/api/timeline/correlation/" in timeline_js

    def test_calls_update_correlation_display(self, timeline_js):
        """Re-fetch delegates stat updates to shared helper."""
        assert "_updateCorrelationDisplay(data)" in timeline_js

    def test_calls_causation_graph_update(self, timeline_js):
        """Uses CausationGraph.update() for animated graph refresh."""
        assert "CausationGraph.update(treeClone)" in timeline_js

    def test_updates_tree_view_when_visible(self, timeline_js):
        """Falls back to tree view update when graph is hidden."""
        assert "_renderCausationTree(data.tree" in timeline_js

    def test_uses_sequence_token_for_staleness(self, timeline_js):
        """Discards stale responses from overlapping fetches."""
        assert "_correlationFetchSeq" in timeline_js
        assert "seq !== _correlationFetchSeq" in timeline_js

    def test_logs_warning_on_error(self, timeline_js):
        assert "console.warn('SSE correlation re-fetch failed:'" in timeline_js


# ---------------------------------------------------------------------------
# JavaScript — Shared correlation display helper
# ---------------------------------------------------------------------------


class TestUpdateCorrelationDisplay:
    """Verify shared helper updates all correlation view stats."""

    def test_has_update_correlation_display(self, timeline_js):
        assert "function _updateCorrelationDisplay(data)" in timeline_js

    def test_updates_event_count(self, timeline_js):
        """Updates the event count stat."""
        assert "'correlation-event-count'" in timeline_js

    def test_updates_total_duration(self, timeline_js):
        """Updates end-to-end duration stat."""
        assert "'correlation-total-duration'" in timeline_js

    def test_updates_streams_touched(self, timeline_js):
        """Updates streams touched stat."""
        assert "'correlation-streams-touched'" in timeline_js

    def test_updates_depth(self, timeline_js):
        """Updates chain depth stat."""
        assert "'correlation-depth'" in timeline_js

    def test_updates_event_table(self, timeline_js):
        """Updates the flat event table."""
        assert "'correlation-events-tbody'" in timeline_js

    def test_stores_correlation_data(self, timeline_js):
        """Stores data for view switching."""
        assert "_currentCorrelationData = data" in timeline_js

    def test_called_from_show_correlation_view(self, timeline_js):
        """Initial load uses the shared helper."""
        # Find _showCorrelationView and verify it calls the helper
        idx = timeline_js.index("async function _showCorrelationView")
        end = timeline_js.index("window.scrollTo(0, 0)", idx)
        snippet = timeline_js[idx:end]
        assert "_updateCorrelationDisplay(data)" in snippet

    def test_called_from_fetch_latest_correlation(self, timeline_js):
        """SSE re-fetch uses the shared helper."""
        idx = timeline_js.index("async function _fetchLatestCorrelation")
        end = timeline_js.index("} catch (e) {", idx)
        snippet = timeline_js[idx:end]
        assert "_updateCorrelationDisplay(data)" in snippet


# ---------------------------------------------------------------------------
# JavaScript — Correlation ID tracking
# ---------------------------------------------------------------------------


class TestCorrelationIdTracking:
    """Verify correlation ID is tracked when entering/leaving the view."""

    def test_has_current_correlation_id_state(self, timeline_js):
        assert "_currentCorrelationId" in timeline_js

    def test_sets_correlation_id_on_show(self, timeline_js):
        """Sets _currentCorrelationId when entering correlation view."""
        assert "_currentCorrelationId = correlationId" in timeline_js

    def test_clears_correlation_id_on_back(self, timeline_js):
        """Clears _currentCorrelationId when leaving correlation view."""
        assert "_currentCorrelationId = null" in timeline_js

    def test_view_teardown_on_navigation(self, timeline_js):
        """Leaving correlation view via any path cleans up timers and graph."""
        # _showView should clean up when navigating away from correlation
        idx = timeline_js.index("function _showView(view)")
        snippet = timeline_js[idx : idx + 500]
        assert "_hideLiveBadge()" in snippet
        assert "_correlationSseDebounceTimer" in snippet
        assert "CausationGraph.destroy()" in snippet


# ---------------------------------------------------------------------------
# JavaScript — Live badge management
# ---------------------------------------------------------------------------


class TestLiveBadgeJS:
    """Verify JS manages the Live badge visibility and staleness."""

    def test_has_show_live_badge(self, timeline_js):
        assert "_showLiveBadge" in timeline_js

    def test_has_hide_live_badge(self, timeline_js):
        assert "_hideLiveBadge" in timeline_js

    def test_has_live_badge_timeout(self, timeline_js):
        """Live badge hides after 30s of inactivity."""
        assert "_LIVE_BADGE_TIMEOUT_MS" in timeline_js
        assert "30000" in timeline_js

    def test_tracks_last_event_time(self, timeline_js):
        assert "_lastCorrelationEventTime" in timeline_js

    def test_updates_timestamp_on_fetch(self, timeline_js):
        """Re-fetch updates the last event timestamp."""
        assert "_lastCorrelationEventTime = Date.now()" in timeline_js

    def test_has_staleness_interval_check(self, timeline_js):
        """Interval timer checks if badge should be hidden."""
        assert "_liveBadgeTimer" in timeline_js
        assert "setInterval" in timeline_js

    def test_hides_on_back_navigation(self, timeline_js):
        """Live badge is hidden when navigating back from correlation view."""
        assert "_hideLiveBadge()" in timeline_js

    def test_shows_badge_element(self, timeline_js):
        """Show function removes hidden class from badge."""
        assert "'correlation-live-badge'" in timeline_js

    def test_clears_interval_on_hide(self, timeline_js):
        """Hide function clears the staleness check interval."""
        assert "clearInterval(_liveBadgeTimer)" in timeline_js


# ---------------------------------------------------------------------------
# JavaScript — CausationGraph.update() method
# ---------------------------------------------------------------------------


class TestCausationGraphUpdate:
    """Verify the D3 graph has an update method for live refresh."""

    def test_has_update_method(self, graph_js):
        assert "function update(newTreeData)" in graph_js

    def test_exports_update(self, graph_js):
        assert "update: update" in graph_js

    def test_returns_new_node_ids(self, graph_js):
        """Update returns array of new message_ids."""
        assert "return newIds" in graph_js

    def test_collects_old_ids(self, graph_js):
        """Collects existing message_ids before rebuilding."""
        assert "oldIds[d.data.message_id]" in graph_js

    def test_diffs_old_vs_new(self, graph_js):
        """Identifies nodes not present in old tree."""
        assert "!oldIds[d.data.message_id]" in graph_js

    def test_applies_new_node_class(self, graph_js):
        """Adds cg-node-new class to new nodes."""
        assert "cg-node-new" in graph_js

    def test_applies_new_link_class(self, graph_js):
        """Adds cg-link-new class to links targeting new nodes."""
        assert "cg-link-new" in graph_js

    def test_removes_highlight_after_timeout(self, graph_js):
        """Highlight class is removed after animation completes."""
        # Check for setTimeout that removes the class
        assert "cg-node-new" in graph_js
        assert "setTimeout" in graph_js

    def test_rebuilds_lane_map(self, graph_js):
        """Lane map is rebuilt for new stream categories."""
        assert "_laneMap = _buildLaneMap(newTreeData)" in graph_js

    def test_refreshes_overlays(self, graph_js):
        """Timeline axis, legend, and minimap are refreshed."""
        idx = graph_js.index("function update(newTreeData)")
        # Find the next function definition to bound the search
        end = graph_js.index("\n  function ", idx + 1)
        snippet = graph_js[idx:end]
        assert "_renderTimelineAxis()" in snippet
        assert "_renderLegend()" in snippet
        assert "_renderMinimap()" in snippet

    def test_handles_null_svg(self, graph_js):
        """Returns early if graph not initialized."""
        assert "if (!_svg || !_g || !_root || !newTreeData) return []" in graph_js

    def test_transfers_collapse_state(self, graph_js):
        """Preserves collapsed branches from old tree."""
        assert "_transferCollapseState" in graph_js

    def test_collects_all_ids_including_collapsed(self, graph_js):
        """Includes collapsed (_children) nodes in old ID set."""
        assert "_collectAllIds" in graph_js

    def test_clears_previous_highlight_timer(self, graph_js):
        """Clears previous highlight timer before scheduling a new one."""
        assert "clearTimeout(_highlightTimerId)" in graph_js

    def test_destroy_clears_highlight_timer(self, graph_js):
        """destroy() clears the highlight timer to prevent leaks."""
        idx = graph_js.index("function destroy()")
        snippet = graph_js[idx : idx + 500]
        assert "_highlightTimerId" in snippet


# ---------------------------------------------------------------------------
# CSS — New node animations
# ---------------------------------------------------------------------------


class TestNewNodeAnimationCSS:
    """Verify CSS animations for live-updating graph nodes."""

    def test_has_node_new_class(self, timeline_css):
        assert ".cg-node-new" in timeline_css

    def test_has_node_pulse_keyframes(self, timeline_css):
        assert "@keyframes cg-node-pulse" in timeline_css

    def test_has_node_fade_in_keyframes(self, timeline_css):
        assert "@keyframes cg-node-fade-in" in timeline_css

    def test_has_link_new_class(self, timeline_css):
        assert ".cg-link-new" in timeline_css

    def test_has_link_fade_in_keyframes(self, timeline_css):
        assert "@keyframes cg-link-fade-in" in timeline_css

    def test_node_new_has_success_stroke(self, timeline_css):
        """New nodes have a success-colored border."""
        # Find the .cg-node-new .cg-card rule
        idx = timeline_css.index(".cg-node.cg-node-new .cg-card")
        snippet = timeline_css[idx : idx + 200]
        assert "stroke:" in snippet

    def test_node_new_card_uses_pulse_animation(self, timeline_css):
        idx = timeline_css.index(".cg-node.cg-node-new .cg-card")
        snippet = timeline_css[idx : idx + 200]
        assert "cg-node-pulse" in snippet

    def test_node_new_uses_fade_in_animation(self, timeline_css):
        idx = timeline_css.index(".cg-node.cg-node-new {")
        snippet = timeline_css[idx : idx + 200]
        assert "cg-node-fade-in" in snippet
