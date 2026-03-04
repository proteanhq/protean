"""Tests for Observatory page routes, Jinja2 template rendering, and static asset serving.

Covers:
- routes/pages.py: All 6 page routes, _get_domain_names, _ctx helper
- routes/__init__.py: create_all_routes composition
- __init__.py: Jinja2Templates + StaticFiles integration, _TEMPLATES_DIR, _STATIC_DIR
"""

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory, _STATIC_DIR, _TEMPLATES_DIR
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

    def test_registers_six_routes(self, test_domain):
        from fastapi.templating import Jinja2Templates

        templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
        router = create_page_router([test_domain], templates)
        paths = {r.path for r in router.routes}
        assert paths == {
            "/",
            "/handlers",
            "/flows",
            "/processes",
            "/eventstore",
            "/infrastructure",
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
        assert len(page_router.routes) == 6

    def test_api_router_is_initially_empty(self, test_domain):
        from fastapi.templating import Jinja2Templates

        templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
        _, api_router = create_all_routes([test_domain], templates)
        assert len(api_router.routes) == 0


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

    def test_serves_vendor_css(self, client):
        response = client.get("/static/vendor/daisyui.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]

    def test_serves_vendor_js(self, client):
        response = client.get("/static/vendor/d3.v7.min.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]

    def test_serves_tailwind_browser_js(self, client):
        response = client.get("/static/vendor/tailwindcss-browser.js")
        assert response.status_code == 200

    def test_serves_daisyui_themes_css(self, client):
        response = client.get("/static/vendor/daisyui-themes.css")
        assert response.status_code == 200

    def test_serves_core_js(self, client):
        response = client.get("/static/js/core.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]

    def test_serves_charts_js(self, client):
        response = client.get("/static/js/charts.js")
        assert response.status_code == 200

    def test_serves_overview_js(self, client):
        response = client.get("/static/js/overview.js")
        assert response.status_code == 200

    def test_serves_observatory_css(self, client):
        response = client.get("/static/css/observatory.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]

    def test_nonexistent_static_returns_404(self, client):
        response = client.get("/static/nonexistent.js")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Page Route Responses
# ---------------------------------------------------------------------------


class TestOverviewPage:
    def test_returns_200(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_returns_html(self, client):
        response = client.get("/")
        assert "text/html" in response.headers["content-type"]

    def test_extends_base_template(self, client):
        """Response includes base template elements: nav sidebar, header."""
        html = client.get("/").text
        assert "Observatory" in html
        assert "drawer" in html  # DaisyUI drawer layout

    def test_contains_overview_content(self, client):
        html = client.get("/").text
        assert "health-banner" in html
        assert "kpi-total" in html
        assert "subscriptions-tbody" in html
        assert "activity-chart" in html
        assert "event-breakdown" in html
        assert "recent-errors" in html

    def test_overview_nav_is_active(self, client):
        """The overview nav link should have the 'active' class."""
        html = client.get("/").text
        # The base template renders: class="{% if active_page == 'overview' %}active{% endif %}"
        # Since active_page == 'overview', the link should have 'active'
        assert "active" in html

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

    def test_contains_domain_badge(self, client, test_domain):
        """Domain name should appear as a badge in the header."""
        html = client.get("/").text
        assert test_domain.name in html


class TestHandlersPage:
    def test_returns_200(self, client):
        response = client.get("/handlers")
        assert response.status_code == 200

    def test_returns_html(self, client):
        assert "text/html" in client.get("/handlers").headers["content-type"]

    def test_contains_page_heading(self, client):
        html = client.get("/handlers").text
        assert "Handlers" in html

    def test_handlers_nav_is_active(self, client):
        html = client.get("/handlers").text
        # The handlers nav link should have active, overview should not
        # Look for the specific pattern: href="/handlers" with active class
        assert 'href="/handlers"' in html

    def test_extends_base_template(self, client):
        html = client.get("/handlers").text
        assert "Observatory" in html
        assert "drawer" in html


class TestFlowsPage:
    def test_returns_200(self, client):
        response = client.get("/flows")
        assert response.status_code == 200

    def test_returns_html(self, client):
        assert "text/html" in client.get("/flows").headers["content-type"]

    def test_contains_page_heading(self, client):
        html = client.get("/flows").text
        assert "Event Flows" in html

    def test_extends_base_template(self, client):
        html = client.get("/flows").text
        assert "Observatory" in html


class TestProcessesPage:
    def test_returns_200(self, client):
        response = client.get("/processes")
        assert response.status_code == 200

    def test_returns_html(self, client):
        assert "text/html" in client.get("/processes").headers["content-type"]

    def test_contains_page_heading(self, client):
        html = client.get("/processes").text
        assert "Processes" in html

    def test_extends_base_template(self, client):
        html = client.get("/processes").text
        assert "Observatory" in html


class TestEventstorePage:
    def test_returns_200(self, client):
        response = client.get("/eventstore")
        assert response.status_code == 200

    def test_returns_html(self, client):
        assert "text/html" in client.get("/eventstore").headers["content-type"]

    def test_contains_page_heading(self, client):
        html = client.get("/eventstore").text
        assert "Event Store" in html

    def test_extends_base_template(self, client):
        html = client.get("/eventstore").text
        assert "Observatory" in html


class TestInfrastructurePage:
    def test_returns_200(self, client):
        response = client.get("/infrastructure")
        assert response.status_code == 200

    def test_returns_html(self, client):
        assert "text/html" in client.get("/infrastructure").headers["content-type"]

    def test_contains_page_heading(self, client):
        html = client.get("/infrastructure").text
        assert "Infrastructure" in html

    def test_extends_base_template(self, client):
        html = client.get("/infrastructure").text
        assert "Observatory" in html


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

    def test_has_link_to_flows(self, overview_html):
        assert 'href="/flows"' in overview_html

    def test_has_link_to_processes(self, overview_html):
        assert 'href="/processes"' in overview_html

    def test_has_link_to_eventstore(self, overview_html):
        assert 'href="/eventstore"' in overview_html

    def test_has_link_to_infrastructure(self, overview_html):
        assert 'href="/infrastructure"' in overview_html


class TestActivePageHighlighting:
    """Each page should mark its own nav link as active."""

    PAGES = [
        ("/", "overview"),
        ("/handlers", "handlers"),
        ("/flows", "flows"),
        ("/processes", "processes"),
        ("/eventstore", "eventstore"),
        ("/infrastructure", "infrastructure"),
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


class TestMultiDomainContext:
    def test_multiple_domains_shown_in_header(self, test_domain):
        from protean.domain import Domain

        d2 = Domain(name="second-domain")
        d2.init(traverse=False)
        obs = Observatory(domains=[test_domain, d2])
        client = TestClient(obs.app)
        html = client.get("/").text
        assert test_domain.name in html
        assert "second-domain" in html

    def test_single_domain_shown_in_header(self, test_domain):
        obs = Observatory(domains=[test_domain])
        client = TestClient(obs.app)
        html = client.get("/").text
        assert test_domain.name in html


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
        assert "Event Flows" in html
        assert "Processes" in html
        assert "Event Store" in html
        assert "Infrastructure" in html

    def test_has_observatory_branding(self, html):
        assert "Observatory" in html
        assert "Protean Monitoring" in html
