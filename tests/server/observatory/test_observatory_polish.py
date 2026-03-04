"""Tests for Observatory polish features: keyboard shortcuts, deep linking, CSV export.

Covers:
- base.html: Keyboard shortcuts modal
- templates/*.html: data-search-input attributes, CSV export buttons
- static/js/core.js: exportCSV function presence
- static/js/*.js: deep linking function presence
"""

import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def observatory(test_domain):
    return Observatory(domains=[test_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


# ---------------------------------------------------------------------------
# Keyboard Shortcuts Modal
# ---------------------------------------------------------------------------


class TestKeyboardShortcutsModal:
    def test_shortcuts_modal_present_in_base(self, client):
        html = client.get("/").text
        assert 'id="shortcuts-modal"' in html

    def test_modal_contains_navigation_keys(self, client):
        html = client.get("/").text
        assert "Go to Overview" in html
        assert "Go to Handlers" in html
        assert "Go to Event Flows" in html
        assert "Go to Processes" in html
        assert "Go to Event Store" in html
        assert "Go to Infrastructure" in html

    def test_modal_contains_action_keys(self, client):
        html = client.get("/").text
        assert "Focus search" in html
        assert "Refresh data" in html
        assert "Toggle this help" in html

    def test_modal_present_on_all_pages(self, client):
        for path in [
            "/",
            "/handlers",
            "/flows",
            "/processes",
            "/eventstore",
            "/infrastructure",
        ]:
            html = client.get(path).text
            assert 'id="shortcuts-modal"' in html, f"Modal missing on {path}"


# ---------------------------------------------------------------------------
# Search Input data-search-input Attribute
# ---------------------------------------------------------------------------


class TestSearchInputAttribute:
    def test_handlers_search_has_attribute(self, client):
        html = client.get("/handlers").text
        assert "data-search-input" in html

    def test_processes_search_has_attribute(self, client):
        html = client.get("/processes").text
        assert "data-search-input" in html

    def test_eventstore_search_has_attribute(self, client):
        html = client.get("/eventstore").text
        assert "data-search-input" in html

    def test_flows_search_has_attribute(self, client):
        html = client.get("/flows").text
        assert "data-search-input" in html


# ---------------------------------------------------------------------------
# CSV Export Buttons
# ---------------------------------------------------------------------------


class TestCSVExportButtons:
    def test_handlers_has_export_button(self, client):
        html = client.get("/handlers").text
        assert 'id="export-csv"' in html
        assert "CSV" in html

    def test_processes_has_export_button(self, client):
        html = client.get("/processes").text
        assert 'id="export-csv"' in html

    def test_eventstore_has_export_button(self, client):
        html = client.get("/eventstore").text
        assert 'id="export-csv"' in html


# ---------------------------------------------------------------------------
# Core.js Polish Features
# ---------------------------------------------------------------------------


class TestCoreJSPolishFeatures:
    def test_core_js_contains_keyboard_handler(self, client):
        response = client.get("/static/js/core.js")
        js = response.text
        assert "_initKeyboard" in js
        assert "_NAV_SHORTCUTS" in js

    def test_core_js_contains_export_csv(self, client):
        response = client.get("/static/js/core.js")
        js = response.text
        assert "exportCSV" in js
        assert "text/csv" in js

    def test_core_js_exports_export_csv(self, client):
        response = client.get("/static/js/core.js")
        js = response.text
        # Verify it's in the public API return object
        assert "exportCSV," in js or "exportCSV:" in js


# ---------------------------------------------------------------------------
# Deep Linking in View JS Modules
# ---------------------------------------------------------------------------


class TestDeepLinkingJS:
    def test_handlers_js_has_deep_linking(self, client):
        js = client.get("/static/js/handlers.js").text
        assert "_readURL" in js
        assert "_updateURL" in js
        assert "history.replaceState" in js

    def test_processes_js_has_deep_linking(self, client):
        js = client.get("/static/js/processes.js").text
        assert "_readURL" in js
        assert "_updateURL" in js
        assert "history.replaceState" in js

    def test_eventstore_js_has_deep_linking(self, client):
        js = client.get("/static/js/eventstore.js").text
        assert "_readURL" in js
        assert "_updateURL" in js
        assert "history.replaceState" in js


# ---------------------------------------------------------------------------
# CSV Export Wiring in View JS Modules
# ---------------------------------------------------------------------------


class TestCSVExportWiringJS:
    def test_handlers_js_has_csv_export(self, client):
        js = client.get("/static/js/handlers.js").text
        assert "_exportCSV" in js
        assert "Observatory.exportCSV" in js

    def test_processes_js_has_csv_export(self, client):
        js = client.get("/static/js/processes.js").text
        assert "_exportCSV" in js
        assert "Observatory.exportCSV" in js

    def test_eventstore_js_has_csv_export(self, client):
        js = client.get("/static/js/eventstore.js").text
        assert "_exportCSV" in js
        assert "Observatory.exportCSV" in js
