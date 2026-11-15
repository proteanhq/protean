"""``BaseEventStore`` sends a raw read to the Port member for its scope.

``_read_raw`` and ``_read_last_raw`` take one stream name and pick a member from
it: ``$all`` reads the whole store, a name with no ``-`` reads a category, and
any other name reads one stream.
"""

from typing import Any

import pytest

from protean.port.event_store import BaseEventStore, EventStoreCapabilities

pytestmark = pytest.mark.no_test_domain


class _RecordingStore(BaseEventStore):
    """Records each read member it is called with, and the arguments."""

    def __init__(self) -> None:
        super().__init__("default", None, {})  # type: ignore[arg-type]
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    @property
    def capabilities(self) -> EventStoreCapabilities:  # pragma: no cover
        return EventStoreCapabilities.BASIC

    def get_stream_messages(
        self, stream_name: str, position: int = 0, limit: int = 1000
    ) -> list[Any]:
        self.calls.append(("get_stream_messages", (stream_name, position, limit)))
        return []

    def get_category_messages(
        self,
        category: str,
        position: int = 0,
        limit: int = 1000,
        *,
        consumer_group_member: int | None = None,
        consumer_group_size: int | None = None,
    ) -> list[Any]:
        self.calls.append(("get_category_messages", (category, position, limit)))
        return []

    def get_all_messages(self, position: int = 0, limit: int = 1000) -> list[Any]:
        self.calls.append(("get_all_messages", (position, limit)))
        return []

    def get_last_stream_message(self, stream_name: str) -> Any:
        self.calls.append(("get_last_stream_message", (stream_name,)))
        return ("stream", stream_name)

    def get_last_category_message(self, category: str) -> Any:
        self.calls.append(("get_last_category_message", (category,)))
        return ("category", category)

    def get_last_message(self) -> Any:
        self.calls.append(("get_last_message", ()))
        return ("all",)

    # Members the dispatch never calls.
    def write_message(self, *args: Any, **kwargs: Any) -> int:  # pragma: no cover
        raise NotImplementedError

    def stream_ids(self, *args: Any, **kwargs: Any) -> list[str]:  # pragma: no cover
        raise NotImplementedError

    def ping(self) -> bool:  # pragma: no cover
        raise NotImplementedError

    def health(self) -> Any:  # pragma: no cover
        raise NotImplementedError

    def get_connection(self) -> object:  # pragma: no cover
        raise NotImplementedError

    def clear(self) -> None:  # pragma: no cover
        raise NotImplementedError


class TestReadRaw:
    def test_all_reads_the_whole_store(self):
        store = _RecordingStore()

        store._read_raw("$all", position=4, limit=7)

        assert store.calls == [("get_all_messages", (4, 7))]

    def test_name_without_a_dash_reads_a_category(self):
        store = _RecordingStore()

        store._read_raw("test::user", position=4, limit=7)

        assert store.calls == [("get_category_messages", ("test::user", 4, 7))]

    def test_name_with_a_dash_reads_one_stream(self):
        store = _RecordingStore()

        store._read_raw("test::user-1", position=4, limit=7)

        assert store.calls == [("get_stream_messages", ("test::user-1", 4, 7))]

    def test_snapshot_stream_reads_one_stream(self):
        store = _RecordingStore()

        store._read_raw("test::user:snapshot-1")

        assert store.calls == [
            ("get_stream_messages", ("test::user:snapshot-1", 0, 1000))
        ]


class TestReadLastRaw:
    def test_all_reads_the_newest_row_of_the_store(self):
        store = _RecordingStore()

        assert store._read_last_raw("$all") == ("all",)
        assert store.calls == [("get_last_message", ())]

    def test_name_without_a_dash_reads_the_newest_row_of_a_category(self):
        store = _RecordingStore()

        assert store._read_last_raw("test::user") == ("category", "test::user")
        assert store.calls == [("get_last_category_message", ("test::user",))]

    def test_name_with_a_dash_reads_the_newest_row_of_one_stream(self):
        store = _RecordingStore()

        assert store._read_last_raw("test::user-1") == ("stream", "test::user-1")
        assert store.calls == [("get_last_stream_message", ("test::user-1",))]

    def test_snapshot_stream_reads_the_newest_row_of_one_stream(self):
        store = _RecordingStore()
        stream = "test::user:snapshot-1"

        assert store._read_last_raw(stream) == ("stream", stream)
        assert store.calls == [("get_last_stream_message", (stream,))]
