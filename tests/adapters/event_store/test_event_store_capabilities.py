"""The guarantees each event store declares through ``capabilities``."""

from typing import Any

import pytest

from protean import Domain
from protean.adapters.event_store.memory import MemoryEventStore
from protean.adapters.event_store.message_db import MessageDBStore
from protean.port.event_store import BaseEventStore, EventStoreCapabilities
from tests.shared import MESSAGE_DB_URI


class TestEventStoreCapabilityFlags:
    def test_flag_defines_exactly_the_nine_single_guarantees(self):
        assert {member.name for member in EventStoreCapabilities} == {
            "WRITE",
            "READ_STREAM",
            "READ_CATEGORY",
            "READ_ALL",
            "EXPECTED_VERSION",
            "CATEGORY_COMMIT_ORDER",
            "CONSUMER_GROUPS",
            "DURABLE",
            "SCHEMA_MANAGEMENT",
        }

    def test_basic_holds_the_read_and_write_flags(self):
        basic = EventStoreCapabilities.BASIC

        assert basic == (
            EventStoreCapabilities.WRITE
            | EventStoreCapabilities.READ_STREAM
            | EventStoreCapabilities.READ_CATEGORY
            | EventStoreCapabilities.READ_ALL
        )
        assert EventStoreCapabilities.EXPECTED_VERSION not in basic
        assert EventStoreCapabilities.CATEGORY_COMMIT_ORDER not in basic

    def test_consistent_adds_version_checks_and_commit_order(self):
        consistent = EventStoreCapabilities.CONSISTENT

        assert EventStoreCapabilities.BASIC in consistent
        assert EventStoreCapabilities.EXPECTED_VERSION in consistent
        assert EventStoreCapabilities.CATEGORY_COMMIT_ORDER in consistent
        assert EventStoreCapabilities.DURABLE not in consistent

    def test_production_adds_durability_only(self):
        production = EventStoreCapabilities.PRODUCTION

        assert production == (
            EventStoreCapabilities.CONSISTENT | EventStoreCapabilities.DURABLE
        )
        assert EventStoreCapabilities.CONSUMER_GROUPS not in production
        assert EventStoreCapabilities.SCHEMA_MANAGEMENT not in production


class TestMemoryEventStoreCapabilities:
    def test_memory_store_declares_consistent(self, test_domain):
        store = test_domain.event_store.store
        assert isinstance(store, MemoryEventStore)
        capabilities = store.capabilities

        assert capabilities == EventStoreCapabilities.CONSISTENT
        assert EventStoreCapabilities.DURABLE not in capabilities
        assert EventStoreCapabilities.CONSUMER_GROUPS not in capabilities
        assert EventStoreCapabilities.SCHEMA_MANAGEMENT not in capabilities


@pytest.mark.message_db
@pytest.mark.no_test_domain
class TestMessageDBStoreCapabilities:
    def test_message_db_store_declares_production(self):
        domain = Domain(name="Message DB Capabilities")
        domain.config["event_store"] = {
            "provider": "message_db",
            "database_uri": MESSAGE_DB_URI,
        }
        domain.init(traverse=False)

        store = domain.event_store.store
        assert isinstance(store, MessageDBStore)
        assert store.capabilities == EventStoreCapabilities.PRODUCTION
        assert EventStoreCapabilities.CONSUMER_GROUPS not in store.capabilities
        assert EventStoreCapabilities.SCHEMA_MANAGEMENT not in store.capabilities


class _StoreWithoutCapabilities(BaseEventStore):
    """Implements every abstract method of ``BaseEventStore`` except ``capabilities``."""

    def _write(self, *args: Any, **kwargs: Any) -> int:  # pragma: no cover
        raise NotImplementedError

    def _read(
        self, *args: Any, **kwargs: Any
    ) -> list[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    def _read_last_message(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    def _stream_identifiers(
        self, *args: Any, **kwargs: Any
    ) -> list[str]:  # pragma: no cover
        raise NotImplementedError

    def _stream_head_position(
        self, *args: Any, **kwargs: Any
    ) -> int:  # pragma: no cover
        raise NotImplementedError

    def _data_reset(self) -> None:  # pragma: no cover
        raise NotImplementedError


class _StoreWithCapabilities(_StoreWithoutCapabilities):
    @property
    def capabilities(self) -> EventStoreCapabilities:  # pragma: no cover
        return EventStoreCapabilities.BASIC


@pytest.mark.no_test_domain
class TestCapabilitiesIsRequired:
    def test_subclass_without_capabilities_cannot_be_instantiated(self):
        with pytest.raises(TypeError, match=r"abstract methods? '?capabilities'?"):
            _StoreWithoutCapabilities("Partial", None, {})  # type: ignore[abstract, arg-type]

    def test_subclass_with_capabilities_can_be_instantiated(self):
        store = _StoreWithCapabilities("Complete", None, {})  # type: ignore[arg-type]

        assert isinstance(store, BaseEventStore)
