"""How a ``StaleDataError`` at commit or flush is recorded in the OCC trace.

SQLAlchemy does not say which row lost the version race, so a ``conflicted``
record is made only when the session version-checked exactly one row.
"""

from protean.adapters.repository.sqlalchemy import _record_stale_conflict
from protean.utils import occ_trace


def test_one_checked_row_records_a_conflict_against_its_base():
    with occ_trace.capture() as events:
        _record_stale_conflict({"counter:1": 3})
        recorded = list(events)

    assert [
        (e["stream"], e["base"], e["outcome"], e["version_after"]) for e in recorded
    ] == [("counter:1", 3, "conflicted", None)]


def test_two_checked_rows_record_nothing():
    with occ_trace.capture() as events:
        _record_stale_conflict({"counter:1": 3, "counter:2": 5})
        recorded = list(events)

    assert recorded == []
