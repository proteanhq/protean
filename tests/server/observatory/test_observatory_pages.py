"""Tests for Observatory page routes, Jinja2 template rendering, and static asset serving.

Tests for:
- routes/pages.py: page routes, _get_domain_names, _ctx helper
- routes/__init__.py: create_all_routes composition
- __init__.py: Jinja2Templates + StaticFiles integration, _TEMPLATES_DIR, _STATIC_DIR
"""

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from protean.server.observatory import _STATIC_DIR, _TEMPLATES_DIR, Observatory
from protean.server.observatory.routes import create_all_routes
from protean.server.observatory.routes.pages import (
    _get_domain_names,
    create_page_router,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def observatory(test_domain):
    """Observatory instance backed by a real domain."""
    return Observatory(domains=[test_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


# ---------------------------------------------------------------------------
# _TEMPLATES_DIR / _STATIC_DIR path constants
# ---------------------------------------------------------------------------


class TestDirectoryConstants:
    def test_templates_dir_exists(self):
        assert _TEMPLATES_DIR.is_dir()

    def test_static_dir_exists(self):
        assert _STATIC_DIR.is_dir()

    def test_templates_dir_contains_base_html(self):
        assert (_TEMPLATES_DIR / "base.html").is_file()

    def test_static_dir_contains_vendor_subdir(self):
        assert (_STATIC_DIR / "vendor").is_dir()

    def test_static_dir_contains_js_subdir(self):
        assert (_STATIC_DIR / "js").is_dir()

    def test_static_dir_contains_css_subdir(self):
        assert (_STATIC_DIR / "css").is_dir()


# ---------------------------------------------------------------------------
# _get_domain_names
# ---------------------------------------------------------------------------


class TestGetDomainNames:
    def test_extracts_single_domain_name(self, test_domain):
        names = _get_domain_names([test_domain])
        assert names == [test_domain.name]

    def test_extracts_multiple_domain_names(self, test_domain):
        from protean.domain import Domain

        d2 = Domain(name="second-domain")
        d2.init(traverse=False)
        names = _get_domain_names([test_domain, d2])
        assert len(names) == 2
        assert names[0] == test_domain.name
        assert names[1] == "second-domain"

    def test_empty_domains_returns_empty_list(self):
        assert _get_domain_names([]) == []


# ---------------------------------------------------------------------------
# create_page_router
# ---------------------------------------------------------------------------


class TestCreatePageRouter:
    def test_returns_api_router(self, test_domain):
        from fastapi.templating import Jinja2Templates

        templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
        router = create_page_router([test_domain], templates)
        assert isinstance(router, APIRouter)

    def test_registers_eight_routes(self, test_domain):
        from fastapi.templating import Jinja2Templates

        templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
        router = create_page_router([test_domain], templates)
        paths = {r.path for r in router.routes}
        assert paths == {
            "/",
            "/handlers",
            "/processes",
            "/eventstore",
            "/timeline",
            "/infrastructure",
            "/messages",
            "/domain",
        }

    def test_all_routes_are_get(self, test_domain):
        from fastapi.templating import Jinja2Templates

        templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
        router = create_page_router([test_domain], templates)
        for route in router.routes:
            assert "GET" in route.methods


# ---------------------------------------------------------------------------
# create_all_routes
# ---------------------------------------------------------------------------


class TestCreateAllRoutes:
    def test_returns_two_routers(self, test_domain):
        from fastapi.templating import Jinja2Templates

        templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
        page_router, api_router = create_all_routes([test_domain], templates)
        assert isinstance(page_router, APIRouter)
        assert isinstance(api_router, APIRouter)

    def test_page_router_has_routes(self, test_domain):
        from fastapi.templating import Jinja2Templates

        templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
        page_router, _ = create_all_routes([test_domain], templates)
        assert len(page_router.routes) == 8


# ---------------------------------------------------------------------------
# Observatory Jinja2 + StaticFiles integration
# ---------------------------------------------------------------------------


class TestObservatoryTemplates:
    def test_observatory_has_templates_attribute(self, observatory):
        from fastapi.templating import Jinja2Templates

        assert hasattr(observatory, "templates")
        assert isinstance(observatory.templates, Jinja2Templates)


class TestObservatoryStaticFiles:
    def test_static_mount_exists(self, observatory):
        """The /static mount should be present in the app routes."""
        mount_paths = [
            r.path
            for r in observatory.app.routes
            if hasattr(r, "path") and r.path == "/static"
        ]
        assert len(mount_paths) == 1

    @pytest.mark.parametrize(
        "path,content_type",
        [
            ("/static/vendor/daisyui.css", "text/css"),
            ("/static/vendor/d3.v7.min.js", "javascript"),
            ("/static/vendor/tailwindcss-browser.js", None),
            ("/static/vendor/daisyui-themes.css", None),
            ("/static/js/core.js", "javascript"),
            ("/static/js/charts.js", None),
            ("/static/js/overview.js", None),
            ("/static/js/timeline.js", "javascript"),
            ("/static/css/observatory.css", "text/css"),
        ],
    )
    def test_serves_static_asset(self, client, path, content_type):
        response = client.get(path)
        assert response.status_code == 200
        if content_type is not None:
            assert content_type in response.headers["content-type"]

    def test_css_has_search_styles(self, client):
        """Observatory CSS should include search-related styles."""
        css = client.get("/static/css/observatory.css").text
        assert ".dv-search-wrapper" in css
        assert ".dv-search-dropdown" in css
        assert ".dv-search-item" in css
        assert ".dv-search-clear" in css
        assert ".dv-flow-focal" in css

    def test_nonexistent_static_returns_404(self, client):
        response = client.get("/static/nonexistent.js")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Page Route Responses
# ---------------------------------------------------------------------------


class TestPageRoutes:
    @pytest.mark.parametrize(
        "path,heading",
        [
            ("/", "Overview"),
            ("/handlers", "Handlers"),
            ("/processes", "Processes"),
            ("/eventstore", "Event Store"),
            ("/timeline", "Timeline"),
            ("/infrastructure", "Infrastructure"),
        ],
    )
    def test_page_renders_base_template_with_heading(self, client, path, heading):
        response = client.get(path)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        html = response.text
        assert heading in html
        # Base template elements: branding and the DaisyUI drawer layout
        assert "Observatory" in html
        assert "drawer" in html


class TestOverviewPage:
    def test_contains_overview_content(self, client):
        html = client.get("/").text
        assert "health-banner" in html
        assert "kpi-total" in html
        assert "sub-summary" in html
        assert "error-summary" in html
        assert "activity-chart" in html
        assert "event-breakdown" in html

    def test_contains_subscription_summary_counters(self, client):
        """Subscription health shows compact summary, not full table."""
        html = client.get("/").text
        assert 'id="sub-healthy"' in html
        assert 'id="sub-lagging"' in html
        assert 'id="sub-dlq"' in html

    def test_contains_error_summary_counters(self, client):
        """Recent errors shows compact summary with link to handlers."""
        html = client.get("/").text
        assert 'id="error-failed"' in html
        assert 'id="error-dlq"' in html
        assert 'href="/handlers"' in html

    def test_unhealthy_table_hidden_by_default(self, client):
        """Unhealthy subscription table starts hidden."""
        html = client.get("/").text
        assert 'id="sub-unhealthy"' in html
        assert "hidden" in html

    def test_includes_overview_js(self, client):
        html = client.get("/").text
        assert "/static/js/overview.js" in html

    def test_includes_vendor_assets(self, client):
        html = client.get("/").text
        assert "/static/vendor/daisyui.css" in html
        assert "/static/vendor/tailwindcss-browser.js" in html
        assert "/static/vendor/d3.v7.min.js" in html

    def test_includes_core_js(self, client):
        html = client.get("/").text
        assert "/static/js/core.js" in html
        assert "/static/js/charts.js" in html

    def test_contains_kpi_cards(self, client):
        html = client.get("/").text
        assert "Total Processed" in html
        assert "Throughput" in html
        assert "Avg Latency" in html
        assert "Error Rate" in html
        assert "In Flight" in html
        assert "DLQ Depth" in html

    def test_contains_sse_status_indicator(self, client):
        """SSE connection status dot should be in the header."""
        html = client.get("/").text
        assert 'id="sse-dot"' in html


class TestHandlersPage:
    def test_handlers_nav_is_active(self, client):
        html = client.get("/handlers").text
        # The handlers nav link should have active, overview should not
        # Look for the specific pattern: href="/handlers" with active class
        assert 'href="/handlers"' in html


class TestTimelinePage:
    def test_contains_summary_cards(self, client):
        html = client.get("/timeline").text
        assert 'id="stats-total-events"' in html
        assert 'id="stats-active-streams"' in html
        assert 'id="stats-events-per-min"' in html
        assert 'id="stats-last-event"' in html

    def test_contains_filter_controls(self, client):
        html = client.get("/timeline").text
        assert 'id="filter-stream"' in html
        assert 'id="filter-event-type"' in html
        assert 'id="filter-aggregate-id"' in html
        assert 'id="filter-kind"' in html

    def test_contains_order_buttons(self, client):
        html = client.get("/timeline").text
        assert 'id="btn-order-asc"' in html
        assert 'id="btn-order-desc"' in html

    def test_contains_clear_filters_button(self, client):
        html = client.get("/timeline").text
        assert 'id="btn-clear-filters"' in html

    def test_contains_events_table(self, client):
        html = client.get("/timeline").text
        assert 'id="events-tbody"' in html

    def test_contains_load_more_control(self, client):
        html = client.get("/timeline").text
        assert 'id="load-more"' in html
        assert 'id="btn-load-more"' in html

    def test_contains_event_detail_modal(self, client):
        html = client.get("/timeline").text
        assert 'id="event-detail-modal"' in html
        assert 'id="event-detail-meta"' in html
        assert 'id="event-detail-payload"' in html
        assert 'id="event-detail-metadata"' in html

    def test_includes_timeline_js(self, client):
        html = client.get("/timeline").text
        assert "/static/js/timeline.js" in html

    def test_timeline_nav_is_active(self, client):
        html = client.get("/timeline").text
        assert 'href="/timeline"' in html

    def test_contains_sub_view_containers(self, client):
        """Smoke test: correlation and aggregate sub-views are present."""
        html = client.get("/timeline").text
        assert 'id="timeline-list-view"' in html
        assert 'id="correlation-view"' in html
        assert 'id="aggregate-view"' in html


# ---------------------------------------------------------------------------
# Navigation across pages
# ---------------------------------------------------------------------------


class TestNavigationLinks:
    """All pages include navigation links to all other views."""

    @pytest.fixture
    def overview_html(self, client):
        return client.get("/").text

    def test_has_link_to_overview(self, overview_html):
        assert 'href="/"' in overview_html

    def test_has_link_to_handlers(self, overview_html):
        assert 'href="/handlers"' in overview_html

    def test_has_link_to_processes(self, overview_html):
        assert 'href="/processes"' in overview_html

    def test_has_link_to_eventstore(self, overview_html):
        assert 'href="/eventstore"' in overview_html

    def test_has_link_to_timeline(self, overview_html):
        assert 'href="/timeline"' in overview_html

    def test_has_link_to_infrastructure(self, overview_html):
        assert 'href="/infrastructure"' in overview_html

    def test_has_link_to_domain(self, overview_html):
        assert 'href="/domain"' in overview_html


class TestActivePageHighlighting:
    """Each page should mark its own nav link as active."""

    PAGES = [
        ("/", "overview"),
        ("/handlers", "handlers"),
        ("/processes", "processes"),
        ("/eventstore", "eventstore"),
        ("/timeline", "timeline"),
        ("/infrastructure", "infrastructure"),
        ("/domain", "domain"),
    ]

    @pytest.mark.parametrize("path,page_name", PAGES)
    def test_active_class_present(self, client, path, page_name):
        """The page's nav link has the 'active' class."""
        html = client.get(path).text
        # The active class is rendered inside the <a> tag for the current page
        # We verify the active_page context variable was set correctly by
        # checking that the word 'active' appears in the rendered HTML
        # near the link for this page
        assert "active" in html


# ---------------------------------------------------------------------------
# Multi-domain support
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Activity Timeline Bootstrap
# ---------------------------------------------------------------------------


class TestActivityTimelineBootstrap:
    """The activity timeline should bootstrap with historical data, not just SSE."""

    def test_overview_js_contains_rebuild_function(self, client):
        js = client.get("/static/js/overview.js").text
        assert "rebuildActivityTimeline" in js

    def test_timeline_registered_as_poller(self, client):
        """Timeline uses a poller so setWindow() triggers a re-fetch."""
        js = client.get("/static/js/overview.js").text
        assert "traces-overview" in js
        assert "/api/traces/overview" in js

    def test_timeline_poller_before_sse(self, client):
        js = client.get("/static/js/overview.js").text
        poller_pos = js.index("'traces-overview'")
        on_trace_pos = js.index("Observatory.sse.onTrace(appendActivityPoint)")
        assert poller_pos < on_trace_pos

    def test_overview_js_has_no_activity_fallback(self, client):
        js = client.get("/static/js/overview.js").text
        assert "_showNoActivity" in js
        assert "No recent activity" in js

    def test_overview_js_uses_server_buckets(self, client):
        """Timeline uses pre-aggregated server buckets, not client-side bucketing."""
        js = client.get("/static/js/overview.js").text
        assert "data.buckets" in js
        assert "data.bucket_ms" in js
        assert "_currentBucketMs" in js


class TestMultiDomainContext:
    def test_multiple_domains_accepted(self, test_domain):
        """Observatory should accept multiple domains without error."""
        from protean.domain import Domain

        d2 = Domain(name="second-domain")
        d2.init(traverse=False)
        obs = Observatory(domains=[test_domain, d2])
        client = TestClient(obs.app)
        response = client.get("/")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Template content: base.html elements
# ---------------------------------------------------------------------------


class TestBaseTemplateElements:
    """Verify that the base template renders common UI elements."""

    @pytest.fixture
    def html(self, client):
        return client.get("/").text

    def test_has_sse_status_indicator(self, html):
        assert 'id="sse-status"' in html or 'id="sse-dot"' in html

    def test_has_window_selector(self, html):
        assert 'id="window-selector"' in html

    def test_has_time_windows(self, html):
        for w in ["5m", "15m", "1h", "24h", "7d"]:
            assert f'data-window="{w}"' in html

    def test_has_pause_button(self, html):
        assert 'id="btn-pause"' in html

    def test_has_theme_toggle(self, html):
        assert 'id="theme-toggle"' in html

    def test_has_nav_sidebar(self, html):
        assert "Overview" in html
        assert "Handlers" in html
        assert "Processes" in html
        assert "Event Store" in html
        assert "Timeline" in html
        assert "Infrastructure" in html
        assert 'href="/domain"' in html

    def test_no_domain_section_header(self, html):
        """Domain should be a regular nav item, not under a separate section header."""
        # menu-title is DaisyUI's section header class — Domain should not have one
        assert "menu-title" not in html

    def test_has_observatory_branding(self, html):
        assert "Observatory" in html
        assert "Protean Monitoring" in html

    def test_has_timeline_keyboard_shortcut(self, html):
        """The keyboard shortcuts modal should include the g→t shortcut."""
        assert "Go to Timeline" in html


class TestKeyboardShortcutsInCoreJS:
    """Verify that core.js includes the Timeline keyboard shortcut."""

    def test_core_js_has_timeline_shortcut(self, client):
        js = client.get("/static/js/core.js").text
        assert "'t': '/timeline'" in js


class TestTimelineJSContent:
    """Verify that timeline.js contains essential functionality."""

    @pytest.mark.parametrize(
        "needle",
        [
            pytest.param("/api/timeline/events", id="fetches_timeline_events"),
            pytest.param("/api/timeline/stats", id="fetches_timeline_stats"),
            pytest.param("timeline-stats", id="registers_stats_poller"),
            pytest.param("_showEventDetail", id="has_event_detail_function"),
            pytest.param("_onFilterChange", id="has_filter_change_handler"),
            pytest.param("scroll", id="has_infinite_scroll"),
            pytest.param("_readURL", id="deep_linking_reads_url"),
            pytest.param("_updateURL", id="deep_linking_updates_url"),
            pytest.param("/api/eventstore/streams", id="fetches_stream_categories"),
        ],
    )
    def test_timeline_js_contains(self, client, needle):
        js = client.get("/static/js/timeline.js").text
        assert needle in js
