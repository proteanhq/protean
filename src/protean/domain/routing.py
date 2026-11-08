"""Find the handlers registered for a message, and the projectors for a projection."""

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.core.projector import BaseProjector
from protean.exceptions import ConfigurationError
from protean.utils import fqn

if TYPE_CHECKING:
    from protean.core.projection import BaseProjection
    from protean.domain.registry import _DomainRegistry


class MessageRouter:
    """Find the handlers registered for a message, and the projectors for a projection.

    The router builds its lookup tables from the registry once, at
    construction. A router built without a registry has empty tables:
    ``handlers_for`` and ``projectors_for`` return empty sets and
    ``command_handler_for`` returns ``None``.
    """

    def __init__(self, registry: "_DomainRegistry | None" = None) -> None:
        # These hold handler/projector CLASSES (record.cls), not instances.
        self._event_streams: defaultdict[str, set[type[BaseEventHandler]]] = (
            defaultdict(set)
        )
        self._command_streams: defaultdict[str, set[type[BaseCommandHandler]]] = (
            defaultdict(set)
        )
        self._projectors: defaultdict[str, set[type[BaseProjector]]] = defaultdict(set)

        if registry is not None:
            self._build_event_streams(registry)
            self._build_command_streams(registry)

    def _build_event_streams(self, registry: "_DomainRegistry") -> None:
        for record in registry.event_handlers.values():
            stream_category = (
                record.cls.meta_.stream_category
                or record.cls.meta_.part_of.meta_.stream_category
            )
            self._event_streams[stream_category].add(record.cls)

        for record in registry.projectors.values():
            for stream_category in record.cls.meta_.stream_categories:
                self._event_streams[stream_category].add(record.cls)
                self._projectors[fqn(record.cls.meta_.projector_for)].add(record.cls)

        for record in registry.process_managers.values():
            for stream_category in record.cls.meta_.stream_categories:
                self._event_streams[stream_category].add(record.cls)

    def _build_command_streams(self, registry: "_DomainRegistry") -> None:
        for record in registry.command_handlers.values():
            self._command_streams[record.cls.meta_.part_of.meta_.stream_category].add(
                record.cls
            )

    def handlers_for(self, event: Any) -> set[Any]:
        """Return all handlers configured to run on the given event.

        For internal events (events with a ``part_of`` aggregate), looks up
        handlers by the aggregate's stream category.  External events (those
        registered via ``register_external_event``) have no ``part_of``
        aggregate, so the lookup falls back to scanning all registered stream
        categories for handlers that match the event's ``__type__``.
        """
        # Gather handlers configured to run on all events
        all_stream_handlers = self._event_streams.get("$all", set())

        stream_category = _stream_category_of(event)
        if stream_category is None:
            # Slow path: an external event has no part_of, so scan all registered
            # stream categories for handlers that match the event's __type__.
            return set.union(_external_event_handlers(self, event), all_stream_handlers)

        # Fast path for an internal event: look up by aggregate stream category
        stream_handlers = self._event_streams.get(stream_category, set())
        configured_stream_handlers = set()
        for stream_handler in stream_handlers:
            if (
                event.__class__.__type__ in stream_handler._handlers
                or "$any" in stream_handler._handlers
            ):
                configured_stream_handlers.add(stream_handler)

        return set.union(configured_stream_handlers, all_stream_handlers)

    def projectors_for(self, projection_cls: "type[BaseProjection]") -> set[Any]:
        """Return the projector classes registered for the projection.

        The returned set is the router's own table entry; callers must not
        change it.
        """
        return self._projectors.get(fqn(projection_cls), set())

    def command_handler_for(self, command: Any) -> type[BaseCommandHandler] | None:
        """Return the handler class registered for the command, or ``None``.

        Raises:
            ConfigurationError: The command is not associated with an aggregate.
        """
        if not command.meta_.part_of:
            raise ConfigurationError(
                f"Command `{command.__name__}` needs to be associated with an aggregate"
            )

        stream_category = command.meta_.part_of.meta_.stream_category

        handler_classes = self._command_streams.get(stream_category, set())
        command_type = command.__class__.__type__
        for handler_cls in handler_classes:
            if handler_cls._handlers.get(command_type):
                return handler_cls

        return None


def _stream_category_of(event: Any) -> str | None:
    """Return the stream category of the event's ``part_of`` aggregate, or
    ``None`` for an event with no ``part_of``."""
    part_of = getattr(event.meta_, "part_of", None) if hasattr(event, "meta_") else None
    if part_of is not None:
        stream_category: str | None = getattr(part_of.meta_, "stream_category", None)
        return stream_category
    return None


def _external_event_handlers(router: MessageRouter, event: Any) -> set[Any]:
    """Return the handlers, on any stream, that handle the event's ``__type__``."""
    stream_handlers = set()
    event_type = getattr(event.__class__, "__type__", None)
    if event_type:
        # External events match handlers by their concrete __type__.
        # `$any` is deliberately NOT honoured here: a `$any` handler
        # scoped to an aggregate (part_of) belongs to that aggregate's
        # stream and must not fire for unrelated external events.
        # `handlers_for` adds every handler on the `$all` stream,
        # `$any` handlers included.
        for handlers_set in router._event_streams.values():
            for handler in handlers_set:
                if event_type in handler._handlers:
                    stream_handlers.add(handler)
    return stream_handlers
