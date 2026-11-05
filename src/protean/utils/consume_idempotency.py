"""Consume-side idempotency — a processed-message marker for exactly-once consumers.

Event delivery to projectors is **at-least-once**: after a publish-then-crash the
outbox lock expires and the message is re-published, and a broker redelivery
replays a message whose read-model write already committed but was not yet
acked. A non-idempotent projector (``total += 1``) therefore double-applies a
redelivered event and corrupts its read model.

A projector marked ``idempotent=True`` records a ``(message_id, handler)`` marker
in the **same UnitOfWork** as its read-model write. On redelivery the marker is
found and the handler is skipped.

The strength of the guarantee depends on the projection's provider:

- On a **transactional (relational) provider** the marker and the read-model
  write share one transaction (truly atomic), and the composite unique index is
  materialized, so two *concurrent* redeliveries collide on the index and only
  one commits — exactly-once even under concurrency.
- On the **in-memory** provider the marker table exists but the provider
  enforces neither the unique index nor real transactions, so only the
  sequential ``is_processed`` skip applies. That still fixes the common
  redelivery case (the reported bug), but it is not atomic and not
  concurrency-safe. In-memory is a development provider; production idempotency
  wants a relational projection.
- For a **cache-backed** projection there is no marker at all (the option
  no-ops); such projectors must be written as idempotent upserts.

A broker subscriber marked ``idempotent=True`` gets the same marker, keyed on
the payload's ``metadata.headers.id`` and the subscriber's fully-qualified name,
and written to the subscriber's ``provider`` in the same UnitOfWork as its
writes. A payload with no such id, or one longer than the marker column, is an
error: the subscriber does not run.

See ADR-0017.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.index import Index
from protean.core.repository import BaseRepository
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import InsufficientDataError
from protean.fields import Auto
from protean.utils import StdlibDatetime, fqn
from protean.utils.globals import current_domain
from protean.utils.query import Q

logger = logging.getLogger(__name__)

MESSAGE_ID_MAX_LENGTH = 255


class ProcessedMessage(BaseAggregate):
    """A marker recording that a handler has processed a message.

    ``handler`` is the fully-qualified handler identity: ``module.Class.method``
    for a projector method and ``module.Class`` for a subscriber, so that each
    distinct handler dedupes the same message independently.
    """

    id = Auto(identifier=True)

    # ``message_id`` is a composite Protean message id (headers.id), e.g.
    # ``testdomain::order-<aggregate-id>-3``, not a bare UUID — so it needs the
    # same 255 ceiling as the outbox table for the (message_id, handler) index.
    message_id: Annotated[str, Field(max_length=MESSAGE_ID_MAX_LENGTH)]
    handler: Annotated[str, Field(max_length=255)]
    # ``mark()`` stamps this from the domain clock, so a marker's age is measured
    # on the same clock ``cleanup_old_markers`` reads. The default factory only
    # covers direct construction: it gets no domain argument and may run with no
    # domain context active, so it falls back to real UTC.
    processed_at: StdlibDatetime = Field(default_factory=lambda: datetime.now(UTC))


# On a relational provider the composite unique index is the concurrency
# guarantee: it rejects a second marker for the same (message_id, handler), so
# concurrent redeliveries cannot both commit. Providers that do not materialize
# the index (in-memory) fall back to the sequential is_processed() check only.
PROCESSED_MESSAGE_INDEXES = [
    Index("message_id", "handler", unique=True),
]


class ProcessedMessageRepository(BaseRepository):
    """Repository for the consume-side idempotency marker."""

    def is_processed(self, message_id: str, handler: str) -> bool:
        """Whether ``handler`` has already processed ``message_id``."""
        rows = (
            self._dao.query.filter(message_id=message_id, handler=handler)
            .limit(1)  # existence check — the pair is unique, one row suffices
            .all(with_total=False)
            .items
        )
        return len(rows) > 0

    def mark(self, message_id: str, handler: str) -> None:
        """Record that ``handler`` has processed ``message_id`` (in the active UoW)."""
        self._dao.save(
            ProcessedMessage(
                message_id=message_id,
                handler=handler,
                processed_at=self._dao.domain.clock.now(),
            )
        )

    def cleanup_old_markers(self, retention_hours: int, batch_size: int) -> int:
        """Delete markers older than ``retention_hours``, in bounded batches.

        A marker is only useful while its event can still be redelivered, so
        markers older than the redelivery/recovery window are safe to prune.
        Delegates to :meth:`BaseRepository._delete_in_batches` so a large backlog
        clears without one long-held lock. Returns the number of markers deleted.
        """
        # A negative window puts the threshold in the future, which would delete
        # every marker (including just-written ones) and reopen the double-apply
        # window — reject it rather than silently wiping the table.
        if retention_hours < 0:
            raise ValueError("retention_hours cannot be negative")

        threshold = self._dao.domain.clock.now() - timedelta(hours=retention_hours)
        return self._delete_in_batches(Q(processed_at__lt=threshold), batch_size)


def resolve_dispatch_context(
    instance: Any, handler_fn: Any, event: Any
) -> tuple[Any, str, str] | None:
    """Resolve consume-side idempotency for a handler invocation, or ``None``.

    Returns ``(repo, message_id, handler_id)`` when the handler opts in
    (``idempotent=True`` projector) AND the event carries a stable id AND the
    projection's provider has a marker repository (a managed, DB-backed
    provider). Otherwise returns ``None`` and the handler runs without
    deduplication: cache-backed projections have no atomic marker and must be
    written as idempotent upserts. See ADR-0017.

    Kept here (rather than in the generic ``@handle`` wrapper) so the handler
    machinery stays free of projector/projection/provider knowledge.
    """
    meta = getattr(instance, "meta_", None)
    if not getattr(meta, "idempotent", False):
        return None

    metadata = getattr(event, "_metadata", None)
    message_id = getattr(getattr(metadata, "headers", None), "id", None)
    if not message_id:
        return None

    projection_cls = getattr(meta, "projector_for", None)
    provider_name = "default"
    if projection_cls is not None:
        provider_name = getattr(projection_cls.meta_, "provider", "default")

    try:
        repo = current_domain._get_processed_message_repo(provider_name)
    except KeyError:
        logger.debug(
            "Consume-side idempotency requested but provider '%s' has no marker "
            "store; %s runs without deduplication",
            provider_name,
            fqn(handler_fn),
        )
        return None

    return repo, message_id, fqn(handler_fn)


def extract_payload_message_id(message: dict[str, Any]) -> str | None:
    """Return the stripped ``metadata.headers.id`` of a broker payload, or ``None``.

    Protean embeds the source message id at ``metadata.headers.id`` when it
    publishes to a broker. Returns ``None`` when the payload has no such key or
    the value is not a non-blank string (e.g. a raw external message).
    """
    try:
        value = message["metadata"]["headers"]["id"]
    except (KeyError, TypeError):
        return None

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def dispatch_to_subscriber(subscriber_cls: Any, message: dict[str, Any]) -> None:
    """Deliver ``message`` to a new instance of ``subscriber_cls``.

    A subscriber without ``idempotent=True`` is called directly. An idempotent
    subscriber runs inside a ``UnitOfWork`` that also checks and writes its
    marker in ``meta_.provider``, keyed on the payload's ``metadata.headers.id``
    and the subscriber's fully-qualified name; a message already marked is
    skipped. Exceptions from the subscriber propagate, and leave no marker.

    Raises:
        InsufficientDataError: The subscriber is idempotent and the payload has
            no non-blank string ``metadata.headers.id``, or that id is longer
            than ``MESSAGE_ID_MAX_LENGTH`` characters. The subscriber does not
            run.
    """
    if not getattr(subscriber_cls.meta_, "idempotent", False):
        subscriber_cls()(message)
        return

    handler_id = fqn(subscriber_cls)
    message_id = _subscriber_message_id(handler_id, message)
    repo = cast(
        ProcessedMessageRepository,
        current_domain._get_processed_message_repo(subscriber_cls.meta_.provider),
    )
    with UnitOfWork():
        if repo.is_processed(message_id, handler_id):
            return  # redelivery — already applied, skip
        subscriber_cls()(message)
        repo.mark(message_id, handler_id)


def _subscriber_message_id(handler_id: str, message: dict[str, Any]) -> str:
    """Return the payload id an idempotent subscriber dedupes on.

    Raises:
        InsufficientDataError: The id is missing, blank, not a string, or too
            long for the marker column. The error is also logged.
    """
    # The broker-assigned delivery id is not a fallback key: a redelivery can
    # carry a new one, so it would not deduplicate.
    message_id = extract_payload_message_id(message)
    if message_id is None:
        error = (
            f"Idempotent subscriber `{handler_id}` received a payload with no "
            "non-blank string `metadata.headers.id`; it needs that id to "
            "deduplicate the message"
        )
    elif len(message_id) > MESSAGE_ID_MAX_LENGTH:
        # Rejected before the call: the marker write would fail only after the
        # subscriber ran, and every redelivery would repeat that.
        error = (
            f"Idempotent subscriber `{handler_id}` received a payload whose "
            f"`metadata.headers.id` is longer than {MESSAGE_ID_MAX_LENGTH} "
            "characters; the marker cannot store it"
        )
    else:
        return message_id

    logger.error(error)
    raise InsufficientDataError(error)


def cleanup_processed_messages(
    domain: Any,
    retention_hours: int | None = None,
    batch_size: int | None = None,
) -> int:
    """Prune consume-side idempotency markers older than the retention window.

    Deletes markers older than ``retention_hours`` across every managed provider
    that has a marker table, in bounded batches, and returns the total deleted.
    Defaults come from ``[consume_idempotency.cleanup]`` (7 days / 5000 rows).
    Intended to be run periodically (e.g. ``protean idempotency cleanup`` from a
    cron job). A no-op when no projector or subscriber opts into idempotency.
    """
    if not getattr(domain, "has_idempotent_consumers", False):
        return 0

    cleanup_config = domain.config.get("consume_idempotency", {}).get("cleanup", {})
    hours = (
        retention_hours
        if retention_hours is not None
        else cleanup_config.get("retention_hours", 168)
    )
    size = (
        batch_size if batch_size is not None else cleanup_config.get("batch_size", 5000)
    )

    with domain.domain_context():
        return sum(
            repo.cleanup_old_markers(hours, batch_size=size)
            for repo in domain._infrastructure.processed_message_repos.values()
        )
