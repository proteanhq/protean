"""SQLite coverage for the adapter DAO writing in the session it is given and
leaving the commit to the caller."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from protean.core.aggregate import BaseAggregate
from protean.fields import String
from protean.port.dao import HoldBack
from protean.utils.query import Q
from tests.shared import provider_adapter


class Label(BaseAggregate):
    name = String(max_length=50)


@pytest.fixture
def label_domain(test_domain):
    test_domain.register(Label)
    test_domain.init(traverse=False)
    test_domain.repository_for(Label)._dao  # materialize the model
    provider = provider_adapter(test_domain, "default")
    provider._metadata.create_all(provider._engine)
    # Start from a clean slate; the table is shared across tests in this module.
    test_domain.repository_for(Label)._dao.delete_all()
    yield test_domain


@pytest.mark.sqlite
class TestSqliteAdapterSession:
    def test_the_adapter_insert_leaves_the_commit_to_the_caller(self, label_domain):
        provider = provider_adapter(label_domain, "default")
        dao = label_domain.repository_for(Label)._dao
        model = dao.database_model_cls.from_entity(Label(name="Draft"))

        session = provider.new_session()
        try:
            dao._adapter.insert(session, model)
            provider.rollback(session)
        finally:
            session.close()

        assert dao.query.all().items == []

    def test_the_rows_an_adapter_insert_wrote_persist_after_commit(self, label_domain):
        provider = provider_adapter(label_domain, "default")
        dao = label_domain.repository_for(Label)._dao
        model = dao.database_model_cls.from_entity(Label(name="Final"))

        session = provider.new_session()
        try:
            dao._adapter.insert(session, model)
            provider.commit(session)
        finally:
            session.close()

        assert [label.name for label in dao.query.all().items] == ["Final"]

    def test_a_new_session_on_a_fresh_connection_matches_case_sensitively(
        self, label_domain, monkeypatch
    ):
        # ``NullPool`` opens a new connection for every session, so no earlier
        # session's ``PRAGMA`` carries over to this one.
        provider = provider_adapter(label_domain, "default")
        engine = create_engine("sqlite://", poolclass=NullPool)
        monkeypatch.setattr(provider, "_session_factory", sessionmaker(bind=engine))

        session = provider.new_session()
        try:
            matched = session.execute(text("SELECT 'a' LIKE 'A'")).scalar()
        finally:
            session.close()
            engine.dispose()

        assert matched == 0


def _forbid_ending(session):
    """Make ``session`` fail the test if anything commits, rolls back or
    closes it."""

    def forbidden(name):
        def end(*args, **kwargs):
            raise AssertionError(f"an adapter DAO called {name} on its session")

        return end

    for name in ("commit", "rollback", "close"):
        setattr(session, name, forbidden(name))


@pytest.mark.sqlite
def test_every_storage_operation_leaves_the_session_open(label_domain):
    provider = provider_adapter(label_domain, "default")
    adapter = label_domain.repository_for(Label)._dao._adapter
    first = adapter.database_model_cls.from_entity(Label(name="a"))
    second = adapter.database_model_cls.from_entity(Label(name="b"))
    hold_back = HoldBack(
        group_by=("name",),
        applies=Q(name__isnull=False),
        holds=Q(name="held"),
        order=("name",),
        lane_of=lambda row: 0,
    )

    session = provider.new_session()
    _forbid_ending(session)
    try:
        adapter.insert(session, first)
        assert adapter.insert_if_absent(session, second) is True
        first.name = "a2"
        adapter.update(session, first)
        assert adapter.update_if_absent(session, first) is True
        assert adapter.update_all(session, Q(name="a2"), {"name": "a3"}) == 1
        assert adapter.count(session, Q()) == 2
        rows = adapter.filter(session, Q(), offset=0, limit=10, order_by=["name"])
        assert [row.name for row in rows.items] == ["a3", "b"]
        raw = adapter.raw(session, "SELECT * FROM label WHERE name = 'b'")
        assert [row.name for row in raw.items] == ["b"]
        candidates = adapter.claim_candidates(
            session, Q(), limit=10, offset=0, order_by=("name",), hold_back=hold_back
        )
        assert [row.name for row in candidates] == ["a3", "b"]
        adapter.delete(session, rows.items[0])
        assert adapter.delete_top(session, Q(name="b"), limit=1) == 1
        assert adapter.delete_all(session, Q()) == 0
    finally:
        Session.rollback(session)
        Session.close(session)

    assert label_domain.repository_for(Label)._dao.query.all().items == []
