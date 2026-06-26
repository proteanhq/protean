"""SQLite coverage for Outbox column DDL.

Verifies that the ``max_length`` bounds on Outbox string fields (issue #948)
flow through the SQLAlchemy adapter as ``VARCHAR(N)`` columns, while the JSON
blob fields stay unbounded.
"""

import pytest

from protean.utils.outbox import Outbox

# Field -> expected VARCHAR length emitted by the SQLAlchemy adapter.
EXPECTED_LENGTHS = {
    "message_id": 255,
    "stream_name": 255,
    "type": 255,
    "status": 32,
    "locked_by": 128,
    "correlation_id": 255,
    "causation_id": 255,
    "target_broker": 128,
}

UNBOUNDED_FIELDS = ["data", "metadata_"]


@pytest.fixture
def outbox_columns(test_domain):
    test_domain.register(Outbox)
    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Outbox)._dao
    # Create the table so the autouse data-reset fixture's DELETE has a target.
    provider = test_domain.providers["default"]
    provider._metadata.create_all(provider._engine)
    # Start from a clean slate when run in isolation against a persistent db.
    dao._delete_all()
    return dao.database_model_cls.__table__.columns


@pytest.mark.sqlite
class TestOutboxColumnDDL:
    def test_string_columns_emit_bounded_varchar(self, outbox_columns):
        assert len(EXPECTED_LENGTHS) > 0
        for name, expected in EXPECTED_LENGTHS.items():
            column = outbox_columns[name]
            assert column.type.length == expected, (
                f"{name} should emit VARCHAR({expected}), "
                f"got length={column.type.length}"
            )

    def test_blob_columns_remain_unbounded(self, outbox_columns):
        assert len(UNBOUNDED_FIELDS) > 0
        for name in UNBOUNDED_FIELDS:
            # JSON / PickleType columns carry no length bound.
            assert getattr(outbox_columns[name].type, "length", None) is None
