"""Consume-side idempotency — a processed-message marker for exactly-once projectors.

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

See ADR-0017.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.index import Index
from protean.core.repository import BaseRepository
from protean.fields import Auto
from protean.utils import fqn
from protean.utils.globals import current_domain

logger = logging.getLogger(__name__)


class ProcessedMessage(BaseAggregate):
    """A marker recording that a handler has processed a message.

    ``handler`` is the fully-qualified handler-method identity (``module.Class.method``)
    so that distinct projectors/methods each dedupe the same message independently.
    """

    id = Auto(identifier=True)

    # ``message_id`` is a composite Protean message id (headers.id), e.g.
    # ``testdomain::order-<aggregate-id>-3``, not a bare UUID — so it needs the
    # same 255 ceiling as the outbox table for the (message_id, handler) index.
    message_id: Annotated[str, Field(max_length=255)]
    handler: Annotated[str, Field(max_length=255)]
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
            .all(with_total=False)
            .items
        )
        return len(rows) > 0

    def mark(self, message_id: str, handler: str) -> None:
        """Record that ``handler`` has processed ``message_id`` (in the active UoW)."""
        self._dao.save(ProcessedMessage(message_id=message_id, handler=handler))


def resolve_dispatch_context(instance: Any, handler_fn: Any, event: Any):
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
