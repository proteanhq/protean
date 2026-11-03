"""Generic conformance tests for ``BaseDAO.save_if_absent`` across providers.

``save_if_absent`` writes a row unless another row holds its unique key: the
values of the fields of each non-partial ``Index(unique=True)``. The outbox
relies on it so that a reconcile sweep and a live unit of work can both try to
write the same row, and the second writer skips its copy instead of failing.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from protean.core.aggregate import BaseAggregate
from protean.core.index import Index
from protean.core.unit_of_work import UnitOfWork
from protean.fields import String
from protean.port.dao import BaseDAO
from protean.utils.globals import current_uow
from protean.utils.query import Q

_KEYED_INDEXES = [Index("key_a", "key_b", unique=True)]


class KeyedRow(BaseAggregate):
    key_a: String(max_length=50)
    key_b: String(max_length=50)
    note: String(max_length=50)


class UnkeyedRow(BaseAggregate):
    key_a: String(max_length=50)
    note: String(max_length=50)


class RawKeyedRow(BaseAggregate):
    token: String(max_length=50)


def _raw_unique_token_indexes():
    # A unique index the framework does not know about: only the database
    # enforces it, so a duplicate reaches the database as an IntegrityError
    # that no declared unique key explains.
    ddl = "CREATE UNIQUE INDEX ix_raw_keyed_token ON generic_raw_keyed_row (token)"
    return [
        Index.from_sql(dialect, ddl)
        for dialect in ("postgresql", "sqlite", "mysql", "mariadb", "mssql")
    ]


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(
        KeyedRow, schema_name="generic_keyed_row", indexes=_KEYED_INDEXES
    )
    test_domain.register(UnkeyedRow, schema_name="generic_unkeyed_row")
    test_domain.register(
        RawKeyedRow,
        schema_name="generic_raw_keyed_row",
        indexes=_raw_unique_token_indexes(),
    )
    test_domain.init(traverse=False)


def _dao(test_domain, cls=KeyedRow):
    return test_domain.repository_for(cls)._dao


def _rows_with_key(test_domain, key_a, key_b):
    return (
        test_domain.repository_for(KeyedRow)
        .query.filter(Q(key_a=key_a) & Q(key_b=key_b))
        .all()
        .items
    )


@pytest.mark.basic_storage
class TestSaveIfAbsent:
    def test_writes_a_row_whose_key_is_free(self, test_domain):
        row = KeyedRow(key_a="m1", key_b="internal", note="first")

        saved = _dao(test_domain).save_if_absent(row)

        assert saved is row
        stored = test_domain.repository_for(KeyedRow).get(row.id)
        assert stored.note == "first"

    def test_skips_a_row_whose_key_is_taken(self, test_domain):
        first = KeyedRow(key_a="m1", key_b="internal", note="first")
        _dao(test_domain).save(first)

        second = KeyedRow(key_a="m1", key_b="internal", note="second")
        assert second.id != first.id

        assert _dao(test_domain).save_if_absent(second) is None

        rows = _rows_with_key(test_domain, "m1", "internal")
        assert [r.id for r in rows] == [first.id]
        assert rows[0].note == "first"
        assert second.state_.is_new

    def test_writes_a_row_that_shares_only_part_of_the_key(self, test_domain):
        _dao(test_domain).save(KeyedRow(key_a="m1", key_b="internal"))

        other_broker = KeyedRow(key_a="m1", key_b="external")
        other_message = KeyedRow(key_a="m2", key_b="internal")

        assert _dao(test_domain).save_if_absent(other_broker) is other_broker
        assert _dao(test_domain).save_if_absent(other_message) is other_message
        assert len(_rows_with_key(test_domain, "m1", "external")) == 1
        assert len(_rows_with_key(test_domain, "m2", "internal")) == 1

    def test_a_none_key_value_never_collides(self, test_domain):
        provider = test_domain.providers["default"]
        if getattr(provider, "__database__", None) == "mssql":
            pytest.skip("SQL Server's unique index treats NULLs as equal")
        first = KeyedRow(key_a="m1", key_b=None)
        _dao(test_domain).save(first)

        second = KeyedRow(key_a="m1", key_b=None)

        assert _dao(test_domain).save_if_absent(second) is second
        stored = test_domain.repository_for(KeyedRow).query.filter(key_a="m1").all()
        assert sorted(r.id for r in stored.items) == sorted([first.id, second.id])

    def test_an_entity_without_a_unique_index_is_saved(self, test_domain):
        dao = _dao(test_domain, UnkeyedRow)
        dao.save(UnkeyedRow(key_a="m1"))

        second = UnkeyedRow(key_a="m1")

        assert dao.save_if_absent(second) is second
        assert len(dao.query.filter(key_a="m1").all().items) == 2

    def test_resaving_a_stored_row_does_not_collide_with_itself(self, test_domain):
        row = KeyedRow(key_a="m1", key_b="internal", note="first")
        _dao(test_domain).save(row)

        row.note = "changed"

        assert _dao(test_domain).save_if_absent(row) is row
        stored = test_domain.repository_for(KeyedRow).get(row.id)
        assert stored.note == "changed"


@pytest.mark.basic_storage
class TestBaseDAODefault:
    """The portable default that an adapter without its own override uses."""

    def test_default_skips_a_row_whose_key_is_taken(self, test_domain):
        dao = _dao(test_domain)
        first = KeyedRow(key_a="m1", key_b="internal", note="first")
        dao.save(first)

        second = KeyedRow(key_a="m1", key_b="internal", note="second")

        assert BaseDAO.save_if_absent(dao, second) is None
        rows = _rows_with_key(test_domain, "m1", "internal")
        assert [r.note for r in rows] == ["first"]

    def test_default_writes_a_row_whose_key_is_free(self, test_domain):
        dao = _dao(test_domain)
        row = KeyedRow(key_a="m1", key_b="internal")

        assert BaseDAO.save_if_absent(dao, row) is row
        assert len(_rows_with_key(test_domain, "m1", "internal")) == 1


@pytest.mark.transactional
class TestSaveIfAbsentInUnitOfWork:
    def test_skip_leaves_the_rest_of_the_unit_of_work_to_commit(self, test_domain):
        first = KeyedRow(key_a="m1", key_b="internal", note="first")
        _dao(test_domain).save(first)

        other = KeyedRow(key_a="m2", key_b="internal", note="other")
        duplicate = KeyedRow(key_a="m1", key_b="internal", note="duplicate")
        with UnitOfWork():
            _dao(test_domain).save(other)
            assert _dao(test_domain).save_if_absent(duplicate) is None
            assert current_uow._tracked_instance(KeyedRow, duplicate.id) is None

        rows = _rows_with_key(test_domain, "m1", "internal")
        assert [r.note for r in rows] == ["first"]
        assert test_domain.repository_for(KeyedRow).get(other.id).note == "other"

    def test_skips_a_row_another_writer_committed_during_the_unit_of_work(
        self, test_domain
    ):
        repo = test_domain.repository_for(KeyedRow)
        # A DAO of its own, so the flag that takes it outside the unit of work
        # does not stick to the repository's shared DAO.
        outside_dao = test_domain.providers["default"].get_dao(
            KeyedRow, repo._database_model
        )
        late = KeyedRow(key_a="m1", key_b="internal", note="committed first")
        mine = KeyedRow(key_a="m1", key_b="internal", note="mine")

        with UnitOfWork():
            # Open this unit of work's session before the other writer commits.
            assert repo.query.all().items == []
            outside_dao.outside_uow().save(late)

            assert _dao(test_domain).save_if_absent(mine) is None

        rows = _rows_with_key(test_domain, "m1", "internal")
        assert [r.note for r in rows] == ["committed first"]


@pytest.mark.atomic_transactions
class TestSaveIfAbsentAtomicity:
    def test_rollback_undoes_a_row_written_first_in_the_unit_of_work(self, test_domain):
        row = KeyedRow(key_a="m1", key_b="internal")

        with pytest.raises(ValueError), UnitOfWork():
            assert _dao(test_domain).save_if_absent(row) is row
            raise ValueError("Forced rollback")

        assert _rows_with_key(test_domain, "m1", "internal") == []

    def test_an_integrity_error_no_unique_key_explains_is_raised(self, test_domain):
        dao = _dao(test_domain, RawKeyedRow)
        dao.save(RawKeyedRow(token="t1"))

        with pytest.raises(IntegrityError), UnitOfWork():
            dao.save_if_absent(RawKeyedRow(token="t1"))

        assert len(dao.query.filter(token="t1").all().items) == 1

    def test_an_integrity_error_no_unique_key_explains_is_raised_standalone(
        self, test_domain
    ):
        dao = _dao(test_domain, RawKeyedRow)
        dao.save(RawKeyedRow(token="t1"))

        with pytest.raises(IntegrityError):
            dao.save_if_absent(RawKeyedRow(token="t1"))

        assert len(dao.query.filter(token="t1").all().items) == 1
