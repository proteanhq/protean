"""Command processing logic extracted from the Domain class.

The ``CommandProcessor`` owns command enrichment, idempotency checking,
sync/async dispatch, and command handler resolution.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any, NamedTuple
from uuid import uuid4

from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.unit_of_work import _uow_stack, run_after_commit
from protean.exceptions import (
    CommandExpiredError,
    DuplicateCommandError,
    IncorrectUsageError,
    ValidationError,
)
from protean.integrations.logging import (
    SECURITY_EVENT_VALIDATION_FAILED,
    log_security_event,
)
from protean.utils import DomainObjects, Processing, fqn
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageEnvelope,
    MessageHeaders,
    Metadata,
    ensure_utc,
    new_correlation_id,
)
from protean.utils.globals import g
from protean.utils.processing import current_priority, processing_priority
from protean.utils.reflection import id_field
from protean.utils.telemetry import (
    extract_context_from_traceparent,
    get_domain_metrics,
    inject_traceparent_from_context,
    set_span_error,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from protean.core.unit_of_work import UnitOfWork
    from protean.domain import Domain
    from protean.utils.idempotency import IdempotencyStore

logger = logging.getLogger(__name__)


def resolve_deadline(
    deadline: datetime | None,
    timeout: timedelta | None,
    now: datetime | None = None,
) -> datetime | None:
    """Resolve an absolute UTC deadline from ``deadline`` or ``timeout``.

    ``deadline`` and ``timeout`` are mutually exclusive. A ``timeout`` is
    converted to an absolute deadline (``now + timeout``) so it survives
    queue delays. Naive deadlines are assumed to be UTC.

    ``now`` is the reference time a ``timeout`` is measured from. It defaults to
    the real current UTC time, keeping this a pure, context-free function;
    domain callers pass ``domain.clock.now()`` so an injected clock governs the
    deadline. When only ``deadline`` is given, ``now`` is unused.
    """
    if deadline is not None and timeout is not None:
        raise IncorrectUsageError("Specify either `deadline` or `timeout`, not both.")

    if timeout is not None:
        if not isinstance(timeout, timedelta):
            raise IncorrectUsageError("`timeout` must be a `datetime.timedelta`.")
        reference = ensure_utc(now) if now is not None else datetime.now(UTC)
        return reference + timeout

    if deadline is not None:
        if not isinstance(deadline, datetime):
            raise IncorrectUsageError("`deadline` must be a `datetime.datetime`.")
        return ensure_utc(deadline)

    return None


def coerce_timeout(value: Any) -> timedelta:
    """Coerce a configured timeout (seconds number or timedelta) to a timedelta."""
    if isinstance(value, timedelta):
        return value
    # bool is an int subclass — reject it explicitly to avoid silent surprises.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return timedelta(seconds=value)
    raise IncorrectUsageError(
        f"timeout must be a number of seconds or a `datetime.timedelta`, got {value!r}"
    )


def _check_idempotency_key(store: IdempotencyStore, key: str) -> dict[str, Any] | None:
    """Return the recorded outcome for ``key``, or ``None`` if it has none.

    A key recorded earlier in the active transaction counts as a success,
    though it reaches the store only when that transaction commits.
    """
    outer_uow = _uow_stack.top
    if outer_uow is not None and key in outer_uow._pending_idempotency_results:
        return {
            "status": "success",
            "result": outer_uow._pending_idempotency_results[key],
        }
    return store.check(key)


def _record_idempotency_success(store: IdempotencyStore, key: str, result: Any) -> None:
    # Record success once the write is durable. Inside an outer UnitOfWork, a
    # later failure rolls this command's write back, and a key recorded now
    # would make the outer retry skip the command.
    outer_uow = _uow_stack.top
    if outer_uow is not None:
        outer_uow._pending_idempotency_results[key] = result
    run_after_commit(lambda: store.record_success(key, result))


def raise_if_expired(
    headers: MessageHeaders | None, command_type: str, metrics: Any = None
) -> None:
    """Raise :class:`CommandExpiredError` when the command deadline has passed.

    When a ``metrics`` registry is supplied, the ``command_expired`` counter is
    incremented before the error is raised.
    """
    if headers is not None and headers.deadline is not None and headers.is_expired():
        if metrics is not None:
            metrics.command_expired.add(1, {"command_type": command_type})
        raise CommandExpiredError(
            f"Command `{command_type}` expired at deadline "
            f"{headers.deadline.isoformat()}",
            command_type=command_type,
            deadline=headers.deadline,
        )


class _CommandLineage(NamedTuple):
    """What a command takes over from the message being handled, if any."""

    origin_stream: str | None
    correlation_id: str | None
    causation_id: str | None
    deadline: datetime | None


def _command_identifier(command: BaseCommand) -> Any:
    identity_field = id_field(command)
    if identity_field is not None and identity_field.field_name is not None:
        return getattr(command, identity_field.field_name)
    return str(uuid4())


def _inherit_lineage(
    correlation_id: str | None, deadline: datetime | None
) -> _CommandLineage:
    """Take the origin stream, correlation ID, causation ID and deadline from
    the message in context. A caller-provided ``correlation_id`` and
    ``deadline`` take precedence over the inherited ones."""
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
            # Propagate the deadline down the chain unless the caller
            # set one explicitly for this command.
            if deadline is None and msg_ctx.metadata.headers.deadline:
                deadline = msg_ctx.metadata.headers.deadline

    return _CommandLineage(
        origin_stream, inherited_correlation_id, causation_id, deadline
    )


def _root_correlation_id(correlation_id: str | None) -> str:
    # Fall back to HTTP request header correlation ID (set by middleware)
    if correlation_id is None and hasattr(g, "request_correlation_id"):
        correlation_id = g.request_correlation_id

    # Generate new correlation_id if this is a root entry point
    if correlation_id is None:
        correlation_id = new_correlation_id()

    return correlation_id


def _command_fqn(command: BaseCommand) -> str | None:
    command_fqn: str | None = None
    if command._metadata.domain:
        command_fqn = command._metadata.domain.fqn
    elif hasattr(command._metadata, "fqn"):
        command_fqn = command._metadata.fqn
    return command_fqn


def _apply_command_enrichers(
    enrichers: list[Callable[..., Any]],
    command: BaseCommand,
    metadata: Metadata,
) -> Metadata:
    """Return ``metadata`` with the enrichers' output merged into its
    extensions, or ``metadata`` itself when they add nothing."""
    extensions = dict(metadata.extensions)
    for enricher in enrichers:
        result = enricher(command)
        if result:
            extensions.update(result)
    if not extensions:
        return metadata
    return Metadata(
        headers=metadata.headers,
        envelope=metadata.envelope,
        domain=metadata.domain,
        event_store=metadata.event_store,
        extensions=extensions,
    )


def _parent_trace_context(command: Any) -> Any:
    if command._metadata and command._metadata.headers:
        return extract_context_from_traceparent(command._metadata.headers.traceparent)
    return None


def _resolve_asynchronous(domain: Domain, asynchronous: bool | None) -> bool:
    # If asynchronous is not specified, use the command_processing setting from config
    if asynchronous is None:
        return bool(domain.config["command_processing"] == Processing.ASYNC.value)
    return asynchronous


def _assert_command_registered(domain: Domain, command: Any) -> None:
    if (
        fqn(command.__class__)
        not in domain.registry._elements[DomainObjects.COMMAND.value]
    ):
        raise IncorrectUsageError(
            f"Element {command.__class__.__name__} is not registered in domain {domain.name}"
        )


def _find_processed_result(
    store: IdempotencyStore, idempotency_key: str, raise_on_duplicate: bool
) -> tuple[bool, Any]:
    """Return ``(True, cached_result)`` when ``idempotency_key`` already holds
    a success, and ``(False, None)`` otherwise.

    Raises:
        DuplicateCommandError: If the key holds a success and
            ``raise_on_duplicate`` is set.
    """
    existing = _check_idempotency_key(store, idempotency_key)
    if not (existing and existing.get("status") == "success"):
        return False, None
    cached_result = existing.get("result")
    if raise_on_duplicate:
        raise DuplicateCommandError(
            f"Command with idempotency key '{idempotency_key}' "
            f"has already been processed",
            original_result=cached_result,
        )
    return True, cached_result


def _set_command_span_attributes(span: Any, cmd_meta: Metadata) -> None:
    # Set span attributes from enriched command metadata
    if cmd_meta.headers:
        span.set_attribute("protean.command.id", str(cmd_meta.headers.id))
        span.set_attribute("protean.stream", cmd_meta.headers.stream or "")
    if cmd_meta.domain and cmd_meta.domain.correlation_id:
        span.set_attribute("protean.correlation_id", cmd_meta.domain.correlation_id)


class CommandProcessor:
    """Enrich, deduplicate, and dispatch commands.

    Instantiated once by ``Domain.__init__()`` and called by
    ``Domain.process()`` to handle the full command lifecycle.
    """

    def __init__(self, domain: Domain) -> None:
        self._domain = domain

    def _default_deadline_for(self, command: BaseCommand) -> datetime | None:
        """Resolve a default deadline from the handler option or domain config.

        Precedence: the handling command handler's ``timeout`` option wins over
        the domain-level ``command_default_timeout`` config. Returns ``None``
        when neither is configured.
        """
        timeout = None
        handler = self.handler_for(command)
        if handler is not None:
            timeout = getattr(handler.meta_, "timeout", None)
        if timeout is None:
            timeout = self._domain.config.get("command_default_timeout")
        if timeout is None:
            return None
        return resolve_deadline(
            None, coerce_timeout(timeout), now=self._domain.clock.now()
        )

    def enrich(
        self,
        command: BaseCommand,
        asynchronous: bool,
        idempotency_key: str | None = None,
        priority: int = 0,
        correlation_id: str | None = None,
        deadline: datetime | None = None,
    ) -> BaseCommand:
        """Enrich a command with metadata (stream, type, headers, etc.)."""
        tracer = self._domain.tracer
        with tracer.start_as_current_span("protean.command.enrich") as span:
            span.set_attribute("protean.command.type", command.__class__.__type__)

            identifier = _command_identifier(command)

            stream = (
                f"{command.meta_.part_of.meta_.stream_category}:command-{identifier}"
            )

            lineage = _inherit_lineage(correlation_id, deadline)
            deadline = lineage.deadline

            # Fall back to a configured default (handler option or domain config)
            # only when no deadline was provided or inherited.
            if deadline is None:
                deadline = self._default_deadline_for(command)

            resolved_correlation_id = _root_correlation_id(lineage.correlation_id)

            # Store the resolved correlation ID so the HTTP middleware can
            # reflect it in the response header (even when auto-generated).
            g.used_correlation_id = resolved_correlation_id

            # Capture the current OTEL span context as a traceparent header
            # so that downstream handlers can continue the distributed trace.
            traceparent = inject_traceparent_from_context()

            headers = MessageHeaders(
                id=identifier,
                type=command.__class__.__type__,
                stream=stream,
                time=command._metadata.headers.time
                if (command._metadata.headers and command._metadata.headers.time)
                else None,
                traceparent=traceparent,
                idempotency_key=idempotency_key,
                deadline=deadline,
            )

            # Compute envelope with checksum for integrity validation
            envelope = MessageEnvelope.build(command.payload)

            # Build domain metadata
            domain_meta = DomainMeta(
                fqn=_command_fqn(command),
                kind="COMMAND",
                origin_stream=lineage.origin_stream,
                version=command._metadata.domain.version
                if command._metadata.domain
                else getattr(command._metadata, "version", 1),
                sequence_id=None,
                asynchronous=asynchronous,
                priority=priority,
                correlation_id=resolved_correlation_id,
                causation_id=lineage.causation_id,
            )

            metadata = Metadata(
                headers=headers,
                envelope=envelope,
                domain=domain_meta,
            )

            # Run command enrichers
            if self._domain._command_enrichers:
                metadata = _apply_command_enrichers(
                    self._domain._command_enrichers, command, metadata
                )

            command_with_metadata = command.__class__(
                command.to_dict(),
                _metadata=metadata,
            )

            return command_with_metadata

    def process(
        self,
        command: Any,
        asynchronous: bool | None = None,
        idempotency_key: str | None = None,
        raise_on_duplicate: bool = False,
        priority: int | None = None,
        correlation_id: str | None = None,
        deadline: datetime | None = None,
        timeout: timedelta | None = None,
    ) -> Any | None:
        """Store a command in the event store and handle it now or later.

        The command is handled synchronously when ``asynchronous`` is ``False``
        or when the ``command_processing`` config is ``"sync"``. Otherwise the
        engine handles it later.

        When ``command_processing`` is ``"sync"`` and ``asynchronous`` is
        ``True``, a call inside an active unit of work (a handler, a
        ``@use_case`` method, a ``with UnitOfWork():`` block or an explicit
        ``UnitOfWork.start()``) defers the command. It is stored at once and
        handled after the caller's unit of work commits, in its own unit of
        work. A failure while it runs, such as a deadline that passed before
        the commit, makes the caller's commit raise ``TransactionError``. A
        rollback of the caller means the command never runs. The memory event
        store discards it with the caller's writes; an event store that writes
        outside the unit of work, such as Message DB, keeps it stored and
        unhandled.

        Args:
            command: Instance of a ``@domain.command``-decorated class.
            asynchronous: Whether to handle the command later. Defaults to the
                ``command_processing`` config.
            idempotency_key: Key for deduplicating submissions. When the
                idempotency store already holds a success for this key, the
                cached result is returned and the command is not stored again.
            raise_on_duplicate: Raise ``DuplicateCommandError`` on a duplicate
                key, instead of returning the cached result.
            priority: Processing priority for the events this command produces.
                Use ``Priority`` values from ``protean.utils.processing``.
                Defaults to the current ``processing_priority()`` context, or
                ``Priority.NORMAL``.
            correlation_id: Correlation ID carried by every command and event
                in the causal chain. A new UUID is generated when omitted.
            deadline: Absolute time after which the command must not run.
                Passed on to downstream commands in the same causal chain.
            timeout: Relative deadline, converted to ``now + timeout`` on
                submission.

        Returns:
            The command handler's return value when the command is handled
            synchronously. ``None`` when the command is deferred, and for a
            repeat of a deferred command's idempotency key in the same unit of
            work. Otherwise, the command's position in the event store.

        Raises:
            IncorrectUsageError: If the command is not registered with the
                domain, or if both ``deadline`` and ``timeout`` are given.
            DuplicateCommandError: If ``raise_on_duplicate`` is ``True`` and the
                idempotency key was already processed.
            CommandExpiredError: If the deadline has passed when a synchronous
                handler is about to run.
        """
        domain = self._domain
        tracer = domain.tracer
        metrics = get_domain_metrics(domain)
        command_type = command.__class__.__type__
        process_start = time.monotonic()

        # Populate the HTTP wide-event commands list when the FastAPI
        # middleware has installed one; absent for every other call site.
        http_commands = g.get("_http_commands_dispatched")
        if isinstance(http_commands, list):
            http_commands.append(command_type)

        # Extract incoming traceparent as parent OTEL context so the
        # processing span becomes a child of the distributed trace.
        parent_ctx = _parent_trace_context(command)

        with tracer.start_as_current_span(
            "protean.command.process",
            context=parent_ctx,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("protean.command.type", command.__class__.__type__)

            asynchronous = _resolve_asynchronous(domain, asynchronous)

            _assert_command_registered(domain, command)

            # --- Idempotency: check for existing result ---
            store = domain.idempotency_store
            if idempotency_key and store.is_active:
                is_duplicate, cached_result = _find_processed_result(
                    store, idempotency_key, raise_on_duplicate
                )
                if is_duplicate:
                    return cached_result

            # Resolve priority: explicit param > context var > default (0)
            resolved_priority = priority if priority is not None else current_priority()

            # Resolve an absolute deadline from deadline/timeout (mutually
            # exclusive), measuring any timeout from the domain's clock.
            resolved_deadline = resolve_deadline(
                deadline, timeout, now=domain.clock.now()
            )

            will_handle_sync = self._handles_in_process(asynchronous)

            handler_class = self.handler_for(command) if will_handle_sync else None

            # A command handled in this process is stored as not asynchronous,
            # so the engine's command subscription skips it instead of handling
            # it a second time. An asynchronous command with no local handler
            # keeps its flag, so a worker that has the handler still runs it.
            command_with_metadata = self.enrich(
                command,
                asynchronous and handler_class is None,
                idempotency_key=idempotency_key,
                priority=resolved_priority,
                correlation_id=correlation_id,
                deadline=resolved_deadline,
            )

            # Set span attributes from enriched command metadata
            cmd_meta = command_with_metadata._metadata
            _set_command_span_attributes(span, cmd_meta)

            # Reject stale commands before they are written to the store when
            # they will be handled synchronously (mirrors the pre-append
            # idempotency check above). Async commands are stored and the engine
            # rejects them at execution time, after any queue delay.
            if will_handle_sync:
                raise_if_expired(cmd_meta.headers, command_type, metrics)

            position = domain._require_event_store().append(command_with_metadata)

            if handler_class is not None:
                # `asynchronous=True` inside a transaction means "outside my
                # transaction": run the command once the caller commits, in its
                # own unit of work, so a conflict there never re-runs the caller.
                outer_uow = _uow_stack.top
                if asynchronous and outer_uow is not None:
                    self._defer(
                        outer_uow,
                        command_with_metadata,
                        handler_class,
                        idempotency_key,
                        resolved_priority,
                    )
                    return None

                return self._run_handler(
                    command_with_metadata,
                    handler_class,
                    span,
                    idempotency_key,
                    resolved_priority,
                    process_start,
                )

            # Async path: record enqueue (actual processing happens later)
            self._record_metrics(command_type, "enqueued", process_start)

            if idempotency_key and store.is_active:
                store.record_success(idempotency_key, position)

            return position

    def _handles_in_process(self, asynchronous: bool) -> bool:
        """Return whether the processing mode lets Protean handle the command
        itself, now or after the caller commits. Returns ``False`` only for an
        asynchronous command in an async domain. In a sync domain it returns
        ``True`` for every command, and ``process`` still leaves a command with
        no registered handler to the engine."""
        return (
            not asynchronous
            or self._domain.config["command_processing"] == Processing.SYNC.value
        )

    def _record_metrics(
        self, command_type: str, status: str, process_start: float
    ) -> None:
        metrics = get_domain_metrics(self._domain)
        attrs = {"command_type": command_type, "status": status}
        metrics.command_processed.add(1, attrs)
        metrics.command_duration.record(time.monotonic() - process_start, attrs)

    def _defer(
        self,
        uow: UnitOfWork,
        command: BaseCommand,
        handler_class: type[BaseCommandHandler],
        idempotency_key: str | None,
        priority: int,
    ) -> None:
        """Handle ``command`` once ``uow`` has committed."""
        uow._deferred_commands.append(
            partial(
                self._run_deferred, command, handler_class, idempotency_key, priority
            )
        )
        # A repeat of the key in this transaction finds it here and returns None
        # instead of deferring a second copy. The outcome reaches the store when
        # the command runs.
        if idempotency_key and self._domain.idempotency_store.is_active:
            uow._pending_idempotency_results[idempotency_key] = None
        # No metric yet: the run records one, "ok" or "error", or counts the
        # command as expired. A run whose idempotency key already has a
        # recorded success returns early and records no metric.

    def _run_deferred(
        self,
        command: BaseCommand,
        handler_class: type[BaseCommandHandler],
        idempotency_key: str | None,
        priority: int,
    ) -> None:
        """Handle a command deferred to the commit of the unit of work it was
        processed in.

        Does not run the handler when ``idempotency_key`` already has a
        recorded success.

        Raises:
            CommandExpiredError: If the command's deadline passed before it ran.
                The handler does not run.
        """
        process_start = time.monotonic()
        command_type = command.__class__.__type__
        headers = command._metadata.headers
        store = self._domain.idempotency_store

        # A sync event handler of the same commit runs before this command and
        # outside the caller's unit of work, so it can run the same key first.
        if idempotency_key and store.is_active:
            existing = store.check(idempotency_key)
            if existing and existing.get("status") == "success":
                return

        with self._domain.tracer.start_as_current_span(
            "protean.command.process",
            context=extract_context_from_traceparent(
                headers.traceparent if headers else None
            ),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("protean.command.type", command_type)
            try:
                raise_if_expired(
                    headers, command_type, get_domain_metrics(self._domain)
                )
            except CommandExpiredError as exc:
                set_span_error(span, exc)
                # An error record, not a success, so a repeat call runs again.
                if idempotency_key and store.is_active:
                    store.record_error(idempotency_key, "command_expired")
                raise

            self._run_handler(
                command, handler_class, span, idempotency_key, priority, process_start
            )

    def _run_handler(
        self,
        command: BaseCommand,
        handler_class: type[BaseCommandHandler],
        span: Any,
        idempotency_key: str | None,
        priority: int,
        process_start: float,
    ) -> Any:
        """Run ``handler_class`` on an enriched command and return its result.

        Records the outcome on the span, the metrics, the trace emitter and,
        when ``idempotency_key`` is given, the idempotency store.
        """
        domain = self._domain
        store = domain.idempotency_store
        command_type = command.__class__.__type__
        cmd_meta = command._metadata

        # Extract trace metadata from the enriched command
        message_id = cmd_meta.headers.id if cmd_meta.headers else "unknown"
        message_type = cmd_meta.headers.type if cmd_meta.headers else "unknown"
        stream = getattr(command.meta_.part_of.meta_, "stream_category", "unknown")
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
        # Save any existing message context (e.g. a broker stub message) so it
        # can be restored after this command finishes. This keeps the outer
        # correlation chain intact when a subscriber dispatches multiple
        # commands.
        _prev_context = g.get("message_in_context")
        try:
            # Build a Message for context propagation so that events raised
            # during sync handling inherit trace IDs.
            g.message_in_context = Message.from_domain_object(command)

            # Set the processing priority context so that UoW.commit() can read
            # it when creating outbox records
            with processing_priority(priority):
                result = handler_class._handle(command)
        # records the failure on span and metrics, then re-raises
        except Exception as exc:
            duration_ms = (time.monotonic() - start_time) * 1000

            # Record exception on the OTEL span
            set_span_error(span, exc)

            # Record OTel metrics for failed command
            self._record_metrics(command_type, "error", process_start)

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

            # Validation errors that cross the command boundary are potential
            # abuse/attack signals — route them to the dedicated
            # protean.security logger so operators can alert independently of
            # the access log.
            if isinstance(exc, ValidationError):
                self._emit_validation_failed(exc, command_type, handler_name)

            # Record failure with short TTL to allow retry
            if idempotency_key and store.is_active:
                store.record_error(idempotency_key, "handler_failed")
            raise
        finally:
            # Restore the previous message context (or remove if there was
            # none) so the outer caller's context is preserved.
            if _prev_context is not None:
                g.message_in_context = _prev_context
            else:
                g.pop("message_in_context", None)

        duration_ms = (time.monotonic() - start_time) * 1000

        # Record OTel metrics for successful command
        self._record_metrics(command_type, "ok", process_start)

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

        if idempotency_key and store.is_active:
            _record_idempotency_success(store, idempotency_key, result)
        return result

    def handler_for(self, command: Any) -> type[BaseCommandHandler] | None:
        """Return Command Handler for a specific command.

        Args:
            command: Command to process (instance of a ``@domain.command``-decorated class)

        Returns:
            Optional[type[BaseCommandHandler]]: Command Handler class registered to
            process the command
        """
        return self._domain.event_store.command_handler_for(command)

    @staticmethod
    def _emit_validation_failed(
        exc: ValidationError, command_type: str, handler_name: str
    ) -> None:
        """Route a boundary-crossing ``ValidationError`` to ``protean.security``.

        Sibling exceptions (``InvalidOperationError``, ``InvalidStateError``)
        emit themselves via :func:`protean.exceptions._emit_security_event`
        when raised inside handler context, so this path covers the remaining
        ``ValidationError`` case only.
        """
        log_security_event(
            SECURITY_EVENT_VALIDATION_FAILED,
            command_type=command_type,
            handler=handler_name,
            error=str(exc)[:256],
        )
