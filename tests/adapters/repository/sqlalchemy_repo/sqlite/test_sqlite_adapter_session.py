"""SQLite coverage for the adapter DAO writing in the session it is given and
leaving the commit to the caller."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import String
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
