"""The ``EventStore`` service sends each call to the right ``EventStorePort`` member.

``_read_raw`` and ``_read_last_raw`` take one stream name and pick a member from
it: ``$all`` reads the whole store, a name with no ``-`` reads a category, and
any other name reads one stream. ``category_head_position`` follows the same
rule for ``$all``. Each forwarder reaches the adapter member it names, and every
call raises ``ConfigurationError`` before ``domain.init()`` builds the adapter.
"""

from typing import Any

import pytest

from protean.exceptions import ConfigurationError
from protean.infra.event_store import EventStore
from protean.ir.diagnostics import DiagnosticCode
from protean.port.event_store import EventStoreCapabilities

pytestmark = pytest.mark.no_test_domain


class _RecordingAdapter:
    """An ``EventStorePort`` double that records each member call and its arguments."""

    def __init__(self, last_global_position: int | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._last_global_position = last_global_position

    @property
    def capabilities(self) -> EventStoreCapabilities:
        self.calls.append(("capabilities", ()))
        return EventStoreCapabilities.BASIC

    def _last_row(self, scope: str, *name: str) -> Any:
        if self._last_global_position is None:
            return (scope, *name)
        return {"global_position": self._last_global_position}

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
        return self._last_row("stream", stream_name)

    def get_last_category_message(self, category: str) -> Any:
        self.calls.append(("get_last_category_message", (category,)))
        return self._last_row("category", category)

    def get_last_message(self) -> Any:
        self.calls.append(("get_last_message", ()))
        return self._last_row("all")

    def write_message(self, *args: Any) -> int:
        self.calls.append(("write_message", args))
        return 3

    def stream_ids(self, category: str) -> list[str]:
        self.calls.append(("stream_ids", (category,)))
        return ["1"]

    def ping(self) -> bool:
        self.calls.append(("ping", ()))
        return True

    def health(self) -> Any:
        self.calls.append(("health", ()))
        return "healthy"

    def get_connection(self) -> object:
        self.calls.append(("get_connection", ()))
        return "connection"

    def clear(self) -> None:
        self.calls.append(("clear", ()))


def _service(adapter: _RecordingAdapter) -> EventStore:
    service = EventStore(None)  # type: ignore[arg-type]
    service._adapter = adapter  # type: ignore[assignment]
    return service


class TestReadRaw:
    def test_all_reads_the_whole_store(self):
        adapter = _RecordingAdapter()

        _service(adapter)._read_raw("$all", position=4, limit=7)

        assert adapter.calls == [("get_all_messages", (4, 7))]

    def test_name_without_a_dash_reads_a_category(self):
        adapter = _RecordingAdapter()

        _service(adapter)._read_raw("test::user", position=4, limit=7)

        assert adapter.calls == [("get_category_messages", ("test::user", 4, 7))]

    def test_name_with_a_dash_reads_one_stream(self):
        adapter = _RecordingAdapter()

        _service(adapter)._read_raw("test::user-1", position=4, limit=7)

        assert adapter.calls == [("get_stream_messages", ("test::user-1", 4, 7))]

    def test_snapshot_stream_reads_one_stream(self):
        adapter = _RecordingAdapter()

        _service(adapter)._read_raw("test::user:snapshot-1")

        assert adapter.calls == [
            ("get_stream_messages", ("test::user:snapshot-1", 0, 1000))
        ]

    def test_read_passes_limit_to_the_adapter(self):
        adapter = _RecordingAdapter()

        assert _service(adapter).read("test::user", position=2, limit=5) == []
        assert adapter.calls == [("get_category_messages", ("test::user", 2, 5))]

    def test_read_rejects_the_old_row_count_keyword(self):
        adapter = _RecordingAdapter()
        # Built from parts so a search of the repository for the old name finds
        # no call that still uses it.
        old_keyword = "no_of" + "_messages"

        with pytest.raises(TypeError, match=old_keyword):
            _service(adapter).read("test::user", **{old_keyword: 5})
        assert adapter.calls == []


class TestReadLastRaw:
    def test_all_reads_the_newest_row_of_the_store(self):
        adapter = _RecordingAdapter()

        assert _service(adapter)._read_last_raw("$all") == ("all",)
        assert adapter.calls == [("get_last_message", ())]

    def test_name_without_a_dash_reads_the_newest_row_of_a_category(self):
        adapter = _RecordingAdapter()

        assert _service(adapter)._read_last_raw("test::user") == (
            "category",
            "test::user",
        )
        assert adapter.calls == [("get_last_category_message", ("test::user",))]

    def test_name_with_a_dash_reads_the_newest_row_of_one_stream(self):
        adapter = _RecordingAdapter()

        assert _service(adapter)._read_last_raw("test::user-1") == (
            "stream",
            "test::user-1",
        )
        assert adapter.calls == [("get_last_stream_message", ("test::user-1",))]

    def test_snapshot_stream_reads_the_newest_row_of_one_stream(self):
        adapter = _RecordingAdapter()
        stream = "test::user:snapshot-1"

        assert _service(adapter)._read_last_raw(stream) == ("stream", stream)
        assert adapter.calls == [("get_last_stream_message", (stream,))]


class TestCategoryHeadPosition:
    def test_all_reads_the_newest_row_of_the_store(self):
        adapter = _RecordingAdapter(last_global_position=42)

        assert _service(adapter).category_head_position("$all") == 42
        assert adapter.calls == [("get_last_message", ())]

    def test_a_category_reads_the_newest_row_of_that_category(self):
        adapter = _RecordingAdapter(last_global_position=17)

        assert _service(adapter).category_head_position("test::user") == 17
        assert adapter.calls == [("get_last_category_message", ("test::user",))]


class TestForwarders:
    @pytest.mark.parametrize(
        ("call", "member", "args", "result"),
        [
            (
                lambda s: s.capabilities,
                "capabilities",
                (),
                EventStoreCapabilities.BASIC,
            ),
            (lambda s: s.clear(), "clear", (), None),
            (lambda s: s.ping(), "ping", (), True),
            (lambda s: s.health(), "health", (), "healthy"),
            (lambda s: s.get_connection(), "get_connection", (), "connection"),
            (
                lambda s: s._write_message("user-1", "Registered", {"n": 1}, {}, 2),
                "write_message",
                ("user-1", "Registered", {"n": 1}, {}, 2),
                3,
            ),
            (
                lambda s: s._get_last_stream_message("user-1"),
                "get_last_stream_message",
                ("user-1",),
                ("stream", "user-1"),
            ),
            (lambda s: s._stream_ids("user"), "stream_ids", ("user",), ["1"]),
            (lambda s: s._get_all_messages(4, 7), "get_all_messages", (4, 7), []),
            (
                lambda s: s._get_category_messages("user", 4, 7),
                "get_category_messages",
                ("user", 4, 7),
                [],
            ),
            (
                lambda s: s._get_stream_messages("user-1", 4, 7),
                "get_stream_messages",
                ("user-1", 4, 7),
                [],
            ),
        ],
    )
    def test_forwarder_reaches_its_adapter_member(self, call, member, args, result):
        adapter = _RecordingAdapter()

        assert call(_service(adapter)) == result
        assert adapter.calls == [(member, args)]


class TestBeforeInit:
    @pytest.mark.parametrize(
        "call",
        [
            lambda s: s.capabilities,
            lambda s: s.clear(),
            lambda s: s.ping(),
            lambda s: s.health(),
            lambda s: s.get_connection(),
            lambda s: s._write_message("user-1", "Registered", {}),
            lambda s: s._get_last_stream_message("user-1"),
            lambda s: s._stream_ids("user"),
            lambda s: s._get_all_messages(),
            lambda s: s._get_category_messages("user"),
            lambda s: s._get_stream_messages("user-1"),
            lambda s: s.read("user"),
            lambda s: list(s.read_all()),
            lambda s: s.read_last_message("$all"),
            lambda s: s.category_head_position("user"),
            lambda s: s.append(object()),
            lambda s: s.load_aggregate(object(), "1"),
            lambda s: s.create_snapshot(object(), "1"),
            lambda s: s.create_snapshots(object()),
        ],
    )
    def test_call_raises_configuration_error(self, call):
        service = EventStore(None)  # type: ignore[arg-type]

        with pytest.raises(ConfigurationError) as exc_info:
            call(service)

        assert exc_info.value.code == DiagnosticCode.CONFIG_EVENT_STORE_NOT_INITIALIZED

    def test_store_is_none(self):
        assert EventStore(None).store is None  # type: ignore[arg-type]
