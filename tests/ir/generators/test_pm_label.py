"""Tests for the process manager node label in the handler and event diagrams."""

from __future__ import annotations

import pytest

from protean.ir.generators import events, handlers


@pytest.mark.parametrize("module", [handlers, events], ids=["handlers", "events"])
class TestPmLabel:
    def test_label_names_start_and_end(self, module):
        pm = {
            "handlers": {
                "Test.B.v1": {"start": False, "end": True},
                "Test.A.v1": {"start": True, "end": False},
            }
        }
        assert module._pm_label("FulfillmentPM", pm) == "FulfillmentPM (start, end)"

    def test_label_without_lifecycle_handlers_is_bare_name(self, module):
        pm = {"handlers": {"Test.A.v1": {"start": False, "end": False}}}
        assert module._pm_label("FulfillmentPM", pm) == "FulfillmentPM"

    def test_entries_after_the_first_match_in_sorted_order_are_not_read(self, module):
        # The malformed entry comes first by insertion and last by sorted key.
        pm = {
            "handlers": {
                "Test.Z.v1": "not-a-dict",
                "Test.A.v1": {"start": True, "end": True},
            }
        }
        assert module._pm_label("FulfillmentPM", pm) == "FulfillmentPM (start, end)"
