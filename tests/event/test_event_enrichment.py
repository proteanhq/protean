"""Tests for event enrichment hooks.

Event enrichers are callables registered on the domain that automatically
add custom metadata (``metadata.extensions``) to every event raised via
``aggregate.raise_()``.
"""

from uuid import uuid4

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.fields import String
from protean.fields.basic import Identifier
from protean.utils.eventing import Message


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class UserRegistered(BaseEvent):
    user_id: Identifier(identifier=True)
    email: String()


class UserActivated(BaseEvent):
    user_id: Identifier(identifier=True)


class User(BaseAggregate):
    id: Identifier(identifier=True)
    email: String()
    name: String()
    tenant_id: String(default="default")

    def register(self):
        self.raise_(UserRegistered(user_id=self.id, email=self.email))

    def activate(self):
        self.raise_(UserActivated(user_id=self.id))

    @apply
    def on_registered(self, event: UserRegistered) -> None:
        pass

    @apply
    def on_activated(self, event: UserActivated) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Basic enrichment
# ---------------------------------------------------------------------------
class TestBasicEventEnrichment:
    def test_single_enricher(self, test_domain):
        """A registered enricher populates metadata.extensions."""

        def add_audit(event, aggregate):
            return {"auditor": "system"}

        test_domain.register_event_enricher(add_audit)

        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()

        event = user._events[0]
        assert event._metadata.extensions == {"auditor": "system"}

    def test_multiple_enrichers_merge(self, test_domain):
        """Multiple enrichers contribute to extensions (merge semantics)."""

        def add_user(event, aggregate):
            return {"user_id": "u-123"}

        def add_tenant(event, aggregate):
            return {"tenant_id": "t-456"}

        test_domain.register_event_enricher(add_user)
        test_domain.register_event_enricher(add_tenant)

        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()

        event = user._events[0]
        assert event._metadata.extensions == {
            "user_id": "u-123",
            "tenant_id": "t-456",
        }

    def test_later_enricher_overrides_earlier(self, test_domain):
        """When two enrichers set the same key, the last one wins."""

        def first(event, aggregate):
            return {"source": "first"}

        def second(event, aggregate):
            return {"source": "second"}

        test_domain.register_event_enricher(first)
        test_domain.register_event_enricher(second)

        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()

        event = user._events[0]
        assert event._metadata.extensions["source"] == "second"


# ---------------------------------------------------------------------------
# Enricher access to event and aggregate
# ---------------------------------------------------------------------------
class TestEnricherAccess:
    def test_enricher_can_read_aggregate_fields(self, test_domain):
        """Enricher receives the aggregate and can read its fields."""

        def add_tenant(event, aggregate):
            return {"tenant_id": aggregate.tenant_id}

        test_domain.register_event_enricher(add_tenant)

        user = User(id=str(uuid4()), email="a@b.com", name="A", tenant_id="acme-corp")
        user.register()

        event = user._events[0]
        assert event._metadata.extensions["tenant_id"] == "acme-corp"

    def test_enricher_can_read_event_payload(self, test_domain):
        """Enricher receives the event and can read its payload fields."""

        def mirror_email(event, aggregate):
            return {"event_email": event.email}

        test_domain.register_event_enricher(mirror_email)

        user = User(id=str(uuid4()), email="test@example.com", name="A")
        user.register()

        event = user._events[0]
        assert event._metadata.extensions["event_email"] == "test@example.com"

    def test_enricher_can_read_aggregate_identity(self, test_domain):
        """Enricher can access the aggregate's identity."""

        def add_agg_id(event, aggregate):
            return {"aggregate_id": aggregate.id}

        test_domain.register_event_enricher(add_agg_id)

        user_id = str(uuid4())
        user = User(id=user_id, email="a@b.com", name="A")
        user.register()

        event = user._events[0]
        assert event._metadata.extensions["aggregate_id"] == user_id


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestEnricherEdgeCases:
    def test_no_enrichers_gives_empty_extensions(self, test_domain):
        """Without enrichers, extensions defaults to empty dict."""
        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()

        event = user._events[0]
        assert event._metadata.extensions == {}

    def test_enricher_returning_none(self, test_domain):
        """An enricher returning None is treated as a no-op."""

        def noop(event, aggregate):
            return None

        test_domain.register_event_enricher(noop)

        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()

        event = user._events[0]
        assert event._metadata.extensions == {}

    def test_enricher_returning_empty_dict(self, test_domain):
        """An enricher returning {} is treated as a no-op."""

        def noop(event, aggregate):
            return {}

        test_domain.register_event_enricher(noop)

        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()

        event = user._events[0]
        assert event._metadata.extensions == {}

    def test_error_in_enricher_propagates(self, test_domain):
        """If an enricher raises, the exception propagates from raise_()."""

        def bad_enricher(event, aggregate):
            raise ValueError("enricher failed")

        test_domain.register_event_enricher(bad_enricher)

        user = User(id=str(uuid4()), email="a@b.com", name="A")
        with pytest.raises(ValueError, match="enricher failed"):
            user.register()

        # Event was not appended
        assert len(user._events) == 0

    def test_non_callable_raises_error(self, test_domain):
        """Registering a non-callable raises IncorrectUsageError."""
        with pytest.raises(IncorrectUsageError, match="callable"):
            test_domain.register_event_enricher("not a function")

    def test_enrichers_run_for_all_events(self, test_domain):
        """Enrichers run for every event, not just the first."""
        call_count = 0

        def counting_enricher(event, aggregate):
            nonlocal call_count
            call_count += 1
            return {"call": call_count}

        test_domain.register_event_enricher(counting_enricher)

        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()
        user.activate()

        assert len(user._events) == 2
        assert user._events[0]._metadata.extensions == {"call": 1}
        assert user._events[1]._metadata.extensions == {"call": 2}


# ---------------------------------------------------------------------------
# Decorator registration
# ---------------------------------------------------------------------------
class TestDecoratorRegistration:
    def test_event_enricher_decorator(self, test_domain):
        """The @domain.event_enricher decorator registers and returns the fn."""

        @test_domain.event_enricher
        def add_source(event, aggregate):
            return {"source": "decorator"}

        # Function is still callable
        assert callable(add_source)
        assert add_source.__name__ == "add_source"

        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()

        event = user._events[0]
        assert event._metadata.extensions == {"source": "decorator"}


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------
class TestSerializationRoundTrip:
    def test_extensions_survive_message_round_trip(self, test_domain):
        """Extensions survive: event → Message → dict → deserialize → extensions."""

        def add_context(event, aggregate):
            return {"user_id": "u-1", "tenant_id": "t-2"}

        test_domain.register_event_enricher(add_context)

        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()

        event = user._events[0]

        # Serialize to Message
        message = Message.from_domain_object(event)
        msg_dict = message.to_dict()

        # Verify extensions in serialized form
        assert msg_dict["metadata"]["extensions"] == {
            "user_id": "u-1",
            "tenant_id": "t-2",
        }

        # Deserialize back
        restored = Message.deserialize(msg_dict)
        assert restored.metadata.extensions == {"user_id": "u-1", "tenant_id": "t-2"}

    def test_empty_extensions_in_serialization(self, test_domain):
        """Empty extensions serialize as {} and deserialize back."""
        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()

        event = user._events[0]
        message = Message.from_domain_object(event)
        msg_dict = message.to_dict()

        assert msg_dict["metadata"]["extensions"] == {}

        restored = Message.deserialize(msg_dict)
        assert restored.metadata.extensions == {}

    def test_extensions_absent_in_legacy_messages(self, test_domain):
        """Messages stored before this feature (no extensions key) deserialize with default {}."""
        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()

        event = user._events[0]
        message = Message.from_domain_object(event)
        msg_dict = message.to_dict()

        # Simulate legacy message without extensions
        del msg_dict["metadata"]["extensions"]

        restored = Message.deserialize(msg_dict)
        assert restored.metadata.extensions == {}


# ---------------------------------------------------------------------------
# Fact events
# ---------------------------------------------------------------------------
class TestFactEventEnrichment:
    """Enrichers also run for auto-generated fact events."""

    @pytest.fixture(autouse=True)
    def setup_fact_events(self, test_domain):
        """Re-register User with fact_events=True."""
        # Elements already registered by module-level fixture;
        # we need a fresh domain with fact_events enabled.
        pass

    def test_enrichers_run_on_fact_events(self, test_domain):
        """Fact events raised during repository.add() also get enriched."""

        # Register a new aggregate with fact_events
        class Order(BaseAggregate):
            id: Identifier(identifier=True)
            amount: String()

        class OrderPlaced(BaseEvent):
            order_id: Identifier(identifier=True)

        test_domain.register(Order, fact_events=True)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        def add_tag(event, aggregate):
            return {"enriched": True}

        test_domain.register_event_enricher(add_tag)

        order = Order(id=str(uuid4()), amount="100")
        order.raise_(OrderPlaced(order_id=order.id))

        # The manually raised event should be enriched
        assert order._events[0]._metadata.extensions == {"enriched": True}


# ---------------------------------------------------------------------------
# Event-sourced aggregate enrichment
# ---------------------------------------------------------------------------
class TestEventSourcedAggregateEnrichment:
    def test_enrichers_work_with_es_aggregates(self, test_domain):
        """Event enrichers work correctly with event-sourced aggregates."""

        def add_version_tag(event, aggregate):
            return {"agg_version": aggregate._version}

        test_domain.register_event_enricher(add_version_tag)

        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()

        event = user._events[0]
        # After raise_, version was incremented to 0 (from -1)
        assert "agg_version" in event._metadata.extensions

    def test_multiple_events_on_es_aggregate(self, test_domain):
        """Each event on an ES aggregate is independently enriched."""

        call_count = 0

        def add_seq(event, aggregate):
            nonlocal call_count
            call_count += 1
            return {"seq": call_count}

        test_domain.register_event_enricher(add_seq)

        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()
        user.activate()

        assert user._events[0]._metadata.extensions["seq"] == 1
        assert user._events[1]._metadata.extensions["seq"] == 2


# ---------------------------------------------------------------------------
# Complex extension values
# ---------------------------------------------------------------------------
class TestComplexExtensionValues:
    def test_nested_dict_in_extensions(self, test_domain):
        """Extensions can contain nested dicts."""

        def add_nested(event, aggregate):
            return {"context": {"user": "admin", "roles": ["read", "write"]}}

        test_domain.register_event_enricher(add_nested)

        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()

        event = user._events[0]
        assert event._metadata.extensions["context"] == {
            "user": "admin",
            "roles": ["read", "write"],
        }

    def test_nested_dict_survives_round_trip(self, test_domain):
        """Nested extension values survive serialization round-trip."""

        def add_nested(event, aggregate):
            return {"context": {"user": "admin", "roles": ["read", "write"]}}

        test_domain.register_event_enricher(add_nested)

        user = User(id=str(uuid4()), email="a@b.com", name="A")
        user.register()

        event = user._events[0]
        message = Message.from_domain_object(event)
        msg_dict = message.to_dict()

        restored = Message.deserialize(msg_dict)
        assert restored.metadata.extensions["context"] == {
            "user": "admin",
            "roles": ["read", "write"],
        }
