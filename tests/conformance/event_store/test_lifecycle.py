"""Members every event store has, whatever it declares: health, clear, close.

The ``clear()`` tests read back through the read members, so each names the
flags of the reads it calls.
"""

import pytest

from protean.infra.registry import event_stores
from protean.port.event_store import EventStoreCapabilities


def _write(adapter, stream_name: str, n: int) -> int:
    return adapter.write_message(stream_name, "Counted", {"n": n})


def test_capabilities_is_an_event_store_capabilities_value(adapter):
    assert isinstance(adapter.capabilities, EventStoreCapabilities)


def test_ping_returns_true_for_a_running_store(adapter):
    assert adapter.ping() is True


def test_health_reports_a_running_store_as_reachable(adapter):
    assert adapter.health().reachable is True


def test_get_connection_returns_without_raising(adapter):
    adapter.get_connection()


@pytest.mark.requires(
    EventStoreCapabilities.WRITE,
    EventStoreCapabilities.READ_STREAM,
    EventStoreCapabilities.READ_CATEGORY,
    EventStoreCapabilities.READ_ALL,
)
def test_clear_empties_every_read(adapter):
    _write(adapter, "user-1", 0)
    _write(adapter, "order-1", 1)

    adapter.clear()

    assert adapter.get_stream_messages("user-1") == []
    assert adapter.get_category_messages("user") == []
    assert adapter.get_all_messages() == []
    assert adapter.get_last_stream_message("user-1") is None
    assert adapter.get_last_category_message("user") is None
    assert adapter.get_last_message() is None
    assert list(adapter.stream_ids("user")) == []


@pytest.mark.requires(EventStoreCapabilities.WRITE, EventStoreCapabilities.READ_STREAM)
def test_a_write_after_clear_starts_the_stream_at_position_0(adapter):
    _write(adapter, "user-1", 0)
    _write(adapter, "user-1", 1)

    adapter.clear()

    assert _write(adapter, "user-1", 2) == 0
    assert [
        (row["position"], row["data"]) for row in adapter.get_stream_messages("user-1")
    ] == [(0, {"n": 2})]


def test_close_can_be_called_twice(adapter_config, test_domain):
    # A test-owned adapter, so the adapter the plugin clears after the test
    # stays open.
    store = event_stores.get(adapter_config["provider"])(
        "default", test_domain, dict(adapter_config)
    )
    store.get_connection()

    store.close()
    store.close()
