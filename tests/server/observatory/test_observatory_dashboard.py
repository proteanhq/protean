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
    """Verify dashboard HTML elements are present."""

    def test_system_pulse_elements_present(self, dashboard_html):
        """System Pulse section has pulse dot, label, last event time, and engine count."""
        assert 'id="pulseDot"' in dashboard_html
        assert 'id="pulseLabel"' in dashboard_html
        assert 'id="lastEventTime"' in dashboard_html
        assert 'id="engineCountValue"' in dashboard_html

    def test_pipeline_and_backpressure_side_by_side(self, dashboard_html):
        """Pipeline and Backpressure gauges are in the same side-by-side row."""
        assert 'class="pipeline-backpressure-row"' in dashboard_html
        assert 'class="pipeline-divider"' in dashboard_html
        # Pipeline comes before backpressure in the row
        row_pos = dashboard_html.find("pipeline-backpressure-row")
        pipeline_pos = dashboard_html.find('class="pipeline"', row_pos)
        bp_pos = dashboard_html.find('class="backpressure-grid"', row_pos)
        assert pipeline_pos < bp_pos

    def test_pipeline_elements_present(self, dashboard_html):
        """Pipeline section has Published, Done count boxes and Done rate label."""
        assert 'id="pipePublished"' in dashboard_html
        assert 'id="pipeDone"' in dashboard_html
        assert 'id="rateDone"' in dashboard_html

    def test_backpressure_gauges_present(self, dashboard_html):
        """Backpressure gauges are present with correct IDs."""
        assert 'id="bpOutboxValue"' in dashboard_html
        assert 'id="bpStreamValue"' in dashboard_html
        assert 'id="bpConsumerValue"' in dashboard_html

    def test_throughput_chart_after_pipeline(self, dashboard_html):
        """Throughput chart appears AFTER the pipeline+backpressure row."""
        pipeline_row_pos = dashboard_html.find("pipeline-backpressure-row")
        sparkline_pos = dashboard_html.find('id="sparkline"')
        assert pipeline_row_pos > 0
        assert sparkline_pos > 0
        assert sparkline_pos > pipeline_row_pos

    def test_queue_depth_chart_after_throughput(self, dashboard_html):
        """Queue Depth chart appears after Throughput chart, stacked vertically."""
        sparkline_pos = dashboard_html.find('id="sparkline"')
        queue_pos = dashboard_html.find('id="queueSparkline"')
        assert sparkline_pos > 0
        assert queue_pos > 0
        assert queue_pos > sparkline_pos

    def test_no_handler_activity_section(self, dashboard_html):
        """Handler Activity section has been removed."""
        assert 'id="handlerActivityCard"' not in dashboard_html
        assert 'id="handlerGrid"' not in dashboard_html

    def test_stream_lag_detail_collapsible(self, dashboard_html):
        """Stream Lag Detail section is collapsible with correct IDs."""
        assert 'id="backpressureHeader"' in dashboard_html
        assert 'id="backpressureBody"' in dashboard_html
        assert 'onclick="toggleBackpressure()"' in dashboard_html

    def test_subscription_collapsible(self, dashboard_html):
        """Subscription section is collapsible with correct IDs and click handler."""
        assert 'id="subscriptionHeader"' in dashboard_html
        assert 'id="subscriptionBody"' in dashboard_html
        assert 'onclick="toggleSubscriptions()"' in dashboard_html

    def test_messages_collapsible(self, dashboard_html):
        """Messages section is collapsible with correct IDs and click handler."""
        assert 'id="messagesHeader"' in dashboard_html
        assert 'id="messagesBody"' in dashboard_html
        assert 'onclick="toggleMessages()"' in dashboard_html

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

    def test_collapsible_functions_defined(self, dashboard_html):
        """Collapsible toggle and summary update functions are defined."""
        assert "function toggleBackpressure()" in dashboard_html
        assert "function toggleSubscriptions()" in dashboard_html
        assert "function toggleMessages()" in dashboard_html
        assert "function updateBackpressureSummary()" in dashboard_html
        assert "function updateSubscriptionSummary()" in dashboard_html

    def test_pulse_interval_wired(self, dashboard_html):
        """System pulse is polled every second via setInterval."""
        assert "setInterval(updateSystemPulse, 1000)" in dashboard_html

    def test_no_handler_activity_tracking(self, dashboard_html):
        """Handler activity tracking has been removed."""
        assert "handlerActivity.set(" not in dashboard_html
        assert "function renderHandlerActivity()" not in dashboard_html
