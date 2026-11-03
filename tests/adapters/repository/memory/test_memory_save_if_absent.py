"""The in-memory ``save_if_absent`` inside a Unit of Work only stages its row.

When another writer commits a row with the same unique key before the Unit of
Work commits, the commit drops the staged row. These tests check that the
commit compares the key the staged row holds when the commit runs. The last
test checks that the portable ``BaseDAO`` default compares the key as a custom
database model stores it.
"""

import pytest

from protean.adapters.repository.memory import MemoryModel
from protean.core.aggregate import BaseAggregate
from protean.core.index import Index
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Auto, String
from protean.port.dao import BaseDAO


class KeyedRow(BaseAggregate):
    key: String(max_length=50)
    note: String(max_length=50)


class AutoKeyedRow(BaseAggregate):
    id: Auto(identifier=True, increment=True)
    key: String(max_length=50)
    note: String(max_length=50)


class UpperKeyedRow(BaseAggregate):
    key: String(max_length=50)


class UpperKeyedRowModel(MemoryModel):
    @classmethod
    def from_entity(cls, entity):
        record = cls._entity_to_dict(entity)
        record["key"] = record["key"].upper()
        return record


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(KeyedRow, indexes=[Index("key", unique=True)])
    test_domain.register(AutoKeyedRow, indexes=[Index("key", unique=True)])
    test_domain.register(UpperKeyedRow, indexes=[Index("key", unique=True)])
    test_domain.register_database_model(UpperKeyedRowModel, part_of=UpperKeyedRow)
    test_domain.init(traverse=False)


def _outside_dao(test_domain, cls):
    """A DAO of its own that writes outside the Unit of Work, so the flag does
    not stick to the repository's shared DAO."""
    repo = test_domain.repository_for(cls)
    dao = test_domain.providers["default"].get_dao(cls, repo._database_model)
    return dao.outside_uow()


def _notes_with_key(test_domain, cls, key):
    rows = test_domain.repository_for(cls).query.filter(key=key).all().items
    return sorted(r.note for r in rows)


def test_commit_drops_a_staged_row_whose_auto_identifier_was_assigned_on_save(
    test_domain,
):
    dao = test_domain.repository_for(AutoKeyedRow)._dao
    mine = AutoKeyedRow(key="k", note="mine")

    with UnitOfWork():
        assert dao.save_if_absent(mine) is mine
        assert mine.id is not None
        _outside_dao(test_domain, AutoKeyedRow).save(
            AutoKeyedRow(key="k", note="committed first")
        )

    assert _notes_with_key(test_domain, AutoKeyedRow, "k") == ["committed first"]


def test_commit_checks_the_key_the_staged_row_holds_after_a_later_save(test_domain):
    dao = test_domain.repository_for(KeyedRow)._dao
    mine = KeyedRow(key="a", note="mine")

    with UnitOfWork():
        assert dao.save_if_absent(mine) is mine
        mine.key = "b"
        dao.save(mine)
        _outside_dao(test_domain, KeyedRow).save(
            KeyedRow(key="b", note="committed first")
        )

    assert _notes_with_key(test_domain, KeyedRow, "a") == []
    assert _notes_with_key(test_domain, KeyedRow, "b") == ["committed first"]


def test_default_compares_the_key_the_database_model_stores(test_domain):
    dao = test_domain.repository_for(UpperKeyedRow)._dao
    dao.save(UpperKeyedRow(key="bolt"))

    assert BaseDAO.save_if_absent(dao, UpperKeyedRow(key="bolt")) is None
    assert dao.query.filter(key="BOLT").count() == 1
