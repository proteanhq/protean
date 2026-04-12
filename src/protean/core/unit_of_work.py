import logging
from collections import defaultdict
from typing import Any

from protean.exceptions import (
    ConfigurationError,
    ExpectedVersionError,
    InvalidOperationError,
    TransactionError,
)
from protean.port.provider import DatabaseCapabilities
from protean.utils import Processing
from protean.utils.globals import _uow_context_stack, current_domain
from protean.utils.reflection import id_field
from protean.utils.telemetry import get_domain_metrics, set_span_error

logger = logging.getLogger(__name__)


class UnitOfWork:
    """Transaction boundary for persistence operations.

    Groups one or more repository operations into an atomic unit. Use as a
    context manager to ensure that all changes within the block are committed
    together or rolled back on error::

        with UnitOfWork():
            repo = domain.repository_for(Order)
            order = repo.get(order_id)
            order.confirm()
            repo.add(order)

    Command handlers and the ``@use_case`` decorator wrap their execution in a
    UnitOfWork automatically, so explicit usage is typically only needed in
    application services or scripts.

    The UnitOfWork maintains an identity map to track loaded aggregates and
    collects domain events raised during the transaction. On commit, events
    are persisted to the outbox and dispatched to brokers/event store.
    """

    def __init__(self) -> None:
        self.domain = current_domain
        self._in_progress = False

        self._sessions = {}
        self._messages_to_dispatch = []
        self._identity_map = defaultdict(dict)

    @property
    def in_progress(self):
        return self._in_progress

    def __enter__(self):
        # Initiate a new session as part of self
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:  # something blew up inside the block
            self.rollback()
            return False  # re-raise the original exception

        try:
            self.commit()  # happy path
        except Exception:
            self.rollback()  # commit itself failed
            raise
        finally:
            self._reset()  # close sessions, clear state

    def _add_to_identity_map(self, aggregate) -> None:
        id_f = id_field(aggregate)
        assert id_f is not None
        identifier = getattr(aggregate, id_f.field_name)
        self._identity_map[aggregate.meta_.provider][identifier] = aggregate

    def _gather_events(self):
        """Gather all events from items in the identity map"""
        all_events = defaultdict(list)
        for provider, identity_map in self._identity_map.items():
            for item in identity_map.values():
                if item._events:
                    all_events[provider].extend(item._events)
        return all_events

    def _clear_events_from_items(self):
        """Clear events from all items in the identity map"""
        for provider, items in self._identity_map.items():
            for item in items.values():
                # Clear events from the item
                item._events = []

    def start(self) -> None:
        """Begin the transaction and push this UnitOfWork onto the context stack."""
        # Log transaction capability warnings for each configured provider
        for provider_name, provider in self.domain.providers.items():
            if not provider.has_capability(DatabaseCapabilities.TRANSACTIONS):
                if provider.has_capability(DatabaseCapabilities.SIMULATED_TRANSACTIONS):
                    logger.debug(
                        "Provider '%s' uses simulated transactions. "
                        "Rollback will not undo persisted changes.",
                        provider_name,
                    )
                else:
                    logger.warning(
                        "Provider '%s' does not support transactions. "
                        "UoW will manage identity map and events "
                        "but commit/rollback are not atomic.",
                        provider_name,
                    )

        self._in_progress = True
        _uow_context_stack.push(self)

    def commit(self) -> None:  # noqa: C901
        """Commit all changes, persist outbox messages, and dispatch events.

        Raises:
            InvalidOperationError: If the UnitOfWork is not in progress.
            ExpectedVersionError: On optimistic concurrency conflict.
            TransactionError: If the underlying database commit fails.
        """
        # Raise error if there the Unit Of Work is not active
        logger.debug("uow.committing", extra={"uow_id": id(self)})
        if not self._in_progress:
            raise InvalidOperationError("UnitOfWork is not in progress")

        tracer = self.domain.tracer

        with tracer.start_as_current_span(
            "protean.uow.commit",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            # Propagate correlation and causation IDs from the message being processed
            from protean.utils.globals import g

            msg = g.get("message_in_context")
            if msg is not None and hasattr(msg, "metadata") and msg.metadata:
                domain_meta = getattr(msg.metadata, "domain", None)
                if domain_meta is not None:
                    correlation_id = getattr(domain_meta, "correlation_id", None)
                    if correlation_id:
                        span.set_attribute("protean.correlation_id", correlation_id)

                    causation_id = getattr(domain_meta, "causation_id", None)
                    if causation_id:
                        span.set_attribute("protean.causation_id", causation_id)

            self._do_commit(span)

    def _do_commit(self, span: Any) -> None:  # noqa: C901
        """Internal commit logic wrapped by the ``protean.uow.commit`` span."""
        from protean.utils.outbox import Outbox
        from protean.utils.processing import current_priority

        # Gather all events from identity map using helper method
        all_events = self._gather_events()

        # Compute event count for span attribute
        total_events = sum(len(events) for events in all_events.values())
        span.set_attribute("protean.uow.event_count", total_events)

        # Warn if multiple aggregate *classes* raised events in this UoW.
        # DDD prescribes one aggregate per transaction; modifying multiple
        # aggregates is a design smell (consider using domain events for
        # cross-aggregate coordination instead).
        aggregate_classes_with_events: set[type] = set()
        for identity_map in self._identity_map.values():
            for item in identity_map.values():
                if item._events:
                    aggregate_classes_with_events.add(type(item))
        if len(aggregate_classes_with_events) > 1:
            class_names = sorted(cls.__name__ for cls in aggregate_classes_with_events)
            logger.warning(
                "Multiple aggregate types modified in a single UnitOfWork: %s. "
                "Consider limiting each transaction to one aggregate and using "
                "domain events for cross-aggregate coordination.",
                ", ".join(class_names),
            )

        # Read the processing priority from the current context.
        # This is set by domain.process() or by a processing_priority() context manager.
        priority = current_priority()

        # Store events in the outbox as part of the transaction.
        #
        # Iterate over providers that have events (not over sessions) because
        # event-sourced aggregates are added to the identity map without
        # opening a database session — their state lives in the event store,
        # not in a relational table.  We still need a session for the outbox
        # INSERT, so one is lazily initialised here when missing.
        if self.domain.has_outbox:
            outbox_config = self.domain.config.get("outbox", {})
            internal_broker = outbox_config.get("broker", "default")
            external_brokers: list[str] = outbox_config.get("external_brokers", [])
            # When external brokers are configured, tag every row with its
            # target broker so each OutboxProcessor can filter by its own
            # broker.  When no external brokers exist, leave target_broker
            # as None for full backward compatibility.
            use_target_broker = bool(external_brokers)

            for provider_name, events in all_events.items():
                if not events:
                    continue

                # Ensure a database session exists for this provider.
                # For event-sourced aggregates no DAO call was made during
                # persistence, so the session may not have been created yet.
                if provider_name not in self._sessions:
                    self._initialize_session(provider_name)

                outbox_repo = self.domain._get_outbox_repo(provider_name)

                for event in events:
                    # Extract trace context for outbox denormalized fields
                    correlation_id = None
                    causation_id = None
                    if event._metadata and event._metadata.domain:
                        correlation_id = event._metadata.domain.correlation_id
                        causation_id = event._metadata.domain.causation_id

                    # Internal outbox row (always created)
                    outbox_message = Outbox.create_message(
                        message_id=event._metadata.headers.id,
                        stream_name=event._metadata.headers.stream,
                        message_type=event._metadata.headers.type,
                        data=event.payload,
                        metadata=event._metadata,
                        priority=priority,
                        correlation_id=correlation_id,
                        causation_id=causation_id,
                        target_broker=(internal_broker if use_target_broker else None),
                    )
                    outbox_repo._dao.save(outbox_message)

                    # External outbox rows for published events — one per
                    # external broker.  Each row is processed independently
                    # by its own OutboxProcessor instance.
                    if external_brokers and getattr(
                        event.__class__.meta_, "published", False
                    ):
                        for ext_broker in external_brokers:
                            ext_outbox = Outbox.create_message(
                                message_id=event._metadata.headers.id,
                                stream_name=event._metadata.headers.stream,
                                message_type=event._metadata.headers.type,
                                data=event.payload,
                                metadata=event._metadata,
                                priority=priority,
                                correlation_id=correlation_id,
                                causation_id=causation_id,
                                target_broker=ext_broker,
                            )
                            outbox_repo._dao.save(ext_outbox)

        # Record final session count after all lazy sessions have been initialised
        span.set_attribute("protean.uow.session_count", len(self._sessions))

        # Exit from Unit of Work
        # This is necessary to ensure that the context stack is cleared
        #   and any further operations are not considered part of this transaction
        _uow_context_stack.pop()

        # Process each provider session separately
        try:
            for provider_name, session in self._sessions.items():
                # Commit the session (includes outbox records)
                session.commit()

            # Store all events in the event store
            for provider, events in all_events.items():
                for event in events:
                    current_domain.event_store.store.append(event)

            # Dispatch messages to their designated broker
            for stream, message, broker_name in self._messages_to_dispatch:
                if broker_name and broker_name in self.domain.brokers:
                    self.domain.brokers[broker_name].publish(stream, message)
                else:
                    # No specific broker designated; publish to default
                    self.domain.brokers["default"].publish(stream, message)

            # Iteratively consume all events produced in this session
            if current_domain.config["event_processing"] == Processing.SYNC.value:
                for provider, events in all_events.items():
                    for event in events:
                        handler_classes = current_domain.handlers_for(event)
                        for handler_cls in handler_classes:
                            handler_cls._handle(event)

            # Clear events from items in identity map
            self._clear_events_from_items()

            # Record OTel metrics for successful commit
            metrics = get_domain_metrics(self.domain)
            metrics.uow_commits.add(1)
            metrics.uow_events_per_commit.record(total_events)

            logger.debug("uow.commit_successful")
        except ValueError as exc:
            logger.exception("uow.commit_failed", exc_info=True)
            set_span_error(span, exc)

            # Extact message based on message store platform in use
            if str(exc).startswith("P0001-ERROR"):
                msg = str(exc).split("P0001-ERROR:  ")[1]
            else:
                msg = str(exc)
            raise ExpectedVersionError(msg) from None
        except ConfigurationError as exc:
            # Configuration errors can be raised if events are misconfigured
            #   We just re-raise it for the client to handle.
            set_span_error(span, exc)
            raise exc
        except Exception as exc:
            logger.exception("uow.commit_failed")
            set_span_error(span, exc)
            raise TransactionError(
                f"Unit of Work commit failed: {str(exc)}",
                extra_info={
                    "original_exception": exc.__class__.__name__,
                    "original_message": str(exc),
                    "sessions": list(self._sessions.keys()),
                    "events_count": sum(len(events) for events in all_events.values()),
                    "messages_count": len(self._messages_to_dispatch),
                },
            ) from exc

        self._reset()

    def _reset(self):
        # Remove all scoped sessions — this calls close() on the underlying
        # session (releasing connections back to the pool) AND discards the
        # session from the scoped registry, preventing stale session reuse.
        for session in self._sessions.values():
            if hasattr(session, "remove"):
                session.remove()
            else:
                session.close()

        # Reset all state
        self._sessions = {}
        self._messages_to_dispatch = []
        self._identity_map = defaultdict(dict)
        self._in_progress = False

    def rollback(self) -> None:
        """Roll back all changes and close sessions.

        Raises:
            InvalidOperationError: If the UnitOfWork is not in progress.
        """
        # Raise error if the Unit Of Work is not active
        if not self._in_progress:
            raise InvalidOperationError("UnitOfWork is not in progress")

        # Exit from Unit of Work
        _uow_context_stack.pop()

        try:
            for session in self._sessions.values():
                session.rollback()

            logger.debug("uow.rollback_successful")
        except Exception as exc:
            logger.exception("uow.rollback_failed")

        self._reset()

    def _get_session(self, provider_name):
        provider = self.domain.providers[provider_name]
        assert provider is not None
        return provider.get_session()

    def _initialize_session(self, provider_name):
        new_session = self._get_session(provider_name)
        self._sessions[provider_name] = new_session
        if not new_session.is_active:
            new_session.begin()
        return new_session

    def get_session(self, provider_name):
        """Get session for provider, initializing one if it doesn't exist"""
        if provider_name in self._sessions:
            return self._sessions[provider_name]
        else:
            return self._initialize_session(provider_name)

    def register_message(
        self, stream: str, message: dict[str, Any], broker_name: str | None = None
    ) -> None:
        self._messages_to_dispatch.append((stream, message, broker_name))
