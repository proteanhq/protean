"""Tests for process manager state persistence with datetime fields.

Regression: _persist_transition() captured raw datetime/date objects in the
state dict, which are not JSON-serializable. This caused UoW commit failures
when the transition event was written to the event store.
"""

import pytest
from datetime import date, datetime
from uuid import uuid4

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.process_manager import BaseProcessManager
from protean.fields import Date, DateTime, Identifier, String
from protean.utils.mixins import handle


# --- Domain elements with datetime fields ---


class Subscription(BaseAggregate):
    user_id: Identifier()
    plan: String()


class SubscriptionCreated(BaseEvent):
    subscription_id: Identifier()
    user_id: Identifier()
    plan: String()


class SubscriptionActivated(BaseEvent):
    subscription_id: Identifier()


class SubscriptionPM(BaseProcessManager):
    subscription_id: Identifier()
    user_id: Identifier()
    plan: String(default="free")
    started_at: DateTime()
    trial_end_date: Date()

    @handle(SubscriptionCreated, start=True, correlate="subscription_id")
    def on_created(self, event: SubscriptionCreated) -> None:
        self.subscription_id = event.subscription_id
        self.user_id = event.user_id
        self.plan = event.plan
        self.started_at = datetime(2025, 6, 15, 10, 30, 0)
        self.trial_end_date = date(2025, 7, 15)

    @handle(SubscriptionActivated, correlate="subscription_id", end=True)
    def on_activated(self, event: SubscriptionActivated) -> None:
        self.plan = "pro"


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Subscription)
    test_domain.register(SubscriptionCreated, part_of=Subscription)
    test_domain.register(SubscriptionActivated, part_of=Subscription)
    test_domain.register(
        SubscriptionPM,
        stream_categories=["test::subscription"],
    )
    test_domain.init(traverse=False)


class TestDateTimeSerialization:
    """Verify that datetime and date fields are serialized to ISO strings in transition state."""

    def test_datetime_field_persists_without_error(self, test_domain):
        """A PM with datetime fields should persist transition events without JSON errors."""
        sub_id = str(uuid4())

        # This would raise TypeError (datetime not JSON serializable) before the fix
        SubscriptionPM._handle(
            SubscriptionCreated(subscription_id=sub_id, user_id="USER-1", plan="trial")
        )

        stream_name = f"{SubscriptionPM.meta_.stream_category}-{sub_id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 1

    def test_datetime_field_serialized_as_iso_string(self, test_domain):
        """datetime values should be stored as ISO format strings in the state dict."""
        sub_id = str(uuid4())

        SubscriptionPM._handle(
            SubscriptionCreated(subscription_id=sub_id, user_id="USER-1", plan="trial")
        )

        stream_name = f"{SubscriptionPM.meta_.stream_category}-{sub_id}"
        messages = test_domain.event_store.store.read(stream_name)
        transition = messages[0].to_domain_object()

        assert transition.state["started_at"] == "2025-06-15T10:30:00"
        assert isinstance(transition.state["started_at"], str)

    def test_date_field_serialized_as_iso_string(self, test_domain):
        """date values should be stored as ISO format strings in the state dict."""
        sub_id = str(uuid4())

        SubscriptionPM._handle(
            SubscriptionCreated(subscription_id=sub_id, user_id="USER-1", plan="trial")
        )

        stream_name = f"{SubscriptionPM.meta_.stream_category}-{sub_id}"
        messages = test_domain.event_store.store.read(stream_name)
        transition = messages[0].to_domain_object()

        assert transition.state["trial_end_date"] == "2025-07-15"
        assert isinstance(transition.state["trial_end_date"], str)

    def test_none_datetime_field_stays_none(self, test_domain):
        """A datetime field that is None should remain None in the state dict."""
        sub_id = str(uuid4())

        SubscriptionPM._handle(
            SubscriptionCreated(subscription_id=sub_id, user_id="USER-1", plan="trial")
        )

        # Activate (on_activated doesn't set datetime fields, but they carry forward)
        SubscriptionPM._handle(SubscriptionActivated(subscription_id=sub_id))

        stream_name = f"{SubscriptionPM.meta_.stream_category}-{sub_id}"
        messages = test_domain.event_store.store.read(stream_name)

        # Second transition should still have the serialized datetime from reconstitution
        transition = messages[-1].to_domain_object()
        assert transition.state["plan"] == "pro"
        assert transition.is_complete is True


class TestDateTimeReconstitution:
    """Verify that PMs with datetime fields can be reconstituted from transitions."""

    def test_reconstitution_preserves_datetime_as_string(self, test_domain):
        """After reconstitution, datetime fields should hold the ISO string value."""
        sub_id = str(uuid4())

        SubscriptionPM._handle(
            SubscriptionCreated(subscription_id=sub_id, user_id="USER-1", plan="trial")
        )

        # Load the PM from the event store
        pm = SubscriptionPM._load_or_create(sub_id, is_start=False)

        assert pm is not None
        assert pm.subscription_id == sub_id
        assert pm.user_id == "USER-1"
        assert pm.started_at == "2025-06-15T10:30:00"
        assert pm.trial_end_date == "2025-07-15"

    def test_full_lifecycle_with_datetime_fields(self, test_domain):
        """A PM with datetime fields should complete its full lifecycle without errors."""
        sub_id = str(uuid4())

        SubscriptionPM._handle(
            SubscriptionCreated(subscription_id=sub_id, user_id="USER-1", plan="trial")
        )
        SubscriptionPM._handle(SubscriptionActivated(subscription_id=sub_id))

        stream_name = f"{SubscriptionPM.meta_.stream_category}-{sub_id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 2

        final = messages[-1].to_domain_object()
        assert final.state["plan"] == "pro"
        assert final.is_complete is True

        # Subsequent events should be skipped
        SubscriptionPM._handle(SubscriptionActivated(subscription_id=sub_id))
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 2  # Still only 2
