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
        # message_id unique, correlation_id plain
        assert any(ix.unique and ix.fields == ("message_id",) for ix in OUTBOX_INDEXES)
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
                "uq_outbox_message_id",
            } <= names
