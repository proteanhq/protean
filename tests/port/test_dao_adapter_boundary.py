"""The adapter DAOs read and write in the session they are given.

They never look up the Unit of Work and never commit: the ``DAO`` service
picks the session and ends it. The providers and the memory session still
read the Unit of Work, which the scan below confirms it can see.
"""

import ast
import importlib.util
import inspect
import sys

import pytest

from protean.adapters.database.elasticsearch import ElasticsearchDAO, ESDatabase
from protean.adapters.database.memory import DictDAO, MemoryDatabase, MemorySession
from protean.adapters.database.sqlalchemy import (
    SADAO,
    MssqlDatabase,
    MysqlDatabase,
    PostgresqlDatabase,
    SADatabase,
    SqliteDatabase,
)
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.port.database import DatabaseCapabilities
from protean.utils.query import Q


def _top_level(tree: ast.Module, kind: type, name: str) -> ast.AST | None:
    return next((n for n in tree.body if isinstance(n, kind) and n.name == name), None)


def _uow_names(tree: ast.Module) -> set[str]:
    """``current_uow`` and every name the module imports it under."""
    return {"current_uow"} | {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name == "current_uow" and alias.asname
    }


def _names_the_unit_of_work(node: ast.AST, names: set[str]) -> bool:
    """Whether ``node`` is ``current_uow`` under one of ``names`` or as a
    module attribute."""
    if isinstance(node, ast.Attribute):
        return node.attr == "current_uow"
    return isinstance(node, ast.Name) and node.id in names


def _class_reads_the_unit_of_work(tree: ast.Module, class_name: str) -> bool:
    """Whether the class, or a module-level function it calls, names
    ``current_uow`` under one of its names or as a module attribute."""
    names = _uow_names(tree)
    class_node = _top_level(tree, ast.ClassDef, class_name)
    assert class_node is not None, class_name
    to_scan, scanned = [class_node], set()
    while to_scan:
        for node in ast.walk(to_scan.pop()):
            if _names_the_unit_of_work(node, names):
                return True
            if not isinstance(node, ast.Name) or node.id in scanned:
                continue
            helper = _top_level(tree, ast.FunctionDef, node.id)
            if helper is not None:
                scanned.add(node.id)
                to_scan.append(helper)
    return False


def _reads_the_unit_of_work(cls: type) -> bool:
    """Whether ``cls``, a Protean base class in its MRO, or a module-level
    function one of them calls names ``current_uow``, under its own name, an
    import alias, or as an attribute of a module."""
    return any(
        _class_reads_the_unit_of_work(
            ast.parse(inspect.getsource(sys.modules[klass.__module__])),
            klass.__name__,
        )
        for klass in cls.__mro__
        if klass.__module__.startswith(("protean", "tests"))
    )


PLANTED_READS = {
    "aliased_import": """
from protean.utils.globals import current_uow as uow

class Planted:
    def run(self):
        return uow.in_progress
""",
    "module_attribute": """
from protean.utils import globals as g

class Planted:
    def run(self):
        return g.current_uow
""",
    "module_helper": """
from protean.utils.globals import current_uow

def _in_uow():
    return bool(current_uow)

class Planted:
    def run(self):
        return _in_uow()
""",
    "mixin_base": """
from protean.utils.globals import current_uow

class Mixin:
    def in_uow(self):
        return bool(current_uow)

class Planted(Mixin):
    pass
""",
}


@pytest.fixture
def planted(tmp_path, request):
    name = f"tests.planted_uow_read_{request.param}"
    path = tmp_path / f"{request.param}.py"
    path.write_text(PLANTED_READS[request.param])
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module.Planted
    finally:
        del sys.modules[name]


class TestNoUnitOfWorkLookup:
    @pytest.mark.parametrize("adapter_cls", [DictDAO, SADAO, ElasticsearchDAO])
    def test_an_adapter_dao_never_reads_the_unit_of_work(self, adapter_cls):
        assert not _reads_the_unit_of_work(adapter_cls)

    @pytest.mark.parametrize("cls", [MemorySession, MemoryDatabase, SADatabase])
    def test_the_scan_sees_a_class_that_reads_the_unit_of_work(self, cls):
        assert _reads_the_unit_of_work(cls)

    @pytest.mark.parametrize("planted", sorted(PLANTED_READS), indirect=True)
    def test_the_scan_sees_an_indirect_read(self, planted):
        assert _reads_the_unit_of_work(planted)


class TestInsertIfAbsentDeclared:
    @pytest.mark.parametrize(
        "provider_cls",
        [
            MemoryDatabase,
            PostgresqlDatabase,
            SqliteDatabase,
            MssqlDatabase,
            MysqlDatabase,
        ],
    )
    def test_declared_by_each_transactional_provider(self, provider_cls):
        # ``capabilities`` reads no instance state.
        provider = object.__new__(provider_cls)

        assert DatabaseCapabilities.INSERT_IF_ABSENT in provider.capabilities

    def test_not_declared_by_elasticsearch(self):
        provider = object.__new__(ESDatabase)

        assert DatabaseCapabilities.INSERT_IF_ABSENT not in provider.capabilities


class Note(BaseAggregate):
    title = String(max_length=50)
    rank = Integer(default=0)


class EndForbiddenSession(MemorySession):
    """A memory session that fails the test if anything ends it or publishes
    its writes."""

    def commit(self):
        raise AssertionError("an adapter DAO committed its session")

    def _merge_into_live_store(self):
        raise AssertionError("an adapter DAO published its session's writes")

    def rollback(self):
        raise AssertionError("an adapter DAO rolled back its session")

    def close(self):
        raise AssertionError("an adapter DAO closed its session")


@pytest.fixture
def adapter(test_domain):
    test_domain.register(Note)
    test_domain.init(traverse=False)
    return test_domain.repository_for(Note)._dao._adapter


class TestMemoryAdapterNeverCommits:
    def test_every_storage_operation_leaves_the_session_open(self, adapter):
        session = EndForbiddenSession(adapter.provider, new_connection=True)
        model = adapter.database_model_cls.from_entity(Note(title="a", rank=1))
        other = adapter.database_model_cls.from_entity(Note(title="b", rank=1))

        adapter.insert(session, model)
        assert adapter.insert_if_absent(session, other) is True
        model["rank"] = 2
        adapter.update(session, model)
        assert adapter.update_if_absent(session, model) is True
        assert adapter.update_all(session, Q(title="a"), {"rank": 3}) == 1
        assert adapter.count(session, Q(title="a")) == 1
        rows = adapter.filter(session, Q(title="a"), offset=0, limit=10).items
        assert [row["rank"] for row in rows] == [3]
        # ``raw`` reads the committed store, which holds none of these rows.
        assert adapter.raw(session, '{"title": "a"}').total == 0
        adapter.delete(session, rows[0])
        assert adapter.delete_top(session, Q(title="b"), limit=1) == 1
        assert adapter.delete_all(session, Q()) == 0

    def test_writes_stay_in_the_session_until_the_provider_commits(self, adapter):
        session = adapter.provider.new_session()
        model = adapter.database_model_cls.from_entity(Note(title="b"))

        adapter.insert(session, model)

        assert adapter.count(adapter.provider.new_session(), Q()) == 0
        adapter.provider.commit(session)
        assert adapter.count(adapter.provider.new_session(), Q()) == 1
