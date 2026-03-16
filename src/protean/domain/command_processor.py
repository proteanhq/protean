"""Command processing logic extracted from the Domain class.

The ``CommandProcessor`` owns command enrichment, idempotency checking,
sync/async dispatch, and command handler resolution.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import DuplicateCommandError, IncorrectUsageError
from protean.utils import DomainObjects, Processing, fqn
from protean.utils.eventing import (
    DomainMeta,
    MessageEnvelope,
    MessageHeaders,
    Metadata,
    new_correlation_id,
)
from protean.utils.globals import g
from protean.utils.reflection import id_field
from protean.utils.telemetry import get_domain_metrics

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class CommandProcessor:
    """Enrich, deduplicate, and dispatch commands.

    Instantiated once by ``Domain.__init__()`` and called by
    ``Domain.process()`` to handle the full command lifecycle.
    """

    def __init__(self, domain: Domain) -> None:
        self._domain = domain

    def enrich(
        self,
        command: BaseCommand,
        asynchronous: bool,
        idempotency_key: Optional[str] = None,
        priority: int = 0,
        correlation_id: Optional[str] = None,
    ) -> BaseCommand:
        """Enrich a command with metadata (stream, type, headers, etc.)."""
        from protean.utils.telemetry import inject_traceparent_from_context

        tracer = self._domain.tracer
        with tracer.start_as_current_span("protean.command.enrich") as span:
            span.set_attribute("protean.command.type", command.__class__.__type__)

            identifier = None
            identity_field = id_field(command)
            if identity_field:
                identifier = getattr(command, identity_field.field_name)
            else:
                identifier = str(uuid4())

            stream = f"{command.meta_.part_of.meta_.stream_category}:command-{identifier}"

            origin_stream = None
            inherited_correlation_id = correlation_id  # Caller-provided takes precedence
            causation_id = None

            if hasattr(g, "message_in_context"):
                msg_ctx = g.message_in_context
                if msg_ctx.metadata.domain.kind == "EVENT":
                    origin_stream = msg_ctx.metadata.headers.stream
                # Inherit correlation_id from parent message (if not caller-provided)
                if inherited_correlation_id is None and msg_ctx.metadata.domain:
                    inherited_correlation_id = msg_ctx.metadata.domain.correlation_id
                # Set causation_id = parent message's ID
                if msg_ctx.metadata.headers:
                    causation_id = msg_ctx.metadata.headers.id

            # Generate new correlation_id if this is a root entry point
            if inherited_correlation_id is None:
                inherited_correlation_id = new_correlation_id()

            # Capture the current OTEL span context as a traceparent header
            # so that downstream handlers can continue the distributed trace.
            traceparent = inject_traceparent_from_context()

            headers = MessageHeaders(
                id=identifier,  # FIXME Double check command ID format and construction
                type=command.__class__.__type__,
                stream=stream,
                time=command._metadata.headers.time
                if (command._metadata.headers and command._metadata.headers.time)
                else None,
                traceparent=traceparent,
                idempotency_key=idempotency_key,
            )

            # Compute envelope with checksum for integrity validation
            envelope = MessageEnvelope.build(command.payload)

            # Build domain metadata
            domain_meta = DomainMeta(
                fqn=command._metadata.domain.fqn
                if command._metadata.domain
                else command._metadata.fqn
                if hasattr(command._metadata, "fqn")
                else None,
                kind="COMMAND",
                origin_stream=origin_stream,
                version=command._metadata.domain.version
                if command._metadata.domain
                else command._metadata.version
                if hasattr(command._metadata, "version")
                else None,
                sequence_id=None,
                asynchronous=asynchronous,
                priority=priority,
                correlation_id=inherited_correlation_id,
                causation_id=causation_id,
            )

            metadata = Metadata(
                headers=headers,
                envelope=envelope,
                domain=domain_meta,
            )

            # Run command enrichers
            if self._domain._command_enrichers:
                extensions = dict(metadata.extensions)
                for enricher in self._domain._command_enrichers:
                    result = enricher(command)
                    if result:
                        extensions.update(result)
                if extensions:
                    metadata = Metadata(
                        headers=metadata.headers,
                        envelope=metadata.envelope,
                        domain=metadata.domain,
                        event_store=metadata.event_store,
                        extensions=extensions,
                    )

            command_with_metadata = command.__class__(
                command.to_dict(),
                _metadata=metadata,
            )

            return command_with_metadata

    def process(
        self,
        command: Any,
        asynchronous: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
        raise_on_duplicate: bool = False,
        priority: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Optional[Any]:
        """Process command and return results based on specified preference.

        By default, Protean does not return values after processing commands. This behavior
        can be overridden either by setting command_processing in config to "sync" or by specifying
        ``asynchronous=False`` when calling the domain's ``handle`` method.

        Args:
            command: Command to process (instance of a ``@domain.command``-decorated class)
            asynchronous (Boolean, optional): Specifies if the command should be processed asynchronously.
                Defaults to True.
            idempotency_key (str, optional): Caller-provided key for command deduplication.
                When provided, enables submission-level dedup via the idempotency store.
            raise_on_duplicate (bool): If ``True``, raises ``DuplicateCommandError``
                when a duplicate idempotency key is detected. If ``False`` (default),
                silently returns the cached result.
            priority (int, optional): Processing priority for events produced by this command.
                When priority lanes are enabled, events with priority below the configured
                threshold are routed to a backfill stream and processed only when the
                primary stream is empty. Use ``Priority`` enum values from
                ``protean.utils.processing``. If not specified, uses the value from
                the current ``processing_priority()`` context, or ``Priority.NORMAL`` (0).
            correlation_id (str, optional): Correlation ID for distributed tracing.
                When provided (e.g. from a frontend or API gateway), this ID is propagated
                to all commands and events in the causal chain. If not provided, a new
                UUID is auto-generated.

        Returns:
            Optional[Any]: Returns either the command handler's return value or nothing, based on preference.
        """
        from protean.utils.eventing import Message
        from protean.utils.processing import current_priority, processing_priority

        from protean.utils.telemetry import extract_context_from_traceparent

        domain = self._domain
        tracer = domain.tracer
        metrics = get_domain_metrics(domain)
        command_type = command.__class__.__type__
        process_start = time.monotonic()

        # Extract incoming traceparent as parent OTEL context so the
        # processing span becomes a child of the distributed trace.
        parent_ctx = None
        if command._metadata and command._metadata.headers:
            parent_ctx = extract_context_from_traceparent(
                command._metadata.headers.traceparent
            )

        with tracer.start_as_current_span(
            "protean.command.process",
            context=parent_ctx,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("protean.command.type", command.__class__.__type__)

            # If asynchronous is not specified, use the command_processing setting from config
            if asynchronous is None:
                asynchronous = domain.config["command_processing"] == Processing.ASYNC.value

            if (
                fqn(command.__class__)
                not in domain.registry._elements[DomainObjects.COMMAND.value]
            ):
                raise IncorrectUsageError(
                    f"Element {command.__class__.__name__} is not registered in domain {domain.name}"
                )

            # --- Idempotency: check for existing result ---
            store = domain.idempotency_store
            if idempotency_key and store.is_active:
                existing = store.check(idempotency_key)
                if existing and existing.get("status") == "success":
                    cached_result = existing.get("result")
                    if raise_on_duplicate:
                        raise DuplicateCommandError(
                            f"Command with idempotency key '{idempotency_key}' "
                            f"has already been processed",
                            original_result=cached_result,
                        )
                    return cached_result

            # Resolve priority: explicit param > context var > default (0)
            resolved_priority = priority if priority is not None else current_priority()

            command_with_metadata = self.enrich(
                command,
                asynchronous,
                idempotency_key=idempotency_key,
                priority=resolved_priority,
                correlation_id=correlation_id,
            )

            # Set span attributes from enriched command metadata
            cmd_meta = command_with_metadata._metadata
            if cmd_meta.headers:
                span.set_attribute("protean.command.id", str(cmd_meta.headers.id))
                span.set_attribute("protean.stream", cmd_meta.headers.stream or "")
            if cmd_meta.domain and cmd_meta.domain.correlation_id:
                span.set_attribute(
                    "protean.correlation_id", cmd_meta.domain.correlation_id
                )

            position = domain.event_store.store.append(command_with_metadata)

            if (
                not asynchronous
                or domain.config["command_processing"] == Processing.SYNC.value
            ):
                handler_class = self.handler_for(command)
                if handler_class:
                    # Extract trace metadata from the enriched command
                    message_id = cmd_meta.headers.id if cmd_meta.headers else "unknown"
                    message_type = (
                        cmd_meta.headers.type if cmd_meta.headers else "unknown"
                    )
                    stream = getattr(
                        command.meta_.part_of.meta_,
                        "stream_category",
                        "unknown",
                    )
                    handler_name = handler_class.__name__

                    emitter = domain.trace_emitter

                    # Emit handler.started trace
                    emitter.emit(
                        event="handler.started",
                        stream=stream,
                        message_id=message_id,
                        message_type=message_type,
                        handler=handler_name,
                        worker_id="api",
                    )

                    start_time = time.monotonic()
                    try:
                        # Build a Message for context propagation so that events
                        # raised during sync handling inherit trace IDs.
                        command_message = Message.from_domain_object(
                            command_with_metadata
                        )
                        g.message_in_context = command_message

                        # Set the processing priority context so that UoW.commit()
                        # can read it when creating outbox records
                        with processing_priority(resolved_priority):
                            result = handler_class._handle(command_with_metadata)
                    except Exception as exc:
                        duration_ms = (time.monotonic() - start_time) * 1000
                        duration_s = (time.monotonic() - process_start)

                        # Record exception on the OTEL span
                        from protean.utils.telemetry import set_span_error

                        set_span_error(span, exc)

                        # Record OTel metrics for failed command
                        cmd_attrs = {"command_type": command_type, "status": "error"}
                        metrics.command_processed.add(1, cmd_attrs)
                        metrics.command_duration.record(duration_s, cmd_attrs)

                        # Emit handler.failed trace
                        emitter.emit(
                            event="handler.failed",
                            stream=stream,
                            message_id=message_id,
                            message_type=message_type,
                            status="error",
                            handler=handler_name,
                            duration_ms=round(duration_ms, 2),
                            error=str(exc),
                            worker_id="api",
                        )

                        # Record failure with short TTL to allow retry
                        if idempotency_key and store.is_active:
                            store.record_error(idempotency_key, "handler_failed")
                        raise
                    finally:
                        g.pop("message_in_context", None)

                    duration_ms = (time.monotonic() - start_time) * 1000
                    duration_s = (time.monotonic() - process_start)

                    # Record OTel metrics for successful command
                    cmd_attrs = {"command_type": command_type, "status": "ok"}
                    metrics.command_processed.add(1, cmd_attrs)
                    metrics.command_duration.record(duration_s, cmd_attrs)

                    # Emit handler.completed trace
                    emitter.emit(
                        event="handler.completed",
                        stream=stream,
                        message_id=message_id,
                        message_type=message_type,
                        handler=handler_name,
                        duration_ms=round(duration_ms, 2),
                        worker_id="api",
                    )

                    # Record success
                    if idempotency_key and store.is_active:
                        store.record_success(idempotency_key, result)
                    return result

            # Async path: record counter (no duration - async processing happens later)
            async_attrs = {"command_type": command_type, "status": "ok"}
            metrics.command_processed.add(1, async_attrs)
            duration_s = time.monotonic() - process_start
            metrics.command_duration.record(duration_s, async_attrs)

            if idempotency_key and store.is_active:
                store.record_success(idempotency_key, position)

            return position

    def handler_for(self, command: Any) -> Optional[BaseCommandHandler]:
        """Return Command Handler for a specific command.

        Args:
            command: Command to process (instance of a ``@domain.command``-decorated class)

        Returns:
            Optional[BaseCommandHandler]: Command Handler registered to process the command
        """
        return self._domain.event_store.command_handler_for(command)
