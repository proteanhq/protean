"""Tests for the Observatory Domain Detail Panel.

Covers:
- templates/domain.html: Slide-in panel markup
- static/js/domain-detail.js: DomainDetail module
- static/css/observatory.css: Panel styling classes
- Integration with domain.js
"""

import pytest


# ---------------------------------------------------------------------------
# Template: Panel Structure
# ---------------------------------------------------------------------------


class TestDetailPanelMarkup:
    """Verify the slide-in panel HTML structure in domain.html."""

    def test_panel_container_exists(self, client):
        html = client.get("/domain").text
        assert 'id="dv-detail-panel"' in html

    def test_panel_has_slide_in_class(self, client):
        html = client.get("/domain").text
        assert "dv-detail-panel" in html

    def test_panel_has_title(self, client):
        html = client.get("/domain").text
        assert 'id="dv-detail-title"' in html

    def test_panel_has_fqn_display(self, client):
        html = client.get("/domain").text
        assert 'id="dv-detail-fqn"' in html

    def test_panel_has_content_area(self, client):
        html = client.get("/domain").text
        assert 'id="dv-detail-content"' in html

    def test_panel_has_close_button(self, client):
        html = client.get("/domain").text
        assert 'id="dv-detail-close"' in html

    def test_panel_has_backdrop(self, client):
        html = client.get("/domain").text
        assert 'id="dv-detail-backdrop"' in html

    def test_panel_has_header_and_body(self, client):
        html = client.get("/domain").text
        assert "dv-detail-header" in html
        assert "dv-detail-body" in html


# ---------------------------------------------------------------------------
# Static Assets: domain-detail.js
# ---------------------------------------------------------------------------


class TestDomainDetailJS:
    """Verify the domain-detail.js module is served and well-formed."""

    def test_serves_domain_detail_js(self, client):
        response = client.get("/static/js/domain-detail.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]

    def test_exports_domain_detail_object(self, client):
        js = client.get("/static/js/domain-detail.js").text
        assert "var DomainDetail" in js

    def test_has_init_method(self, client):
        js = client.get("/static/js/domain-detail.js").text
        assert "init:" in js

    def test_has_show_method(self, client):
        js = client.get("/static/js/domain-detail.js").text
        assert "show:" in js

    def test_has_hide_method(self, client):
        js = client.get("/static/js/domain-detail.js").text
        assert "hide:" in js

    def test_renders_fields_section(self, client):
        js = client.get("/static/js/domain-detail.js").text
        assert "_renderFieldsSection" in js

    def test_renders_element_section(self, client):
        js = client.get("/static/js/domain-detail.js").text
        assert "_renderElementSection" in js

    def test_renders_handler_section(self, client):
        js = client.get("/static/js/domain-detail.js").text
        assert "_renderHandlerSection" in js

    def test_renders_invariants_section(self, client):
        js = client.get("/static/js/domain-detail.js").text
        assert "_renderInvariantsSection" in js

    def test_renders_repo_section(self, client):
        js = client.get("/static/js/domain-detail.js").text
        assert "_renderRepoSection" in js

    def test_renders_fields_table(self, client):
        js = client.get("/static/js/domain-detail.js").text
        assert "_renderFieldsTable" in js

    def test_has_escape_key_handler(self, client):
        js = client.get("/static/js/domain-detail.js").text
        assert "Escape" in js

    def test_has_backdrop_click_handler(self, client):
        js = client.get("/static/js/domain-detail.js").text
        assert "dv-detail-backdrop" in js

    def test_accordion_toggle_wiring(self, client):
        js = client.get("/static/js/domain-detail.js").text
        assert "dv-section-toggle" in js
        assert "dv-open" in js


# ---------------------------------------------------------------------------
# Script Inclusion Order
# ---------------------------------------------------------------------------


class TestScriptInclusion:
    """domain-detail.js must load before domain.js (which calls DomainDetail)."""

    def test_detail_js_included_in_page(self, client):
        html = client.get("/domain").text
        assert "/static/js/domain-detail.js" in html

    def test_detail_js_loaded_before_domain_js(self, client):
        html = client.get("/domain").text
        detail_pos = html.index("/static/js/domain-detail.js")
        domain_pos = html.rindex("/static/js/domain.js")
        assert detail_pos < domain_pos


# ---------------------------------------------------------------------------
# Integration: domain.js delegates to DomainDetail
# ---------------------------------------------------------------------------


class TestDomainJSIntegration:
    """domain.js should delegate to DomainDetail for detail panel logic."""

    def test_domain_js_calls_domain_detail_show(self, client):
        js = client.get("/static/js/domain.js").text
        assert "DomainDetail.show" in js

    def test_domain_js_calls_domain_detail_init(self, client):
        js = client.get("/static/js/domain.js").text
        assert "DomainDetail.init" in js


# ---------------------------------------------------------------------------
# CSS: Panel Styles
# ---------------------------------------------------------------------------


class TestDetailPanelCSS:
    """Verify the CSS classes for the detail panel exist."""

    def test_panel_css_exists(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-detail-panel" in css

    def test_backdrop_css_exists(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-detail-backdrop" in css

    def test_section_css_exists(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-section" in css
        assert ".dv-section-toggle" in css
        assert ".dv-section-body" in css

    def test_field_table_css_exists(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-field-table" in css

    def test_badge_css_exists(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-badge--id" in css
        assert ".dv-badge--version" in css
        assert ".dv-badge--published" in css

    def test_handler_map_css_exists(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-handler-map" in css

    def test_slide_transition_css(self, client):
        css = client.get("/static/css/observatory.css").text
        assert "translateX" in css
        assert "transition" in css


# ---------------------------------------------------------------------------
# Multi-Aggregate: Cluster Data for Detail Panel
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDetailPanelClusterData:
    """Verify cluster data from /api/domain/ir contains what the detail panel needs."""

    def test_cluster_has_aggregate_entry(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for fqn, cluster in data["clusters"].items():
            assert "aggregate" in cluster

    def test_cluster_has_element_sections(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        expected_sections = [
            "commands",
            "events",
            "entities",
            "value_objects",
            "command_handlers",
            "event_handlers",
        ]
        for fqn, cluster in data["clusters"].items():
            for section in expected_sections:
                assert section in cluster, f"Missing {section} in cluster {fqn}"

    def test_aggregate_has_fields(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for fqn, cluster in data["clusters"].items():
            agg = cluster["aggregate"]
            assert "fields" in agg
            assert isinstance(agg["fields"], dict)
            assert len(agg["fields"]) > 0

    def test_aggregate_has_identity_field(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for fqn, cluster in data["clusters"].items():
            agg = cluster["aggregate"]
            assert "identity_field" in agg

    def test_aggregate_has_options(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for fqn, cluster in data["clusters"].items():
            agg = cluster["aggregate"]
            assert "options" in agg

    def test_command_has_type_key(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for fqn, cluster in data["clusters"].items():
            for cmd_fqn, cmd in cluster.get("commands", {}).items():
                assert "__type__" in cmd

    def test_event_has_type_key(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for fqn, cluster in data["clusters"].items():
            for evt_fqn, evt in cluster.get("events", {}).items():
                assert "__type__" in evt

    def test_handler_has_handler_map(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for fqn, cluster in data["clusters"].items():
            for ch_fqn, ch in cluster.get("command_handlers", {}).items():
                assert "handlers" in ch
                assert isinstance(ch["handlers"], dict)
