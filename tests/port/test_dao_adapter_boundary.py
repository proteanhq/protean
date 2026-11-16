"""The adapter DAOs read and write in the session they are given.

They never look up the Unit of Work and never commit: the ``DAO`` service
picks the session and ends it. The providers and the memory session still
read the Unit of Work, which the scan below confirms it can see.
"""

import ast
import inspect
import textwrap

import pytest

from protean.adapters.repository.elasticsearch import ElasticsearchDAO, ESProvider
from protean.adapters.repository.memory import DictDAO, MemoryProvider, MemorySession
from protean.adapters.repository.sqlalchemy import (
    SADAO,
    MssqlProvider,
    MysqlProvider,
    PostgresqlProvider,
    SAProvider,
    SqliteProvider,
)
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.port.provider import DatabaseCapabilities
from protean.utils.query import Q


def _names_used(cls: type) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


class TestNoUnitOfWorkLookup:
    @pytest.mark.parametrize("adapter_cls", [DictDAO, SADAO, ElasticsearchDAO])
    def test_an_adapter_dao_never_reads_the_unit_of_work(self, adapter_cls):
        assert "current_uow" not in _names_used(adapter_cls)

    @pytest.mark.parametrize("cls", [MemorySession, MemoryProvider, SAProvider])
    def test_the_scan_sees_a_class_that_reads_the_unit_of_work(self, cls):
        assert "current_uow" in _names_used(cls)


class TestInsertIfAbsentDeclared:
    @pytest.mark.parametrize(
        "provider_cls",
        [
            MemoryProvider,
            PostgresqlProvider,
            SqliteProvider,
            MssqlProvider,
            MysqlProvider,
        ],
    )
    def test_declared_by_each_transactional_provider(self, provider_cls):
        # ``capabilities`` reads no instance state.
        provider = object.__new__(provider_cls)

        assert DatabaseCapabilities.INSERT_IF_ABSENT in provider.capabilities

    def test_not_declared_by_elasticsearch(self):
        provider = object.__new__(ESProvider)

        assert DatabaseCapabilities.INSERT_IF_ABSENT not in provider.capabilities


class Note(BaseAggregate):
    title = String(max_length=50)
    rank = Integer(default=0)


class CommitForbiddenSession(MemorySession):
    """A memory session that fails the test if anything commits it."""

    def commit(self):
        raise AssertionError("an adapter DAO committed its session")


@pytest.fixture
def adapter(test_domain):
    test_domain.register(Note)
    test_domain.init(traverse=False)
    return test_domain.repository_for(Note)._dao._adapter


class TestMemoryAdapterNeverCommits:
    def test_every_storage_operation_leaves_the_session_open(self, adapter):
        session = CommitForbiddenSession(adapter.provider, new_connection=True)
        model = adapter.database_model_cls.from_entity(Note(title="a", rank=1))

        adapter.insert(session, model)
        model["rank"] = 2
        adapter.update(session, model)
        assert adapter.update_all(session, Q(title="a"), {"rank": 3}) == 1
        assert adapter.count(session, Q(title="a")) == 1
        rows = adapter.filter(session, Q(title="a"), offset=0, limit=10).items
        assert [row["rank"] for row in rows] == [3]
        adapter.delete(session, rows[0])
        assert adapter.delete_all(session, Q()) == 0

    def test_writes_stay_in_the_session_until_the_provider_commits(self, adapter):
        session = adapter.provider.new_session()
        model = adapter.database_model_cls.from_entity(Note(title="b"))

        adapter.insert(session, model)

        assert adapter.count(adapter.provider.new_session(), Q()) == 0
        adapter.provider.commit(session)
        assert adapter.count(adapter.provider.new_session(), Q()) == 1
