"""Tests for process managers handling external events registered via register_external_event().

Regression: register_external_event() did not set __type__ on the event class,
causing _setup_process_managers to fail with AttributeError when resolving
handler event types.
"""

import pytest
from uuid import uuid4

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.process_manager import BaseProcessManager
from protean.fields import Float, Identifier, String
from protean.utils.mixins import handle


# --- Local aggregate (belongs to this domain) ---


class Enrollment(BaseAggregate):
    student_id: Identifier()
    course_id: Identifier()
    status: String(default="pending")


class EnrollmentRequested(BaseEvent):
    enrollment_id: Identifier()
    student_id: Identifier()
    course_id: Identifier()


# --- External event (comes from another domain, no part_of) ---


class PaymentReceived(BaseEvent):
    """External event from a billing domain."""

    enrollment_id: Identifier()
    amount: Float()


# --- Process Manager that handles both local and external events ---


class EnrollmentPM(BaseProcessManager):
    enrollment_id: Identifier()
    status: String(default="new")

    @handle(EnrollmentRequested, start=True, correlate="enrollment_id")
    def on_enrollment_requested(self, event: EnrollmentRequested) -> None:
        self.enrollment_id = event.enrollment_id
        self.status = "awaiting_payment"

    @handle(PaymentReceived, correlate="enrollment_id", end=True)
    def on_payment_received(self, event: PaymentReceived) -> None:
        self.status = "confirmed"


class TestExternalEventTypeAssignment:
    """Verify that register_external_event sets __type__ on the event class."""

    def test_external_event_has_type_after_registration(self, test_domain):
        test_domain.register_external_event(
            PaymentReceived, "Billing.PaymentReceived.v1"
        )

        assert hasattr(PaymentReceived, "__type__")
        assert PaymentReceived.__type__ == "Billing.PaymentReceived.v1"

    def test_external_event_in_events_and_commands(self, test_domain):
        test_domain.register_external_event(
            PaymentReceived, "Billing.PaymentReceived.v1"
        )

        assert "Billing.PaymentReceived.v1" in test_domain._events_and_commands
        assert (
            test_domain._events_and_commands["Billing.PaymentReceived.v1"]
            is PaymentReceived
        )


class TestPMWithExternalEvents:
    """Verify that a PM can handle external events registered via register_external_event."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Enrollment)
        test_domain.register(EnrollmentRequested, part_of=Enrollment)
        test_domain.register_external_event(
            PaymentReceived, "Billing.PaymentReceived.v1"
        )
        test_domain.register(
            EnrollmentPM,
            stream_categories=["test::enrollment", "test::billing"],
        )
        test_domain.init(traverse=False)

    def test_setup_succeeds_with_external_event(self):
        """_setup_process_managers should not raise AttributeError for external events."""
        # If we get here, setup succeeded (the fixture ran without error)
        assert EnrollmentPM._handlers is not None
        assert len(EnrollmentPM._handlers) == 2

    def test_external_event_type_in_handlers_map(self):
        """The external event's type string should be a key in the PM's _handlers map."""
        assert "Billing.PaymentReceived.v1" in EnrollmentPM._handlers

    def test_full_lifecycle_with_external_event(self, test_domain):
        """A PM should handle both local and external events end-to-end."""
        enrollment_id = str(uuid4())

        # Start the PM with a local event
        EnrollmentPM._handle(
            EnrollmentRequested(
                enrollment_id=enrollment_id,
                student_id="STU-1",
                course_id="COURSE-101",
            )
        )

        stream_name = f"{EnrollmentPM.meta_.stream_category}-{enrollment_id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 1

        transition = messages[0].to_domain_object()
        assert transition.state["status"] == "awaiting_payment"

        # Complete the PM with an external event
        EnrollmentPM._handle(
            PaymentReceived(enrollment_id=enrollment_id, amount=299.99)
        )

        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 2

        final = messages[-1].to_domain_object()
        assert final.state["status"] == "confirmed"
        assert final.is_complete is True

    def test_completed_pm_skips_external_events(self, test_domain):
        """Once completed via an external event, further events should be skipped."""
        enrollment_id = str(uuid4())

        EnrollmentPM._handle(
            EnrollmentRequested(
                enrollment_id=enrollment_id,
                student_id="STU-2",
                course_id="COURSE-202",
            )
        )
        EnrollmentPM._handle(
            PaymentReceived(enrollment_id=enrollment_id, amount=199.99)
        )

        # PM is now complete; send another event — should be skipped
        EnrollmentPM._handle(PaymentReceived(enrollment_id=enrollment_id, amount=50.0))

        stream_name = f"{EnrollmentPM.meta_.stream_category}-{enrollment_id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 2  # Only the original 2 transitions
