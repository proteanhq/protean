"""A memory event store that declares ``EXPECTED_VERSION`` and ignores it.

``tests/conformance/test_plugin.py`` runs the event-store suite against it to
show that the suite fails an adapter that lets a stale write through.
"""

from collections.abc import Mapping
from typing import Any

from protean.adapters.event_store.memory import MemoryEventStore


class StaleWriteEventStore(MemoryEventStore):
    def write_message(
        self,
        stream_name: str,
        message_type: str,
        data: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> int:
        return super().write_message(stream_name, message_type, data, metadata)
