"""Tests for ``max_length`` bounds on Outbox string fields.

These bounds make SQL providers emit ``VARCHAR(N)`` instead of unbounded
``TEXT`` / ``VARCHAR(MAX)``, which unblocks index creation on the outbox
table. See issue #948 and the v0.16 migration guide.
"""

import pytest
from datetime import datetime, timezone

from protean.exceptions import ValidationError
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import Outbox
from protean.utils.reflection import fields

# Field -> expected max_length, per the design in issue #948.
EXPECTED_BOUNDS = {
    "message_id": 64,
    "stream_name": 255,
    "type": 255,
    "status": 32,
    "locked_by": 128,
    "correlation_id": 64,
    "causation_id": 64,
    "target_broker": 128,
}

# These remain unbounded JSON blobs and must NOT carry a max_length.
UNBOUNDED_FIELDS = ["data", "metadata_"]


@pytest.fixture(autouse=True)
def setup_outbox_domain(test_domain):
    """Register Outbox so its fields are resolved for reflection."""
    test_domain.register(Outbox)
    test_domain.init(traverse=False)


@pytest.fixture
def sample_metadata():
    return Metadata(
        headers=MessageHeaders(
            id="test-id",
            type="TestEvent",
            stream="test-stream",
            time=datetime.now(timezone.utc),
        ),
        domain=DomainMeta(
            fqn="test.TestEvent",
            kind="event",
            origin_stream="test-message-123",
            version="1.0",
            sequence_id="1",
        ),
    )


class TestOutboxFieldBoundsDeclared:
    """Each string field declares the expected max_length; blobs stay unbounded."""

    def test_all_bounded_fields_declare_expected_max_length(self):
        resolved = fields(Outbox)
        assert len(EXPECTED_BOUNDS) > 0
        for name, expected in EXPECTED_BOUNDS.items():
            assert resolved[name].max_length == expected, (
                f"{name} should bound at {expected}, got {resolved[name].max_length}"
            )

    def test_blob_fields_remain_unbounded(self):
        resolved = fields(Outbox)
        assert len(UNBOUNDED_FIELDS) > 0
        for name in UNBOUNDED_FIELDS:
            assert resolved[name].max_length is None


class TestOutboxFieldBoundsValidation:
    """Boundary behavior: max-length values are accepted, max+1 is rejected."""

    def test_value_at_bound_is_accepted(self, sample_metadata):
        outbox = Outbox(
            message_id="m" * 64,
            stream_name="s" * 255,
            type="t" * 255,
            data={"key": "value"},
            metadata_=sample_metadata,
            status="p" * 32,
            locked_by="w" * 128,
            correlation_id="c" * 64,
            causation_id="z" * 64,
            target_broker="b" * 128,
        )
        assert len(outbox.message_id) == 64
        assert len(outbox.status) == 32
        assert len(outbox.locked_by) == 128

    @pytest.mark.parametrize("field_name,bound", list(EXPECTED_BOUNDS.items()))
    def test_value_over_bound_is_rejected(self, sample_metadata, field_name, bound):
        valid = {
            "message_id": "m",
            "stream_name": "s",
            "type": "t",
            "data": {"key": "value"},
            "metadata_": sample_metadata,
        }
        valid[field_name] = "x" * (bound + 1)
        with pytest.raises(ValidationError):
            Outbox(**valid)
