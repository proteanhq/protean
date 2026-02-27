"""Tests for Observatory dashboard HTML structure and JavaScript wiring.

These tests load the dashboard HTML via TestClient and verify that the
expected element IDs, section ordering, and JavaScript functions exist.
No JS runtime is needed — these are string/pattern assertions on the
served HTML.
"""

import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory


@pytest.fixture
def observatory(test_domain):
    """Observatory instance backed by a real domain."""
    return Observatory(domains=[test_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


@pytest.fixture
def dashboard_html(client):
    """Fetch the dashboard HTML once per test class."""
    response = client.get("/")
    assert response.status_code == 200
    return response.text


@pytest.mark.redis
class TestDashboardStructure:
    """Verify new dashboard HTML elements are present."""

    def test_system_pulse_elements_present(self, dashboard_html):
        """System Pulse section has pulse dot, label, last event time, and engine count."""
        assert 'id="pulseDot"' in dashboard_html
        assert 'id="pulseLabel"' in dashboard_html
        assert 'id="lastEventTime"' in dashboard_html
        assert 'id="engineCountValue"' in dashboard_html

    def test_throughput_chart_promoted(self, dashboard_html):
        """Throughput chart (sparkline canvas) appears BEFORE the pipeline section."""
        sparkline_pos = dashboard_html.find('id="sparkline"')
        pipeline_pos = dashboard_html.find('class="pipeline"')
        assert sparkline_pos > 0, "sparkline element not found"
        assert pipeline_pos > 0, "pipeline element not found"
        assert sparkline_pos < pipeline_pos, (
            "Throughput chart should appear before the pipeline section"
        )

    def test_pipeline_elements_present(self, dashboard_html):
        """Pipeline section has Published, Done count boxes and Done rate label."""
        assert 'id="pipePublished"' in dashboard_html
        assert 'id="pipeDone"' in dashboard_html
        assert 'id="rateDone"' in dashboard_html

    def test_handler_activity_section_present(self, dashboard_html):
        """Handler Activity card and grid are present."""
        assert 'id="handlerActivityCard"' in dashboard_html
        assert 'id="handlerGrid"' in dashboard_html

    def test_backpressure_collapsible(self, dashboard_html):
        """Backpressure section is collapsible with correct IDs and click handler."""
        assert 'id="backpressureHeader"' in dashboard_html
        assert 'id="backpressureBody"' in dashboard_html
        assert 'onclick="toggleBackpressure()"' in dashboard_html

    def test_subscription_collapsible(self, dashboard_html):
        """Subscription section is collapsible with correct IDs and click handler."""
        assert 'id="subscriptionHeader"' in dashboard_html
        assert 'id="subscriptionBody"' in dashboard_html
        assert 'onclick="toggleSubscriptions()"' in dashboard_html

    def test_no_activity_overlay_present(self, dashboard_html):
        """No-activity overlay exists for the throughput chart."""
        assert 'id="noActivityOverlay"' in dashboard_html


@pytest.mark.redis
class TestDashboardJavaScript:
    """Verify JavaScript functions are defined and wired correctly."""

    def test_system_pulse_functions_defined(self, dashboard_html):
        """System Pulse JS functions are defined."""
        assert "function updateSystemPulse()" in dashboard_html
        assert "function formatRelativeTime(" in dashboard_html
        assert "function updateEngineStatus(" in dashboard_html

    def test_handler_activity_functions_defined(self, dashboard_html):
        """Handler Activity rendering function is defined."""
        assert "function renderHandlerActivity()" in dashboard_html

    def test_collapsible_functions_defined(self, dashboard_html):
        """Collapsible toggle and summary update functions are defined."""
        assert "function toggleBackpressure()" in dashboard_html
        assert "function toggleSubscriptions()" in dashboard_html
        assert "function updateBackpressureSummary()" in dashboard_html
        assert "function updateSubscriptionSummary()" in dashboard_html

    def test_pulse_interval_wired(self, dashboard_html):
        """System pulse is polled every second via setInterval."""
        assert "setInterval(updateSystemPulse, 1000)" in dashboard_html

    def test_handler_activity_tracking_in_sse(self, dashboard_html):
        """SSE handler updates the handlerActivity map."""
        assert "handlerActivity.set(data.handler" in dashboard_html
