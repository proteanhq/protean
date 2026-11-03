"""Generic conformance tests for ``BaseDAO.save_if_absent`` across providers.

``save_if_absent`` writes a row unless another row holds its unique key: the
values of the fields of each non-partial ``Index(unique=True)``. The outbox
relies on it so that a reconcile sweep and a live unit of work can both try to
write the same row, and the second writer skips its copy instead of failing.
"""

import threading
import time

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


class RenamedKeyRow(BaseAggregate):
    email: String(max_length=50, referenced_as="email_address")


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
    test_domain.register(
        RenamedKeyRow,
        schema_name="generic_renamed_key_row",
        indexes=[Index("email", unique=True)],
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

    def test_a_key_field_stored_under_another_name_is_matched(self, test_domain):
        dao = _dao(test_domain, RenamedKeyRow)
        dao.save(RenamedKeyRow(email="a@example.com"))

        assert dao.save_if_absent(RenamedKeyRow(email="a@example.com")) is None
        assert BaseDAO.save_if_absent(dao, RenamedKeyRow(email="a@example.com")) is None

        # A count, because the Elasticsearch model cannot load a record whose
        # field is stored under another name.
        assert dao.query.filter(email="a@example.com").count() == 1


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

    def test_default_writes_a_row_with_a_none_key_value(self, test_domain):
        provider = test_domain.providers["default"]
        if getattr(provider, "__database__", None) == "mssql":
            pytest.skip("SQL Server's unique index treats NULLs as equal")
        dao = _dao(test_domain)
        first = KeyedRow(key_a="m1", key_b=None)
        dao.save(first)

        second = KeyedRow(key_a="m1", key_b=None)

        assert BaseDAO.save_if_absent(dao, second) is second
        stored = dao.query.filter(key_a="m1").all().items
        assert sorted(r.id for r in stored) == sorted([first.id, second.id])

    def test_default_resaves_a_stored_row(self, test_domain):
        dao = _dao(test_domain)
        row = KeyedRow(key_a="m1", key_b="internal", note="first")
        dao.save(row)

        row.note = "changed"

        assert BaseDAO.save_if_absent(dao, row) is row
        assert test_domain.repository_for(KeyedRow).get(row.id).note == "changed"


@pytest.mark.transactional
class TestSaveIfAbsentInUnitOfWork:
    def test_skip_leaves_the_rest_of_the_unit_of_work_to_commit(self, test_domain):
        first = KeyedRow(key_a="m1", key_b="internal", note="first")
        _dao(test_domain).save(first)

        other = KeyedRow(key_a="m2", key_b="internal", note="other")
        duplicate = KeyedRow(key_a="m1", key_b="internal", note="duplicate")
        version = duplicate._version
        with UnitOfWork():
            _dao(test_domain).save(other)
            assert _dao(test_domain).save_if_absent(duplicate) is None
            assert current_uow._tracked_instance(KeyedRow, duplicate.id) is None

        assert duplicate.state_.is_new
        assert duplicate._version == version

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

    def test_writes_a_row_whose_key_this_unit_of_work_freed(self, test_domain):
        repo = test_domain.repository_for(KeyedRow)
        first = KeyedRow(key_a="m1", key_b="internal", note="first")
        _dao(test_domain).save(first)

        newcomer = KeyedRow(key_a="m1", key_b="internal", note="newcomer")
        with UnitOfWork():
            moved = repo.get(first.id)
            moved.key_a = "m3"
            _dao(test_domain).save(moved)

            assert _dao(test_domain).save_if_absent(newcomer) is newcomer

        assert [r.note for r in _rows_with_key(test_domain, "m1", "internal")] == [
            "newcomer"
        ]
        assert repo.get(first.id).key_a == "m3"


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


def _skip_on_sqlite(test_domain):
    provider = test_domain.providers["default"]
    if getattr(provider, "__database__", None) == "sqlite":
        pytest.skip("SQLite lets one transaction write at a time")


def _race_a_live_writer(test_domain, live_commits):
    """Stage ``live`` in a unit of work on another thread, then call
    ``save_if_absent`` with the same key in this thread's unit of work while
    ``live`` is still in flight. The other thread then commits or rolls back.

    Returns the rows that hold the key, the row this thread saved beside it,
    and any error either thread raised.
    """
    live = KeyedRow(key_a="m1", key_b="internal", note="live")
    mine = KeyedRow(key_a="m1", key_b="internal", note="mine")
    other = KeyedRow(key_a="m2", key_b="internal", note="other")
    live_staged = threading.Event()
    mine_started = threading.Event()
    live_done = threading.Event()
    errors: list[Exception] = []

    def live_writer() -> None:
        ctx = test_domain.domain_context()
        ctx.push()
        try:
            uow = UnitOfWork()
            uow.start()
            assert _dao(test_domain).save_if_absent(live) is live
            # Send the INSERT now, so the database holds the key in flight.
            if hasattr(uow.get_session("default"), "flush"):
                uow.get_session("default").flush()
            live_staged.set()
            mine_started.wait(timeout=10)
            # Give this thread's write time to reach the database and wait
            # on the in-flight key.
            time.sleep(0.5)
            if live_commits:
                uow.commit()
            else:
                uow.rollback()
        except Exception as exc:
            errors.append(exc)
        finally:
            live_done.set()
            live_staged.set()
            ctx.pop()

    thread = threading.Thread(target=live_writer)
    thread.start()
    try:
        assert live_staged.wait(timeout=10)
        with UnitOfWork():
            _dao(test_domain).save(other)
            mine_started.set()
            _dao(test_domain).save_if_absent(mine)
            # Commit only after the live writer has finished.
            assert live_done.wait(timeout=10)
    except Exception as exc:
        errors.append(exc)
    finally:
        mine_started.set()
        thread.join(timeout=20)
    assert not thread.is_alive()

    stored_other = test_domain.repository_for(KeyedRow).query.filter(key_a="m2").all()
    return _rows_with_key(test_domain, "m1", "internal"), stored_other.items, errors


@pytest.mark.transactional
class TestSaveIfAbsentBesideALiveWriter:
    """A second writer calls ``save_if_absent`` while a first writer's unit of
    work holds the same key, written and not yet committed."""

    def test_the_second_writer_skips_its_row_when_the_first_commits(self, test_domain):
        _skip_on_sqlite(test_domain)

        rows, others, errors = _race_a_live_writer(test_domain, live_commits=True)

        assert errors == []
        assert [r.note for r in rows] == ["live"]
        assert [r.note for r in others] == ["other"]

    def test_the_second_writer_keeps_its_row_when_the_first_rolls_back(
        self, test_domain
    ):
        _skip_on_sqlite(test_domain)

        rows, others, errors = _race_a_live_writer(test_domain, live_commits=False)

        assert errors == []
        assert [r.note for r in rows] == ["mine"]
        assert [r.note for r in others] == ["other"]
