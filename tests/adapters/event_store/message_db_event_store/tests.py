import pytest

from protean import Domain
from protean.adapters.event_store.message_db import MessageDBStore
from protean.exceptions import ConfigurationError
from tests.shared import MESSAGE_DB_PORT


@pytest.mark.message_db
class TestMessageDBEventStore:
    @pytest.fixture(autouse=True)
    def initialize_domain(self, test_domain):
        test_domain.init(traverse=False)

    def test_retrieving_message_store_from_domain(self, test_domain):
        assert test_domain.event_store is not None
        assert test_domain.event_store.store is not None
        assert isinstance(test_domain.event_store.store, MessageDBStore)

    def test_error_on_message_db_initialization(self):
        domain = Domain()
        domain.config["event_store"]["provider"] = "message_db"
        domain.config["event_store"]["database_uri"] = (
            f"postgresql://message_store@localhost:{MESSAGE_DB_PORT}/dummy"
        )
        domain.init(traverse=False)

        with pytest.raises(ConfigurationError) as exc:
            domain.event_store.store._write(
                "testStream-123",
                "Event1",
                {"foo": "bar"},
                {"domain": {"kind": "EVENT"}},
            )

        assert 'FATAL:  database "dummy" does not exist' in str(exc.value)

    def test_write_to_event_store(self, test_domain):
        position = test_domain.event_store.store._write(
            "testStream-123", "Event1", {"foo": "bar"}
        )

        assert position == 0

    def test_multiple_writes_to_event_store(self, test_domain):
        for i in range(5):
            position = test_domain.event_store.store._write(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )

        position = test_domain.event_store.store._write(
            "testStream-123", "Event1", {"foo": "bar"}
        )
        assert position == 5

    def test_reading_stream_message(self, test_domain):
        test_domain.event_store.store._write("testStream-123", "Event1", {"foo": "bar"})

        messages = test_domain.event_store.store._read("testStream-123")

        assert len(messages) == 1
        assert messages[0]["position"] == 0
        assert messages[0]["data"] == {"foo": "bar"}

    def test_reading_multiple_stream_messages(self, test_domain):
        for i in range(5):
            test_domain.event_store.store._write(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )

        messages = test_domain.event_store.store._read("testStream-123")

        assert len(messages) == 5
        assert messages[4]["data"] == {"foo": "bar4"}

    def test_reading_category_message(self, test_domain):
        test_domain.event_store.store._write("testStream-123", "Event1", {"foo": "bar"})

        messages = test_domain.event_store.store._read("testStream")

        assert len(messages) == 1
        assert messages[0]["position"] == 0
        assert messages[0]["data"] == {"foo": "bar"}

    def test_reading_multiple_category_messages(self, test_domain):
        for i in range(5):
            test_domain.event_store.store._write(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )

        messages = test_domain.event_store.store._read("testStream")

        assert len(messages) == 5
        assert messages[4]["data"] == {"foo": "bar4"}

    def test_reading_targeted_stream_messages(self, test_domain):
        for i in range(5):
            test_domain.event_store.store._write(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )
        for i in range(5):
            test_domain.event_store.store._write(
                "testStream-456", "Event1", {"foo": f"baz{i}"}
            )

        messages = test_domain.event_store.store._read("testStream-456")

        assert len(messages) == 5
        assert messages[4]["data"] == {"foo": "baz4"}

    def test_read_last_message(self, test_domain):
        for i in range(5):
            test_domain.event_store.store._write(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )

        message = test_domain.event_store.store._read_last_message("testStream-123")
        assert message["position"] == 4

    def test_read_last_message_when_there_are_no_messages(self, test_domain):
        message = test_domain.event_store.store._read_last_message("foo-bar")
        assert message is None

    def test_read_last_message_category_stream(self, test_domain):
        """read_last_message resolves a category stream (not just category-id).

        ``get_last_stream_message()`` returns None for category streams; the
        adapter must fall back to reading the category. Regression for #1073.
        """
        for i in range(5):
            test_domain.event_store.store._write(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )

        message = test_domain.event_store.store._read_last_message("testStream")
        assert message is not None
        assert message["data"]["foo"] == "bar4"  # the newest, not None

    def test_read_last_message_all_stream(self, test_domain):
        """read_last_message('$all') returns the newest global message.

        The exact #1073 failure: this returned None on Message-DB, making
        reconcile_outbox a permanent no-op (ADR-0015 crash-window recovery).
        """
        test_domain.event_store.store._write("streamA-1", "EventA", {"n": 1})
        test_domain.event_store.store._write("streamB-2", "EventB", {"n": 2})

        message = test_domain.event_store.store._read_last_message("$all")
        assert message is not None  # was None before the fix
        # The newest global message is the *last one written* — asserted on
        # content, not by mirroring the fallback's own query. The client's
        # "$all" read has no ORDER BY, so the adapter must pick by global_position.
        assert message["type"] == "EventB"
        assert message["data"]["n"] == 2
        all_msgs = test_domain.event_store.store._read("$all", no_of_messages=1_000_000)
        assert message["global_position"] == max(m["global_position"] for m in all_msgs)

    def test_read_last_message_empty_category_and_all(self, test_domain):
        """The category fallback returns None (not IndexError) on an empty store.

        Guards the ``else None`` branch for the category/`$all` path that #1073
        added — the existing None test only covers a *specific* stream.
        """
        store = test_domain.event_store.store
        assert store._read_last_message("$all") is None
        assert store._read_last_message("neverWritten") is None

    def test_stream_head_position_empty_stream(self, test_domain):
        """stream_head_position returns -1 for a stream with no messages."""
        result = test_domain.event_store.store.stream_head_position("nonexistent")
        assert result == -1

    def test_stream_head_position_with_messages(self, test_domain):
        """stream_head_position returns global_position of the newest message."""
        for i in range(5):
            test_domain.event_store.store._write(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )

        result = test_domain.event_store.store.stream_head_position("testStream")
        assert result >= 0

        # Should match the last category message's global_position
        all_msgs = test_domain.event_store.store._read(
            "testStream", no_of_messages=1_000_000
        )
        assert result == all_msgs[-1]["global_position"]

    def test_stream_head_position_per_category(self, test_domain):
        """stream_head_position returns correct head per stream category."""
        for i in range(3):
            test_domain.event_store.store._write("streamA-123", "EventA", {"idx": i})
        for i in range(2):
            test_domain.event_store.store._write("streamB-456", "EventB", {"idx": i})

        head_a = test_domain.event_store.store.stream_head_position("streamA")
        head_b = test_domain.event_store.store.stream_head_position("streamB")

        assert head_a >= 0
        assert head_b >= 0
        assert head_a != head_b
