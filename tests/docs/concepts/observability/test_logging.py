"""Run the examples on ``docs/concepts/observability/logging.md``."""

import pytest
import structlog

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_structured_call_keeps_event_name_and_fields_separate():
    with structlog.testing.capture_logs() as logs:
        load_example("concepts/observability/logging/001.py")

    refunds = [entry for entry in logs if entry["event"] == "payment_refunded"]
    assert refunds == [
        {
            "event": "payment_refunded",
            "log_level": "info",
            "order_id": "ord-123",
            "amount": 19.99,
            "reason": "customer_request",
        }
    ]
