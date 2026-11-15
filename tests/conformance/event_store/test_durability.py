"""A message written before the adapter closes is there for the next adapter.

The second adapter comes from the event-store registry with the configuration
under test and the name of the plugin's adapter, ``default``. The test closes
it. The plugin then clears and closes the first adapter, which this test has
already closed.
"""

import pytest

from protean.infra.registry import event_stores
from protean.port.event_store import EventStoreCapabilities


@pytest.mark.requires(EventStoreCapabilities.DURABLE)
def test_a_reopened_store_returns_the_message_written_before_close(
    adapter, adapter_config, test_domain
):
    adapter.write_message("user-1", "Counted", {"n": 0})
    adapter.close()

    reopened = event_stores.get(adapter_config["provider"])(
        "default", test_domain, dict(adapter_config)
    )
    try:
        rows = reopened.get_stream_messages("user-1")
    finally:
        reopened.close()

    assert [(row["position"], row["data"]) for row in rows] == [(0, {"n": 0})]
