"""Tests for the Observatory Domain Detail Panel.

Tests for:
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

    @pytest.mark.parametrize(
        "fragment",
        [
            pytest.param('id="dv-detail-panel"', id="container"),
            pytest.param('id="dv-detail-title"', id="title"),
            pytest.param('id="dv-detail-fqn"', id="fqn-display"),
            pytest.param('id="dv-detail-content"', id="content-area"),
            pytest.param('id="dv-detail-close"', id="close-button"),
            pytest.param('id="dv-detail-backdrop"', id="backdrop"),
            pytest.param("dv-detail-header", id="header"),
            pytest.param("dv-detail-body", id="body"),
        ],
    )
    def test_panel_markup_present(self, client, fragment):
        html = client.get("/domain").text
        assert fragment in html


# ---------------------------------------------------------------------------
# Static Assets: domain-detail.js
# ---------------------------------------------------------------------------


class TestDomainDetailJS:
    """Verify the domain-detail.js module is served and well-formed."""

    def test_serves_domain_detail_js(self, client):
        response = client.get("/static/js/domain-detail.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]

    @pytest.mark.parametrize(
        "fragment",
        [
            pytest.param("var DomainDetail", id="exports-domain-detail-object"),
            pytest.param("init:", id="init-method"),
            pytest.param("show:", id="show-method"),
            pytest.param("hide:", id="hide-method"),
            pytest.param("_renderFieldsSection", id="fields-section"),
            pytest.param("_renderElementSection", id="element-section"),
            pytest.param("_renderHandlerSection", id="handler-section"),
            pytest.param("_renderInvariantsSection", id="invariants-section"),
            pytest.param("_renderRepoSection", id="repo-section"),
            pytest.param("_renderFieldsTable", id="fields-table"),
            pytest.param("Escape", id="escape-key-handler"),
            pytest.param("dv-detail-backdrop", id="backdrop-click-handler"),
            pytest.param("dv-section-toggle", id="accordion-toggle"),
            pytest.param("dv-open", id="accordion-open-class"),
        ],
    )
    def test_module_contains(self, client, fragment):
        js = client.get("/static/js/domain-detail.js").text
        assert fragment in js


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

    @pytest.mark.parametrize("call", ["DomainDetail.show", "DomainDetail.init"])
    def test_domain_js_calls_domain_detail(self, client, call):
        js = client.get("/static/js/domain.js").text
        assert call in js


# ---------------------------------------------------------------------------
# CSS: Panel Styles
# ---------------------------------------------------------------------------


class TestDetailPanelCSS:
    """Verify the CSS classes for the detail panel exist."""

    @pytest.mark.parametrize(
        "fragments",
        [
            pytest.param([".dv-detail-panel"], id="panel"),
            pytest.param([".dv-detail-backdrop"], id="backdrop"),
            pytest.param(
                [".dv-section", ".dv-section-toggle", ".dv-section-body"],
                id="section",
            ),
            pytest.param([".dv-field-table"], id="field-table"),
            pytest.param(
                [".dv-badge--id", ".dv-badge--version", ".dv-badge--published"],
                id="badge",
            ),
            pytest.param([".dv-handler-map"], id="handler-map"),
            pytest.param(["translateX", "transition"], id="slide-transition"),
        ],
    )
    def test_panel_css_present(self, client, fragments):
        css = client.get("/static/css/observatory.css").text
        for fragment in fragments:
            assert fragment in css


# ---------------------------------------------------------------------------
# Multi-Aggregate: Cluster Data for Detail Panel
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDetailPanelClusterData:
    """Verify cluster data from /api/domain/ir contains what the detail panel needs."""

    def test_cluster_has_aggregate_entry(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for cluster in data["clusters"].values():
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
        for cluster in data["clusters"].values():
            agg = cluster["aggregate"]
            assert "fields" in agg
            assert isinstance(agg["fields"], dict)
            assert len(agg["fields"]) > 0

    def test_aggregate_has_identity_field(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for cluster in data["clusters"].values():
            agg = cluster["aggregate"]
            assert "identity_field" in agg

    def test_aggregate_has_options(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for cluster in data["clusters"].values():
            agg = cluster["aggregate"]
            assert "options" in agg

    def test_command_has_type_key(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for cluster in data["clusters"].values():
            for cmd in cluster.get("commands", {}).values():
                assert "__type__" in cmd

    def test_event_has_type_key(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for cluster in data["clusters"].values():
            for evt in cluster.get("events", {}).values():
                assert "__type__" in evt

    def test_handler_has_handler_map(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for cluster in data["clusters"].values():
            for ch in cluster.get("command_handlers", {}).values():
                assert "handlers" in ch
                assert isinstance(ch["handlers"], dict)
