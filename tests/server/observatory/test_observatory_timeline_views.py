"""Tests for Timeline sub-views: correlation chain and aggregate history.

Covers the HTML template structure, CSS styles, and JavaScript logic
for the correlation chain view, aggregate history view, and view management
features added in issue #740.

Uses standalone in-memory domains to avoid Redis dependency.
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
    domain = Domain(name="ViewTests", root_path=str(tmp_path))
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
# Timeline page — view containers
# ---------------------------------------------------------------------------


class TestTimelineViewContainers:
    """The timeline page has three mutually exclusive view sections."""

    def test_has_list_view_container(self, client):
        html = client.get("/timeline").text
        assert 'id="timeline-list-view"' in html

    def test_has_correlation_view_container(self, client):
        html = client.get("/timeline").text
        assert 'id="correlation-view"' in html

    def test_has_aggregate_view_container(self, client):
        html = client.get("/timeline").text
        assert 'id="aggregate-view"' in html

    def test_correlation_view_starts_hidden(self, client):
        html = client.get("/timeline").text
        assert 'id="correlation-view" class="hidden"' in html

    def test_aggregate_view_starts_hidden(self, client):
        html = client.get("/timeline").text
        assert 'id="aggregate-view" class="hidden"' in html

    def test_list_view_is_visible_by_default(self, client):
        """The list view should NOT have the hidden class by default."""
        html = client.get("/timeline").text
        # The list view div should not be hidden
        assert 'id="timeline-list-view"' in html
        # It should NOT have class="hidden"
        idx = html.index('id="timeline-list-view"')
        # Get the surrounding tag
        tag_start = html.rfind("<", 0, idx)
        tag_end = html.index(">", idx)
        tag = html[tag_start:tag_end]
        assert "hidden" not in tag


# ---------------------------------------------------------------------------
# Correlation chain view — HTML structure
# ---------------------------------------------------------------------------


class TestCorrelationViewHTML:
    """Verify the correlation chain view HTML elements."""

    def test_has_back_button(self, client):
        html = client.get("/timeline").text
        assert 'id="btn-back-from-correlation"' in html

    def test_has_heading(self, client):
        html = client.get("/timeline").text
        assert "Correlation Chain" in html

    def test_has_correlation_id_display(self, client):
        html = client.get("/timeline").text
        assert 'id="correlation-id-display"' in html

    def test_has_event_count_stat(self, client):
        html = client.get("/timeline").text
        assert 'id="correlation-event-count"' in html
        assert "Events in Chain" in html

    def test_has_root_type_stat(self, client):
        html = client.get("/timeline").text
        assert 'id="correlation-root-type"' in html
        assert "Root Event" in html

    def test_has_depth_stat(self, client):
        html = client.get("/timeline").text
        assert 'id="correlation-depth"' in html
        assert "Chain Depth" in html

    def test_has_causation_tree_container(self, client):
        html = client.get("/timeline").text
        assert 'id="correlation-tree"' in html
        assert "Causation Tree" in html

    def test_has_flat_event_list(self, client):
        html = client.get("/timeline").text
        assert 'id="correlation-events-tbody"' in html
        assert "All Events (chronological)" in html


# ---------------------------------------------------------------------------
# Aggregate history view — HTML structure
# ---------------------------------------------------------------------------


class TestAggregateViewHTML:
    """Verify the aggregate history view HTML elements."""

    def test_has_back_button(self, client):
        html = client.get("/timeline").text
        assert 'id="btn-back-from-aggregate"' in html

    def test_has_heading(self, client):
        html = client.get("/timeline").text
        assert "Aggregate History" in html

    def test_has_stream_display(self, client):
        html = client.get("/timeline").text
        assert 'id="aggregate-stream-display"' in html

    def test_has_category_stat(self, client):
        html = client.get("/timeline").text
        assert 'id="aggregate-category"' in html
        assert "Stream Category" in html

    def test_has_aggregate_id_display(self, client):
        html = client.get("/timeline").text
        assert 'id="aggregate-id-display"' in html
        assert "Aggregate ID" in html

    def test_has_version_stat(self, client):
        html = client.get("/timeline").text
        assert 'id="aggregate-version"' in html
        assert "Current Version" in html

    def test_has_event_history_container(self, client):
        html = client.get("/timeline").text
        assert 'id="aggregate-timeline"' in html
        assert "Event History" in html

    def test_has_empty_state(self, client):
        html = client.get("/timeline").text
        assert 'id="aggregate-empty"' in html


# ---------------------------------------------------------------------------
# Event detail modal — clickable links
# ---------------------------------------------------------------------------


class TestEventDetailModal:
    """The event detail modal is still present with all elements."""

    def test_has_modal(self, client):
        html = client.get("/timeline").text
        assert 'id="event-detail-modal"' in html

    def test_has_meta_grid(self, client):
        html = client.get("/timeline").text
        assert 'id="event-detail-meta"' in html

    def test_has_payload_section(self, client):
        html = client.get("/timeline").text
        assert 'id="event-detail-payload"' in html

    def test_has_metadata_section(self, client):
        html = client.get("/timeline").text
        assert 'id="event-detail-metadata"' in html


# ---------------------------------------------------------------------------
# Timeline JavaScript — correlation features
# ---------------------------------------------------------------------------


class TestTimelineJSCorrelation:
    """Verify JS has correlation chain functionality."""

    def test_has_show_correlation_view(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "_showCorrelationView" in js

    def test_has_render_causation_tree(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "_renderCausationTree" in js

    def test_has_compute_tree_depth(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "_computeTreeDepth" in js

    def test_fetches_correlation_api(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "/api/timeline/correlation/" in js

    def test_sets_correlation_url_param(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "params.set('correlation'" in js

    def test_reads_correlation_url_param(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "params.has('correlation')" in js


# ---------------------------------------------------------------------------
# Timeline JavaScript — aggregate features
# ---------------------------------------------------------------------------


class TestTimelineJSAggregate:
    """Verify JS has aggregate history functionality."""

    def test_has_show_aggregate_view(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "_showAggregateView" in js

    def test_has_render_aggregate_timeline(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "_renderAggregateTimeline" in js

    def test_fetches_aggregate_api(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "/api/timeline/aggregate/" in js

    def test_sets_aggregate_url_params(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "params.set('stream'" in js
        assert "params.set('aggregate'" in js

    def test_reads_aggregate_url_params(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "params.has('stream')" in js
        assert "params.has('aggregate')" in js


# ---------------------------------------------------------------------------
# Timeline JavaScript — view management
# ---------------------------------------------------------------------------


class TestTimelineJSViewManagement:
    """Verify JS manages view switching correctly."""

    def test_has_current_view_state(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "_currentView" in js

    def test_has_show_view_function(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "_showView" in js

    def test_has_back_to_list_function(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "_backToList" in js

    def test_has_enter_list_view_helper(self, client):
        """_enterListView loads list data when returning from sub-views."""
        js = client.get("/static/js/timeline.js").text
        assert "_enterListView" in js

    def test_back_to_list_delegates_to_enter_list_view(self, client):
        """_backToList calls _enterListView to ensure data is loaded."""
        js = client.get("/static/js/timeline.js").text
        assert "_enterListView()" in js

    def test_popstate_list_calls_enter_list_view(self, client):
        """Popstate to list view calls _enterListView to load data."""
        js = client.get("/static/js/timeline.js").text
        # The popstate handler calls _enterListView when no sub-view params
        assert "_enterListView()" in js

    def test_binds_back_buttons(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "btn-back-from-correlation" in js
        assert "btn-back-from-aggregate" in js

    def test_has_popstate_handler(self, client):
        """Browser back/forward navigation is handled."""
        js = client.get("/static/js/timeline.js").text
        assert "popstate" in js

    def test_has_parse_stream_helper(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "_parseStream" in js

    def test_skips_infinite_scroll_in_sub_views(self, client):
        """Infinite scroll only triggers in list view."""
        js = client.get("/static/js/timeline.js").text
        assert "_currentView !== 'list'" in js

    def test_uses_push_state_for_sub_views(self, client):
        """Sub-view navigation uses pushState for proper back/forward."""
        js = client.get("/static/js/timeline.js").text
        assert "history.pushState" in js


# ---------------------------------------------------------------------------
# Timeline JavaScript — clickable entry points
# ---------------------------------------------------------------------------


class TestTimelineJSEntryPoints:
    """Event detail has clickable links for correlation and stream."""

    def test_has_correlation_link_in_detail(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "detail-correlation-link" in js

    def test_has_stream_link_in_detail(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "detail-stream-link" in js

    def test_correlation_link_triggers_view(self, client):
        """Clicking correlation link calls _showCorrelationView."""
        js = client.get("/static/js/timeline.js").text
        # The click handler closes modal and opens correlation view
        assert "modal.close()" in js
        assert "_showCorrelationView(data.correlation_id)" in js

    def test_stream_link_triggers_aggregate_view(self, client):
        """Clicking stream link calls _showAggregateView."""
        js = client.get("/static/js/timeline.js").text
        assert "_showAggregateView(parts.category, parts.id)" in js


# ---------------------------------------------------------------------------
# Timeline JavaScript — shared rendering
# ---------------------------------------------------------------------------


class TestTimelineJSRendering:
    """Verify shared rendering function was extracted."""

    def test_has_render_event_rows(self, client):
        """_renderEventRows is shared between list and correlation views."""
        js = client.get("/static/js/timeline.js").text
        assert "_renderEventRows" in js

    def test_render_table_uses_shared_function(self, client):
        js = client.get("/static/js/timeline.js").text
        # _renderTable delegates to _renderEventRows
        assert "_renderEventRows($tbody, _events)" in js


# ---------------------------------------------------------------------------
# CSS — Vertical timeline styles
# ---------------------------------------------------------------------------


class TestVerticalTimelineCSS:
    """Verify CSS for correlation tree and aggregate timeline."""

    def test_has_correlation_tree_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".correlation-tree" in css

    def test_has_vtl_node(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".vtl-node" in css

    def test_has_vtl_root(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".vtl-root" in css

    def test_has_vtl_card(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".vtl-card" in css

    def test_has_vtl_children(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".vtl-children" in css

    def test_has_vtl_card_hover(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".vtl-card:hover" in css

    def test_has_aggregate_timeline_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".aggregate-timeline" in css

    def test_has_agg_tl_node(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".agg-tl-node" in css

    def test_has_agg_tl_dot(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".agg-tl-dot" in css

    def test_has_agg_tl_line(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".agg-tl-line" in css

    def test_has_agg_tl_content(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".agg-tl-content" in css

    def test_has_agg_tl_marker(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".agg-tl-marker" in css

    def test_has_agg_tl_content_hover(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".agg-tl-content:hover" in css


# ---------------------------------------------------------------------------
# Original list view elements still present
# ---------------------------------------------------------------------------


class TestOriginalListViewIntact:
    """Ensure original list view elements still work after refactoring."""

    def test_has_summary_cards(self, client):
        html = client.get("/timeline").text
        assert 'id="stats-total-events"' in html
        assert 'id="stats-active-streams"' in html

    def test_has_filter_controls(self, client):
        html = client.get("/timeline").text
        assert 'id="filter-stream"' in html
        assert 'id="filter-event-type"' in html
        assert 'id="filter-aggregate-id"' in html
        assert 'id="filter-kind"' in html

    def test_has_events_table(self, client):
        html = client.get("/timeline").text
        assert 'id="events-tbody"' in html

    def test_has_load_more(self, client):
        html = client.get("/timeline").text
        assert 'id="load-more"' in html
        assert 'id="btn-load-more"' in html

    def test_includes_timeline_js(self, client):
        html = client.get("/timeline").text
        assert "/static/js/timeline.js" in html


# ---------------------------------------------------------------------------
# Accessibility — keyboard navigation and ARIA attributes
# ---------------------------------------------------------------------------


class TestTimelineJSAccessibility:
    """Verify interactive elements have keyboard support and ARIA roles."""

    def test_causation_tree_cards_have_role_button(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "card.setAttribute('role', 'button')" in js

    def test_causation_tree_cards_have_tabindex(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "card.setAttribute('tabindex', '0')" in js

    def test_causation_tree_cards_handle_keyboard(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "card.addEventListener('keydown'" in js

    def test_aggregate_timeline_items_have_role_button(self, client):
        js = client.get("/static/js/timeline.js").text
        assert 'role="button" tabindex="0" data-message-id' in js

    def test_event_rows_have_role_button(self, client):
        js = client.get("/static/js/timeline.js").text
        assert 'tabindex="0" role="button" title="View event detail"' in js

    def test_event_rows_handle_keyboard(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "row.addEventListener('keydown'" in js

    def test_detail_links_have_role_button(self, client):
        js = client.get("/static/js/timeline.js").text
        assert 'role="button" tabindex="0" id="detail-correlation-link"' in js
        assert 'role="button" tabindex="0" id="detail-stream-link"' in js

    def test_detail_links_handle_keyboard(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "$corrLink.addEventListener('keydown'" in js
        assert "$streamLink.addEventListener('keydown'" in js

    def test_correlation_links_have_role_button(self, client):
        """Correlation links in aggregate timeline have role=button."""
        js = client.get("/static/js/timeline.js").text
        assert 'role="button" tabindex="0" data-correlation-id' in js

    def test_correlation_links_handle_keyboard(self, client):
        js = client.get("/static/js/timeline.js").text
        assert "link.addEventListener('keydown'" in js

    def test_includes_timeline_js(self, client):
        html = client.get("/timeline").text
        assert "/static/js/timeline.js" in html


# ---------------------------------------------------------------------------
# Enhanced correlation view — HTML stat cards (#859)
# ---------------------------------------------------------------------------


class TestEnhancedCorrelationViewHTML:
    """Verify new summary stat cards for timing and streams."""

    def test_has_total_duration_stat(self, client):
        html = client.get("/timeline").text
        assert 'id="correlation-total-duration"' in html
        assert "End-to-End Duration" in html

    def test_has_streams_touched_stat(self, client):
        html = client.get("/timeline").text
        assert 'id="correlation-streams-touched"' in html
        assert "Streams Touched" in html

    def test_summary_grid_has_five_columns(self, client):
        """The correlation summary grid should have 5 stat cards."""
        html = client.get("/timeline").text
        assert "md:grid-cols-5" in html


# ---------------------------------------------------------------------------
# Enhanced correlation view — CSS classes (#859)
# ---------------------------------------------------------------------------


class TestEnhancedCorrelationCSS:
    """Verify new CSS classes for handler, duration, latency, cross-aggregate."""

    def test_has_vtl_handler_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".vtl-handler" in css

    def test_has_vtl_duration_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".vtl-duration" in css

    def test_has_vtl_latency_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".vtl-latency" in css

    def test_has_vtl_cross_aggregate_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".vtl-cross-aggregate" in css

    def test_has_vtl_cross_aggregate_icon_class(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".vtl-cross-aggregate-icon" in css


# ---------------------------------------------------------------------------
# Enhanced correlation view — JavaScript rendering (#859)
# ---------------------------------------------------------------------------


class TestEnhancedCorrelationJS:
    """Verify JS renders handler badges, duration, latency, cross-aggregate."""

    def test_render_causation_tree_accepts_parent_stream(self, client):
        """_renderCausationTree takes parentStream for cross-aggregate detection."""
        js = client.get("/static/js/timeline.js").text
        assert "_renderCausationTree(node, depth, parentStream)" in js

    def test_renders_handler_badge(self, client):
        """Handler name is rendered with vtl-handler class."""
        js = client.get("/static/js/timeline.js").text
        assert "vtl-handler" in js
        assert "node.handler" in js

    def test_renders_duration_badge(self, client):
        """Duration is rendered with vtl-duration class."""
        js = client.get("/static/js/timeline.js").text
        assert "vtl-duration" in js
        assert "node.duration_ms" in js

    def test_renders_latency_label(self, client):
        """Inter-step latency is rendered with vtl-latency class."""
        js = client.get("/static/js/timeline.js").text
        assert "vtl-latency" in js
        assert "node.delta_ms" in js

    def test_renders_cross_aggregate_marker(self, client):
        """Cross-aggregate boundary is detected and marked."""
        js = client.get("/static/js/timeline.js").text
        assert "vtl-cross-aggregate" in js
        assert "isCrossAggregate" in js

    def test_uses_observatory_duration_formatter(self, client):
        """Duration formatting uses Observatory.fmt.duration from core.js."""
        js = client.get("/static/js/timeline.js").text
        assert "Observatory.fmt.duration(" in js

    def test_has_collect_tree_streams_helper(self, client):
        """_collectTreeStreams helper exists for counting unique streams."""
        js = client.get("/static/js/timeline.js").text
        assert "_collectTreeStreams" in js

    def test_populates_total_duration_stat(self, client):
        """_showCorrelationView populates the total duration stat card."""
        js = client.get("/static/js/timeline.js").text
        assert "correlation-total-duration" in js
        assert "data.total_duration_ms" in js

    def test_populates_streams_touched_stat(self, client):
        """_showCorrelationView populates the streams touched stat card."""
        js = client.get("/static/js/timeline.js").text
        assert "correlation-streams-touched" in js

    def test_passes_parent_stream_to_children(self, client):
        """Child nodes receive parent's stream for cross-aggregate detection."""
        js = client.get("/static/js/timeline.js").text
        assert "_renderCausationTree(node.children[i], depth + 1, node.stream)" in js

    def test_latency_label_only_for_non_root(self, client):
        """Latency label is only rendered for non-root nodes (depth > 0)."""
        js = client.get("/static/js/timeline.js").text
        assert "depth > 0 && node.delta_ms" in js
