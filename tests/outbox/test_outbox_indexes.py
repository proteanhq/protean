"""The Outbox aggregate declares the recommended indexes (issue #944)."""

import pytest
from sqlalchemy import inspect

from protean.domain import Domain
from protean.core.index import Index
from protean.utils.outbox import OUTBOX_INDEXES


class TestOutboxIndexDeclarations:
    def test_declares_three_recommended_indexes(self):
        assert len(OUTBOX_INDEXES) == 3
        by_name = {(ix.name or "_".join(ix.fields)): ix for ix in OUTBOX_INDEXES}
        assert "ix_outbox_active" in by_name
        # (message_id, target_broker) composite unique, correlation_id plain.
        # Uniqueness is composite because a single event is dual-written once per
        # target broker (internal + every external broker), so message_id is not
        # unique on its own across those per-broker rows. The framework always
        # writes a non-NULL target_broker, so the composite still enforces one row
        # per (message_id, broker). See issue #1009 (dual-write regression).
        assert any(
            ix.unique and ix.fields == ("message_id", "target_broker")
            for ix in OUTBOX_INDEXES
        )
        assert any(ix.fields == ("correlation_id",) for ix in OUTBOX_INDEXES)

    def test_active_index_is_partial_on_status_and_priority(self):
        active = next(ix for ix in OUTBOX_INDEXES if ix.name == "ix_outbox_active")
        assert active.fields == ("status", "priority")
        assert active.desc == ("priority",)
        assert active.where is not None

    def test_all_entries_are_index_instances(self):
        assert all(isinstance(ix, Index) for ix in OUTBOX_INDEXES)


@pytest.mark.sqlite
@pytest.mark.no_test_domain
class TestOutboxIndexCreation:
    def test_outbox_table_has_recommended_indexes(self):
        domain = Domain(name="OutboxIndexes")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": "sqlite:///:memory:",
        }
        domain.config["enable_outbox"] = True
        domain.config["server"] = {"default_subscription_type": "stream"}
        domain.init(traverse=False)

        with domain.domain_context():
            repo = domain._get_outbox_repo("default")
            repo._dao  # ensure table registered
            provider = domain.providers["default"]
            provider._metadata.create_all(provider._engine)

            insp = inspect(provider._engine)
            names = {i["name"] for i in insp.get_indexes("outbox")}
            assert {
                "ix_outbox_active",
                "ix_outbox_correlation_id",
                "uq_outbox_message_id_target_broker",
            } <= names


@pytest.mark.sqlite
@pytest.mark.no_test_domain
class TestOutboxDualWriteUniqueness:
    """The composite unique index must permit the framework's own dual-write:
    one outbox row per target broker for a single event, all sharing one
    ``message_id`` and distinguished only by ``target_broker`` (issue #1009)."""

    def _sample_metadata(self):
        from datetime import datetime, timezone

        from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata

        return Metadata(
            headers=MessageHeaders(
                id="identity::customer-abc-0.1",
                type="CustomerRegistered",
                stream="identity::customer-abc",
                time=datetime.now(timezone.utc),
            ),
            domain=DomainMeta(
                fqn="identity.CustomerRegistered",
                kind="event",
                origin_stream="identity::customer-abc",
                version="1.0",
                sequence_id="1",
            ),
        )

    def test_same_message_id_persists_once_per_target_broker(self, tmp_path):
        from protean.utils.outbox import Outbox

        # A file-backed SQLite DB so the table survives across sessions/connections
        # (an in-memory ``:memory:`` DB is per-connection and would vanish).
        db_path = tmp_path / "dual_write.db"
        domain = Domain(name="OutboxDualWrite")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": f"sqlite:///{db_path}",
        }
        domain.config["enable_outbox"] = True
        domain.config["server"] = {"default_subscription_type": "stream"}
        domain.init(traverse=False)

        with domain.domain_context():
            repo = domain._get_outbox_repo("default")
            repo._dao  # ensure the outbox table is registered before create_all
            provider = domain.providers["default"]
            provider._metadata.create_all(provider._engine)

            metadata = self._sample_metadata()
            shared_message_id = metadata.headers.id

            # Same event, dual-written to the internal broker and one external bus.
            for broker in ("default", "global"):
                repo.add(
                    Outbox.create_message(
                        message_id=shared_message_id,
                        stream_name="identity::customer-abc",
                        message_type="CustomerRegistered",
                        data={"customer_id": "abc"},
                        metadata=metadata,
                        target_broker=broker,
                    )
                )

            # Both rows must persist — no UniqueViolation on the shared message_id.
            rows = repo._dao.query.filter(message_id=shared_message_id).all().items
            assert len(rows) == 2
            assert {r.target_broker for r in rows} == {"default", "global"}

    def test_same_message_id_same_broker_is_rejected(self, tmp_path):
        """Idempotency holds within a broker: two rows sharing both
        ``message_id`` and ``target_broker`` violate the composite unique index.
        This is the guarantee a non-NULL ``target_broker`` restores for
        single-broker mode, where rows would otherwise carry NULL and escape
        uniqueness (issue #1009)."""
        from sqlalchemy.exc import IntegrityError

        from protean.core.unit_of_work import UnitOfWork
        from protean.exceptions import TransactionError, ValidationError
        from protean.utils.outbox import Outbox

        db_path = tmp_path / "idempotency.db"
        domain = Domain(name="OutboxIdempotency")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": f"sqlite:///{db_path}",
        }
        domain.config["enable_outbox"] = True
        domain.config["server"] = {"default_subscription_type": "stream"}
        domain.init(traverse=False)

        with domain.domain_context():
            repo = domain._get_outbox_repo("default")
            repo._dao  # ensure the outbox table is registered before create_all
            provider = domain.providers["default"]
            provider._metadata.create_all(provider._engine)

            metadata = self._sample_metadata()

            def _row():
                return Outbox.create_message(
                    message_id=metadata.headers.id,
                    stream_name="identity::customer-abc",
                    message_type="CustomerRegistered",
                    data={"customer_id": "abc"},
                    metadata=metadata,
                    target_broker="default",
                )

            # repo.add enrolls the row in a UnitOfWork that persists on commit,
            # so wrap each add in its own UoW to control when the INSERT (and the
            # unique-constraint check) happens.
            with UnitOfWork():
                repo.add(_row())

            # Same (message_id, target_broker) a second time must be rejected.
            # The UnitOfWork wraps the DB UNIQUE violation as a TransactionError.
            with pytest.raises((TransactionError, IntegrityError, ValidationError)):
                with UnitOfWork():
                    repo.add(_row())
