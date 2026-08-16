"""MessageDB integration tests for ``verify()``.

``verify`` is concrete on the port, so its detection logic is exercised
exhaustively at the port level (``tests/port/test_event_store_verify.py``). These
tests confirm it runs end to end against a real MessageDB store: that ``$all``
paging and the raw-dict keys (``id``, ``position``, ``global_position``,
``stream_name``, ``data``) line up with what the adapter actually returns. The
clean path is what the adapter can produce through its normal write API, so that
is what is asserted here; the violation branches are driven at the port level.
"""

import pytest


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
        assert report.violations == []
        assert report.message_count == 3
        assert report.stream_count == 2
