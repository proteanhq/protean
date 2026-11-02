"""MessageDB integration tests for ``verify()``.

``verify`` is concrete on the port, so its detection logic is exercised
exhaustively at the port level (``tests/port/test_event_store_verify.py``). These
tests confirm it runs end to end against a real MessageDB store: that ``$all``
paging and the raw-dict keys (``id``, ``position``, ``global_position``,
``stream_name``, ``data``) line up with what the adapter actually returns. The
clean path is what the adapter produces through its normal write API. The one
violation asserted here is a NULL or non-object ``data`` column, which Message
DB allows and which the client must hand to ``verify`` instead of failing on it;
the other violation branches are driven at the port level.
"""

import pytest

from protean.adapters.event_store.message_db import _superuser_connection


@pytest.mark.message_db
class TestMessageDBVerify:
    @pytest.fixture(autouse=True)
    def initialize_domain(self, test_domain):
        test_domain.init(traverse=False)

    def test_empty_store_passes(self, test_domain):
        report = test_domain.event_store.store.verify()

        assert report.ok is True
        assert report.message_count == 0

    def test_clean_store_with_events_and_snapshot_passes(self, test_domain):
        store = test_domain.event_store.store
        metadata = {
            "domain": {"kind": "EVENT"},
            "headers": {"type": "Registered", "stream": "test::user-abc"},
        }
        store._write("test::user-abc", "Registered", {"n": 1}, metadata)
        store._write("test::user-abc", "Renamed", {"n": 2}, metadata)
        store._write("test::user:snapshot-abc", "SNAPSHOT", {"_version": 1})

        report = store.verify()

        assert report.ok is True
        assert report.violations == ()
        assert report.message_count == 3
        assert report.stream_count == 2

    @pytest.mark.parametrize(
        "body, detail",
        [
            (None, "Message data is NULL."),
            ("[]", "Message data is a list, not an object."),
        ],
        ids=["null", "array"],
    )
    def test_message_with_null_or_non_object_data_is_reported(
        self, test_domain, body, detail
    ):
        store = test_domain.event_store.store
        metadata = {
            "domain": {"kind": "EVENT"},
            "headers": {"type": "Registered", "stream": "test::user-abc"},
        }
        for n in range(3):
            store._write("test::user-abc", "Registered", {"n": n}, metadata)

        # The ``message_store`` role cannot UPDATE, so connect as ``postgres``.
        conn = _superuser_connection(test_domain.config["event_store"]["database_uri"])
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE message_store.messages SET data = %s::jsonb "
                    "WHERE stream_name = %s AND position = 1",
                    (body, "test::user-abc"),
                )
            conn.commit()
        finally:
            conn.close()

        report = store.verify()

        assert report.ok is False
        assert len(report.violations) == 1
        violation = report.violations[0]
        assert violation.kind == store.VERIFY_MALFORMED_MESSAGE
        assert violation.stream == "test::user-abc"
        assert violation.position == 1
        assert violation.detail == detail
