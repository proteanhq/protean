"""A message written before an adapter closes is there for the next adapter.

The test builds both adapters from the event-store registry with the
configuration under test and the name of the plugin's adapter, ``default``, so
the adapter the conformance plugin clears and closes after the test stays open.
"""

from typing import Any

import pytest

from protean.domain import Domain
from protean.infra.registry import event_stores
from protean.port.event_store import BaseEventStore, EventStoreCapabilities


def _build(domain: Domain, config: dict[str, Any]) -> BaseEventStore:
    return event_stores.get(config["provider"])("default", domain, dict(config))


@pytest.mark.requires(
    EventStoreCapabilities.DURABLE, EventStoreCapabilities.READ_STREAM
)
def test_a_reopened_store_returns_the_message_written_before_close(
    adapter_config, test_domain
):
    writer = _build(test_domain, adapter_config)
    try:
        writer.write_message("user-1", "Counted", {"n": 0})
    finally:
        writer.close()

    reopened = _build(test_domain, adapter_config)
    try:
        rows = reopened.get_stream_messages("user-1")
    finally:
        reopened.close()

    assert [(row["position"], row["data"]) for row in rows] == [(0, {"n": 0})]
