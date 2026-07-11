"""Serialization bugs the property suite would have caught, pinned as explicit
named cases so a regression is legible in the diff, not just a Hypothesis
counterexample.

* :issue:`#1078` — an all-default (falsy) value object collapsed to ``None`` on
  serialization instead of staying present.
* :issue:`#1039` — ``DateTime`` serialized via ``str()`` (space separator)
  instead of ISO 8601 (``T`` separator), so it did not round-trip.
* :issue:`#1046` — ``Date`` reached ``json.dumps`` as a ``datetime.date``
  object (not JSON-serializable) instead of an ISO string.
"""

import json
from datetime import UTC, date, datetime

import pytest

from tests.serialization.strategies import (
    Inventory,
    Scalars,
    StockLevels,
    assert_entity_roundtrip,
    assert_value_object_roundtrip,
)

pytestmark = pytest.mark.no_test_domain


class TestAllDefaultValueObject:
    """#1078: a falsy, all-default VO is present, not ``None``.

    ``tests/value_object/test_all_default_roundtrip.py`` is the canonical pin
    for this bug; the cases here restate it through the shared round-trip
    helpers so the serialization suite stays self-contained across all three
    regressions (#1039, #1046, #1078).
    """

    def test_all_default_vo_serializes_its_fields(self):
        levels = StockLevels()
        assert bool(levels) is False  # genuinely falsy — that was the trap
        assert levels.to_dict() == {"on_hand": 0, "reserved": 0}

    def test_all_default_vo_roundtrips(self):
        assert_value_object_roundtrip(StockLevels())

    def test_embedded_all_default_vo_is_present_and_roundtrips(self):
        item = Inventory(sku="SKU-1", levels=StockLevels())
        assert item.to_dict()["levels"] == {"on_hand": 0, "reserved": 0}
        assert_entity_roundtrip(item)


class TestDateTimeIsoFormat:
    """#1039: ``DateTime`` serializes as ISO 8601, not ``str()``."""

    def test_naive_datetime_uses_iso_separator(self):
        dt = datetime(2020, 1, 2, 3, 4, 5, 123456)
        serialized = Scalars(a_datetime=dt).to_dict()["a_datetime"]
        assert serialized == dt.isoformat()
        assert "T" in serialized and " " not in serialized

    def test_aware_datetime_roundtrips(self):
        dt = datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
        assert_value_object_roundtrip(Scalars(a_datetime=dt))


class TestDateJsonSerializable:
    """#1046: ``Date`` serializes to an ISO string that ``json.dumps`` accepts."""

    def test_date_is_json_serializable(self):
        serialized = Scalars(a_date=date(2021, 5, 6)).to_dict()
        assert serialized["a_date"] == "2021-05-06"
        # The whole payload must survive json.dumps without a custom encoder.
        assert json.loads(json.dumps(serialized))["a_date"] == "2021-05-06"

    def test_date_roundtrips(self):
        assert_value_object_roundtrip(Scalars(a_date=date(2021, 5, 6)))
