"""Tests for real-time SSE updates on the Timeline page.

Covers:
- SSE toast notification element in timeline HTML
- SSE-related CSS animations and styles
- JavaScript SSE trace listener, deduplication, toast, and scroll handling
- Stats card presence and poller registration
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
    domain = Domain(name="SSETests", root_path=str(tmp_path))
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
def timeline_css(client):
    return client.get("/static/css/observatory.css").text


# ---------------------------------------------------------------------------
# HTML — SSE toast notification element
# ---------------------------------------------------------------------------


class TestSSEToastHTML:
    """The timeline page has a toast element for new-event notifications."""

    def test_has_toast_element(self, timeline_html):
        assert 'id="sse-toast"' in timeline_html

    def test_toast_starts_hidden(self, timeline_html):
        idx = timeline_html.index('id="sse-toast"')
        tag_start = timeline_html.rfind("<", 0, idx)
        tag_end = timeline_html.index(">", idx)
        tag = timeline_html[tag_start : tag_end + 1]
        assert "hidden" in tag

    def test_toast_has_label_span(self, timeline_html):
        assert "toast-label" in timeline_html

    def test_toast_has_aria_live(self, timeline_html):
        idx = timeline_html.index('id="sse-toast"')
        tag_start = timeline_html.rfind("<", 0, idx)
        tag_end = timeline_html.index(">", idx)
        tag = timeline_html[tag_start : tag_end + 1]
        assert 'aria-live="polite"' in tag

    def test_toast_has_role_status(self, timeline_html):
        idx = timeline_html.index('id="sse-toast"')
        tag_start = timeline_html.rfind("<", 0, idx)
        tag_end = timeline_html.index(">", idx)
        tag = timeline_html[tag_start : tag_end + 1]
        assert 'role="status"' in tag

    def test_toast_has_cursor_pointer(self, timeline_html):
        idx = timeline_html.index('id="sse-toast"')
        tag_start = timeline_html.rfind("<", 0, idx)
        tag_end = timeline_html.index(">", idx)
        tag = timeline_html[tag_start : tag_end + 1]
        assert "cursor-pointer" in tag

    def test_toast_has_fixed_positioning(self, timeline_html):
        idx = timeline_html.index('id="sse-toast"')
        tag_start = timeline_html.rfind("<", 0, idx)
        tag_end = timeline_html.index(">", idx)
        tag = timeline_html[tag_start : tag_end + 1]
        assert "fixed" in tag

    def test_toast_has_z_index(self, timeline_html):
        idx = timeline_html.index('id="sse-toast"')
        tag_start = timeline_html.rfind("<", 0, idx)
        tag_end = timeline_html.index(">", idx)
        tag = timeline_html[tag_start : tag_end + 1]
        assert "z-50" in tag

    def test_toast_is_button_element(self, timeline_html):
        """Toast is a <button> for native keyboard accessibility."""
        idx = timeline_html.index('id="sse-toast"')
        tag_start = timeline_html.rfind("<", 0, idx)
        tag = timeline_html[tag_start : tag_start + 8]
        assert "<button" in tag

    def test_toast_has_aria_label(self, timeline_html):
        idx = timeline_html.index('id="sse-toast"')
        tag_start = timeline_html.rfind("<", 0, idx)
        tag_end = timeline_html.index(">", idx)
        tag = timeline_html[tag_start : tag_end + 1]
        assert "aria-label=" in tag


# ---------------------------------------------------------------------------
# CSS — SSE animations
# ---------------------------------------------------------------------------


class TestSSEAnimationCSS:
    """Verify CSS for new-event highlight and toast animations."""

    def test_has_sse_new_event_class(self, timeline_css):
        assert ".sse-new-event" in timeline_css

    def test_has_sse_highlight_animation(self, timeline_css):
        assert "sse-highlight" in timeline_css

    def test_highlight_uses_keyframes(self, timeline_css):
        assert "@keyframes sse-highlight" in timeline_css

    def test_has_bounce_in_animation(self, timeline_css):
        assert ".animate-bounce-in" in timeline_css

    def test_has_bounce_in_keyframes(self, timeline_css):
        assert "@keyframes bounce-in" in timeline_css


# ---------------------------------------------------------------------------
# JavaScript — SSE trace listener
# ---------------------------------------------------------------------------


class TestTimelineJSSSEListener:
    """Verify JS registers an SSE trace listener for real-time updates."""

    def test_registers_sse_on_trace(self, timeline_js):
        assert "Observatory.sse.onTrace" in timeline_js

    def test_has_on_trace_event_handler(self, timeline_js):
        assert "_onTraceEvent" in timeline_js

    def test_listens_for_handler_completed(self, timeline_js):
        assert "'handler.completed'" in timeline_js

    def test_listens_for_outbox_published(self, timeline_js):
        assert "'outbox.published'" in timeline_js

    def test_listens_for_outbox_external_published(self, timeline_js):
        assert "'outbox.external_published'" in timeline_js

    def test_has_live_trace_events_map(self, timeline_js):
        assert "_LIVE_TRACE_EVENTS" in timeline_js

    def test_only_handles_list_view(self, timeline_js):
        """SSE handler only processes events when in list view."""
        assert "_currentView !== 'list'" in timeline_js

    def test_skips_when_loading(self, timeline_js):
        """SSE handler skips when a fetchEvents call is in progress."""
        assert "if (_loading) return" in timeline_js

    def test_debounces_traces(self, timeline_js):
        """SSE handler debounces rapid traces to coalesce into one fetch."""
        assert "_sseDebounceTimer" in timeline_js
        assert "clearTimeout(_sseDebounceTimer)" in timeline_js
        assert "setTimeout" in timeline_js


# ---------------------------------------------------------------------------
# JavaScript — fetch latest event logic
# ---------------------------------------------------------------------------


class TestTimelineJSFetchLatest:
    """Verify JS fetches the latest event when SSE trace arrives."""

    def test_has_fetch_latest_event(self, timeline_js):
        assert "_fetchLatestEvent" in timeline_js

    def test_fetches_with_limit_1(self, timeline_js):
        assert "qs.set('limit', '1')" in timeline_js

    def test_fetches_newest_first(self, timeline_js):
        assert "qs.set('order', 'desc')" in timeline_js

    def test_applies_stream_category_filter(self, timeline_js):
        assert "qs.set('stream_category', _streamCategory)" in timeline_js

    def test_applies_event_type_filter(self, timeline_js):
        assert "qs.set('event_type', _eventType)" in timeline_js

    def test_applies_aggregate_id_filter(self, timeline_js):
        assert "qs.set('aggregate_id', _aggregateId)" in timeline_js

    def test_applies_kind_filter(self, timeline_js):
        assert "qs.set('kind', _kind)" in timeline_js

    def test_logs_warning_on_error(self, timeline_js):
        """Errors are logged as warnings for debuggability."""
        assert "console.warn('SSE fetch latest event failed:'" in timeline_js


# ---------------------------------------------------------------------------
# JavaScript — deduplication
# ---------------------------------------------------------------------------


class TestTimelineJSDeduplication:
    """Verify JS deduplicates events to prevent duplicate entries."""

    def test_tracks_last_known_position(self, timeline_js):
        assert "_lastKnownPosition" in timeline_js

    def test_skips_old_positions(self, timeline_js):
        assert "latestPos <= _lastKnownPosition" in timeline_js

    def test_checks_message_id_duplicate(self, timeline_js):
        assert "message_id === latest.message_id" in timeline_js

    def test_updates_high_water_mark(self, timeline_js):
        assert "_lastKnownPosition = latestPos" in timeline_js

    def test_updates_position_on_fetch(self, timeline_js):
        """fetchEvents updates _lastKnownPosition for SSE deduplication."""
        assert "_lastKnownPosition" in timeline_js
        # The fetchEvents function should update the position tracker
        assert "p > _lastKnownPosition" in timeline_js


# ---------------------------------------------------------------------------
# JavaScript — new event highlight
# ---------------------------------------------------------------------------


class TestTimelineJSHighlight:
    """Verify JS adds CSS highlight class to new event rows."""

    def test_adds_sse_new_event_class(self, timeline_js):
        assert "sse-new-event" in timeline_js

    def test_highlights_first_row(self, timeline_js):
        assert "$tbody.firstElementChild" in timeline_js


# ---------------------------------------------------------------------------
# JavaScript — toast notification
# ---------------------------------------------------------------------------


class TestTimelineJSToast:
    """Verify JS toast notification for new events."""

    def test_has_pending_count_state(self, timeline_js):
        assert "_pendingNewEvents" in timeline_js

    def test_has_show_toast_function(self, timeline_js):
        assert "_showToast" in timeline_js

    def test_has_dismiss_toast_function(self, timeline_js):
        assert "_dismissToast" in timeline_js

    def test_has_scroll_to_top_function(self, timeline_js):
        assert "_scrollToTopAndDismiss" in timeline_js

    def test_has_is_scrolled_down_check(self, timeline_js):
        assert "_isScrolledDown" in timeline_js

    def test_toast_shows_click_to_scroll(self, timeline_js):
        assert "click to scroll to top" in timeline_js

    def test_toast_click_scrolls_to_top(self, timeline_js):
        """Clicking the toast scrolls to top and dismisses it."""
        assert "$toast.addEventListener('click', _scrollToTopAndDismiss)" in timeline_js

    def test_auto_dismiss_on_scroll_up(self, timeline_js):
        """Toast auto-dismisses when user scrolls back to top."""
        # The scroll handler dismisses when not scrolled down
        assert "_dismissToast()" in timeline_js

    def test_toast_dom_ref(self, timeline_js):
        """The toast DOM element is captured on init."""
        assert "document.getElementById('sse-toast')" in timeline_js

    def test_toast_label_updated(self, timeline_js):
        """Toast label shows count of new events."""
        assert "toast-label" in timeline_js

    def test_single_event_label(self, timeline_js):
        """Shows '1 new event' for single event."""
        assert "'1 new event'" in timeline_js

    def test_plural_event_label(self, timeline_js):
        """Shows 'N new events' for multiple events."""
        assert "' new events'" in timeline_js


# ---------------------------------------------------------------------------
# JavaScript — stats poller
# ---------------------------------------------------------------------------


class TestTimelineJSStatsPoller:
    """Verify stats polling is registered for stat cards."""

    def test_has_fetch_stats_function(self, timeline_js):
        assert "fetchStats" in timeline_js

    def test_registers_stats_poller(self, timeline_js):
        assert "Observatory.poller.register('timeline-stats'" in timeline_js

    def test_stats_poller_interval(self, timeline_js):
        assert "15000" in timeline_js

    def test_stats_poller_endpoint(self, timeline_js):
        assert "/api/timeline/stats" in timeline_js


# ---------------------------------------------------------------------------
# JavaScript — SSE refreshes stats
# ---------------------------------------------------------------------------


class TestTimelineJSSSERefreshesStats:
    """SSE trace events trigger immediate stats refresh."""

    def test_calls_fetch_stats_on_trace(self, timeline_js):
        """The _onTraceEvent handler calls fetchStats() for live updates."""
        assert "fetchStats()" in timeline_js


# ---------------------------------------------------------------------------
# JavaScript — ascending order falls back to full refresh
# ---------------------------------------------------------------------------


class TestTimelineJSAscendingRefresh:
    """When order is ascending, new events trigger a full refresh."""

    def test_asc_order_full_refresh(self, timeline_js):
        """In ascending order, new events call fetchEvents(false)."""
        # The else branch for ascending order calls full refresh
        assert "fetchEvents(false)" in timeline_js
