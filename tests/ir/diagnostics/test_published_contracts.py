"""Diagnostics: TestPublishedContracts."""

import pytest

from protean.ir.builder import IRBuilder
from tests.ir.elements import build_published_event_domain


class TestPublishedContracts:
    """Verify published events appear in the contracts section."""

    @pytest.fixture(autouse=True)
    def setup(self):
        domain = build_published_event_domain()
        self.ir = IRBuilder(domain).build()

    def test_published_event_in_contracts(self):
        events = self.ir["contracts"]["events"]
        assert len(events) == 1

    def test_published_event_has_fqn(self):
        event = self.ir["contracts"]["events"][0]
        assert "AccountCreated" in event["fqn"]

    def test_published_event_has_type(self):
        event = self.ir["contracts"]["events"][0]
        assert "type" in event
        assert event["type"].startswith("PublishedTest.")

    def test_published_event_has_version(self):
        event = self.ir["contracts"]["events"][0]
        assert event["version"] == 1

    def test_published_event_has_fields(self):
        event = self.ir["contracts"]["events"][0]
        assert "fields" in event
        assert "account_id" in event["fields"]
        assert "holder_name" in event["fields"]

    def test_published_event_keys_are_language_neutral(self):
        """Contract entries should not use Python-specific dunder keys."""
        event = self.ir["contracts"]["events"][0]
        assert "__type__" not in event
        assert "__version__" not in event

    def test_unpublished_event_excluded(self):
        """AccountUpdated is not published and should not appear."""
        fqns = [e["fqn"] for e in self.ir["contracts"]["events"]]
        assert not any("AccountUpdated" in f for f in fqns)
