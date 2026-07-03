"""Consume-side idempotency for projectors (issue #1042, ADR-0017).

Event delivery is at-least-once. A non-idempotent accumulating projector
(``total_reviews += 1``) double-applies a redelivered event. An
``idempotent=True`` projector records a (message_id, handler) marker in the same
UnitOfWork as its read-model write, so a redelivery is skipped.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.exceptions import ConfigurationError, ObjectNotFoundError
from protean.fields import Identifier, Integer, String
from protean.utils import fqn
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageEnvelope,
    MessageHeaders,
    Metadata,
)
from protean.utils.globals import current_domain


class Product(BaseAggregate):
    name = String()


class ReviewApproved(BaseEvent):
    product_id = Identifier()


class ProductStats(BaseProjection):
    product_id = Identifier(identifier=True)
    total_reviews = Integer(default=0)


class RatingProjector(BaseProjector):
    """Deliberately non-idempotent (accumulating) — the issue's anti-pattern."""

    @on(ReviewApproved)
    def on_review_approved(self, event: ReviewApproved) -> None:
        repo = current_domain.repository_for(ProductStats)
        try:
            stats = repo.get(event.product_id)
        except ObjectNotFoundError:
            stats = ProductStats(product_id=event.product_id, total_reviews=0)
        stats.total_reviews += 1
        repo.add(stats)


def _review_message(product_id: str, seq: int = 0) -> Message:
    """A concrete event Message with a stable headers.id (survives redelivery).

    ``seq`` distinguishes genuinely different events for the same product.
    """
    event = ReviewApproved(product_id=product_id)
    headers = MessageHeaders(
        id=f"test::product-{product_id}-{seq}",
        type=ReviewApproved.__type__,
        stream=f"test::product-{product_id}",
    )
    metadata = Metadata(
        headers=headers,
        envelope=MessageEnvelope.build(event.payload),
        domain=DomainMeta(
            fqn="tests.projector.test_consume_idempotency.ReviewApproved",
            kind="EVENT",
            stream_category="test::product",
            version=1,
        ),
    )
    return Message(data=event.payload, metadata=metadata)


def _create_tables(test_domain):
    """Create tables after in-test registration.

    The ``db`` fixture creates artifacts at setup, before these tests register
    their elements, so the read-model and marker tables must be (re)created here.
    Goes through the real ``setup_database`` path (which forces the marker DAO).
    """
    test_domain.setup_database()


def _register(test_domain, *, idempotent: bool):
    test_domain.register(Product)
    test_domain.register(ReviewApproved, part_of=Product)
    test_domain.register(ProductStats)
    test_domain.register(
        RatingProjector,
        projector_for=ProductStats,
        aggregates=[Product],
        idempotent=idempotent,
    )
    test_domain.init(traverse=False)


class TestConsumeIdempotency:
    def test_redelivery_double_applies_without_idempotency(self, test_domain):
        """Baseline / reproduction: the same event delivered twice double-counts."""
        _register(test_domain, idempotent=False)
        product_id = str(uuid4())
        message = _review_message(product_id)

        RatingProjector._handle(message)
        RatingProjector._handle(message)  # redelivery

        stats = current_domain.repository_for(ProductStats).get(product_id)
        assert stats.total_reviews == 2  # corrupted by the double-apply

    def test_idempotent_projector_applies_once_on_redelivery(self, test_domain):
        """The fix: with idempotent=True the redelivery is skipped."""
        _register(test_domain, idempotent=True)
        product_id = str(uuid4())
        message = _review_message(product_id)

        RatingProjector._handle(message)
        RatingProjector._handle(message)  # redelivery — must be a no-op

        stats = current_domain.repository_for(ProductStats).get(product_id)
        assert stats.total_reviews == 1

    def test_distinct_messages_are_each_applied(self, test_domain):
        """Idempotency dedupes only redeliveries — distinct events still apply."""
        _register(test_domain, idempotent=True)
        product_id = str(uuid4())

        RatingProjector._handle(_review_message(product_id, seq=0))
        # A different message id for the same product → a genuine second review.
        RatingProjector._handle(_review_message(product_id, seq=1))

        stats = current_domain.repository_for(ProductStats).get(product_id)
        assert stats.total_reviews == 2

    def test_marker_recorded_with_message_and_handler_key(self, test_domain):
        """The marker is keyed by (message_id, fully-qualified handler method)."""
        _register(test_domain, idempotent=True)
        product_id = str(uuid4())
        RatingProjector._handle(_review_message(product_id))

        repo = current_domain._get_processed_message_repo("default")
        handler_id = fqn(RatingProjector.on_review_approved)
        assert repo.is_processed(f"test::product-{product_id}-0", handler_id)
        # A different handler has NOT processed it — dedup is per-handler.
        assert not repo.is_processed(f"test::product-{product_id}-0", "other.Handler")

    def test_idempotency_is_off_by_default(self, test_domain):
        """Without idempotent=True no marker store is created for the domain."""
        _register(test_domain, idempotent=False)
        assert current_domain.has_idempotent_consumers is False

    def test_no_dedup_context_when_event_lacks_a_message_id(self, test_domain):
        """A handler runs without dedup if the event carries no message id."""
        from protean.utils.consume_idempotency import resolve_dispatch_context

        _register(test_domain, idempotent=True)
        projector = RatingProjector()
        # A plain object stands in for an event with no ``_metadata``.
        context = resolve_dispatch_context(
            projector, RatingProjector.on_review_approved, object()
        )
        assert context is None

    def test_degrades_gracefully_when_provider_has_no_marker_store(
        self, test_domain, monkeypatch
    ):
        """Cache-backed / unmanaged-provider projections have no atomic marker,
        so idempotency degrades to a no-op (documented boundary) rather than
        crashing: the redelivery is applied again."""
        from protean.domain import Domain

        _register(test_domain, idempotent=True)
        monkeypatch.setattr(
            Domain,
            "_get_processed_message_repo",
            lambda self, provider: (_ for _ in ()).throw(KeyError(provider)),
        )
        product_id = str(uuid4())
        message = _review_message(product_id)

        RatingProjector._handle(message)
        RatingProjector._handle(message)  # redelivery — NOT deduped

        stats = current_domain.repository_for(ProductStats).get(product_id)
        assert stats.total_reviews == 2

    def test_processed_message_repo_is_lazily_initialized(self, test_domain):
        """Accessing the marker repo initializes it on first use."""
        _register(test_domain, idempotent=True)
        test_domain._infrastructure.processed_message_repos.clear()
        assert test_domain._get_processed_message_repo("default") is not None

    def test_initialization_failure_is_wrapped_in_configuration_error(
        self, test_domain, monkeypatch
    ):
        """A failure synthesizing the per-provider marker surfaces clearly."""
        from protean.domain import infrastructure

        _register(test_domain, idempotent=False)  # providers exist, no marker yet

        def _boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(infrastructure, "clone_class", _boom)
        with pytest.raises(ConfigurationError, match="consume-side idempotency"):
            test_domain._infrastructure.initialize_processed_messages()


class FlakyProjector(BaseProjector):
    """Writes the read model, then crashes before commit on its first delivery."""

    _failed = {"done": False}

    @on(ReviewApproved)
    def on_review_approved(self, event: ReviewApproved) -> None:
        repo = current_domain.repository_for(ProductStats)
        try:
            stats = repo.get(event.product_id)
        except ObjectNotFoundError:
            stats = ProductStats(product_id=event.product_id, total_reviews=0)
        stats.total_reviews += 1
        repo.add(stats)
        if not FlakyProjector._failed["done"]:
            FlakyProjector._failed["done"] = True
            raise RuntimeError("crash after write, before commit")


@pytest.mark.database
class TestConsumeIdempotencyRelational:
    """The atomic guarantee is only real on a transactional provider."""

    @pytest.fixture(autouse=True)
    def reset(self):
        FlakyProjector._failed["done"] = False

    def test_dedup_on_a_relational_provider(self, test_domain):
        _register(test_domain, idempotent=True)
        _create_tables(test_domain)
        product_id = str(uuid4())
        message = _review_message(product_id)

        RatingProjector._handle(message)
        RatingProjector._handle(message)

        stats = current_domain.repository_for(ProductStats).get(product_id)
        assert stats.total_reviews == 1

    @pytest.mark.sqlite
    def test_duplicate_marker_is_rejected_by_unique_index(self, test_domain):
        """The composite (message_id, handler) unique index is the concurrency
        guarantee: a second marker for the same pair is rejected. This holds
        only on a provider that materializes the index (relational, not memory)."""
        from protean.core.unit_of_work import UnitOfWork

        # ``--sqlite`` only signals the flag is available; the active provider is
        # set by ``--db``. Skip when it is the in-memory provider, which does not
        # enforce unique indexes (so the duplicate insert would not be rejected).
        if type(test_domain.providers["default"]).__name__ == "MemoryProvider":
            pytest.skip("unique index is enforced only by relational providers")

        _register(test_domain, idempotent=True)
        _create_tables(test_domain)
        repo = current_domain._get_processed_message_repo("default")

        with UnitOfWork():
            repo.mark("msg-1", "handler-A")

        with pytest.raises(Exception):
            with UnitOfWork():
                repo.mark("msg-1", "handler-A")  # duplicate pair → index rejects

        # A different pair still inserts.
        with UnitOfWork():
            repo.mark("msg-1", "handler-B")
        assert repo.is_processed("msg-1", "handler-B")

    def test_failed_delivery_rolls_back_marker_and_read_model(self, test_domain):
        """A crash after the read-model write rolls back BOTH the write and the
        marker (same transaction), so the redelivery reprocesses cleanly and the
        count is 1, not 0 (marker leaked) or 2 (write leaked)."""
        test_domain.register(Product)
        test_domain.register(ReviewApproved, part_of=Product)
        test_domain.register(ProductStats)
        test_domain.register(
            FlakyProjector,
            projector_for=ProductStats,
            aggregates=[Product],
            idempotent=True,
        )
        test_domain.init(traverse=False)
        _create_tables(test_domain)

        product_id = str(uuid4())
        message = _review_message(product_id)
        message_id = f"test::product-{product_id}-0"
        handler_id = fqn(FlakyProjector.on_review_approved)
        repo = current_domain._get_processed_message_repo("default")

        with pytest.raises(Exception):
            FlakyProjector._handle(message)  # crashes → rolls back
        # The failed delivery left NO marker: it rolled back with the write.
        assert not repo.is_processed(message_id, handler_id)

        FlakyProjector._handle(message)  # redelivery reprocesses cleanly
        # Now the marker IS written (proves it is only committed on success).
        assert repo.is_processed(message_id, handler_id)

        stats = current_domain.repository_for(ProductStats).get(product_id)
        assert stats.total_reviews == 1
