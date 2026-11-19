"""The ``EventStorePort`` members of the memory event store.

The event-store conformance suite, ``tests/conformance/event_store/``, tests
the Port behaviour both built-in stores share. These tests cover what only
the memory store does.
"""

from datetime import datetime

import pytest

from protean.adapters.event_store.memory import MemoryEventStore
from protean.exceptions import ExpectedVersionError, NotSupportedError, ValidationError
from protean.port.event_store import EventStoreHealth


def _write(store, stream_name: str, n: int) -> None:
    store.write_message(stream_name, "Counted", {"n": n})


class TestConstruction:
    def test_domain_builds_the_store_named_default(self, test_domain):
        store = test_domain.event_store._adapter

        assert isinstance(store, MemoryEventStore)
        assert store.name == "default"
        assert store.domain is test_domain

    def test_store_keeps_the_event_store_settings_as_config(self, test_domain):
        store = test_domain.event_store._adapter

        assert store.config is test_domain.config["event_store"]
        assert store.config["provider"] == "memory"


class TestWrites:
    def test_a_write_with_rejected_metadata_leaves_the_stream_unchanged(
        self, test_domain
    ):
        store = test_domain.event_store._adapter
        store.write_message("testStream-123", "Event1", {"foo": "bar"})

        # Metadata without headers fails validation while the row is built.
        with pytest.raises(ValidationError):
            store.write_message("testStream-123", "Event1", {"foo": "baz"}, metadata={})

        assert [m["data"] for m in store.get_stream_messages("testStream-123")] == [
            {"foo": "bar"}
        ]
        assert store.write_message("testStream-123", "Event1", {"foo": "qux"}) == 1

    def test_a_wrong_expected_version_names_the_stream_and_its_version(
        self, test_domain
    ):
        store = test_domain.event_store._adapter
        store.write_message("testStream-1", "Event1", {"seq": "seed"})

        with pytest.raises(ExpectedVersionError) as exc_info:
            store.write_message(
                "testStream-1", "Event1", {"seq": "stale"}, expected_version=5
            )

        assert str(exc_info.value) == (
            "Wrong expected version: 5 (Stream: testStream-1, Stream Version: 0)"
        )


class TestRowTime:
    def test_every_read_returns_the_time_as_a_datetime(self, test_domain):
        store = test_domain.event_store._adapter
        _write(store, "user-1", 0)

        rows = [
            *store.get_stream_messages("user-1"),
            *store.get_category_messages("user"),
            *store.get_all_messages(),
            store.get_last_stream_message("user-1"),
            store.get_last_category_message("user"),
            store.get_last_message(),
        ]

        assert all(isinstance(row["time"], datetime) for row in rows)


class TestConsumerGroups:
    @pytest.mark.parametrize(
        "group",
        [
            {"consumer_group_member": 0, "consumer_group_size": 2},
            {"consumer_group_member": 0},
            {"consumer_group_size": 2},
        ],
        ids=["both", "member-only", "size-only"],
    )
    def test_consumer_group_arguments_raise_not_supported(self, test_domain, group):
        store = test_domain.event_store._adapter

        with pytest.raises(NotSupportedError, match="consumer groups"):
            store.get_category_messages("user", **group)


class TestHealth:
    def test_health_reports_reachable_with_no_pool(self, test_domain):
        assert test_domain.event_store._adapter.health() == EventStoreHealth(
            reachable=True, pool=None
        )

    def test_get_connection_returns_the_stored_rows(self, test_domain):
        store = test_domain.event_store._adapter
        _write(store, "user-1", 0)

        rows = store.get_connection()

        assert [(r["stream_name"], r["global_position"]) for r in rows] == [
            ("user-1", 1)
        ]


def test_changing_a_read_result_leaves_the_stored_row_unchanged(test_domain):
    store = test_domain.event_store._adapter
    store.write_message("user-1", "Counted", {"n": 0, "tags": ["a"]})

    for read in (
        store.get_stream_messages("user-1")[0],
        store.get_category_messages("user")[0],
        store.get_all_messages()[0],
        store.get_last_stream_message("user-1"),
        store.get_last_category_message("user"),
        store.get_last_message(),
    ):
        read["data"]["tags"].append("b")
        read["position"] = 99

    assert [(row["position"], row["data"]) for row in store.get_all_messages()] == [
        (0, {"n": 0, "tags": ["a"]})
    ]
