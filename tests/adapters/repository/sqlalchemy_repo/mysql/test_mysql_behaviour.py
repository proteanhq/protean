"""MySQL and MariaDB behaviour that only a live server can show.

Every test here is parametrized over both servers. One provider serves both, and
SQLAlchemy reports two different dialect names for them, so a branch that works
on MySQL and skips MariaDB is the most likely way this adapter breaks.

The capability-gated conformance battery in
``tests/adapters/repository/generic/`` is the portable bar and runs against both
through ``--db MYSQL`` and ``--db MARIADB``. What is left here is the behaviour
that is specific to these servers: collation, fractional seconds, the stored
column types, and the isolation level.
"""

from datetime import datetime

import pytest
from sqlalchemy import text

from protean import Domain, UnitOfWork
from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime, Dict, Integer, List, String, Text
from tests.shared import MARIADB_URI, MYSQL_URI

pytestmark = [pytest.mark.mysql, pytest.mark.no_test_domain]

SERVERS = [
    pytest.param(MYSQL_URI, id="mysql"),
    pytest.param(MARIADB_URI, id="mariadb"),
]


class Note(BaseAggregate):
    title: String(max_length=50)
    body: Text()
    written_at: DateTime()
    tags: List()
    extra: Dict()
    read_count: Integer(default=0)


@pytest.fixture(params=SERVERS)
def mysql_domain(request):
    """A MySQL or MariaDB domain with its own table, dropped after each test."""
    domain = Domain(
        name="MySQL behaviour",
        config={
            "identity_type": "uuid",
            "databases": {
                "default": {
                    "provider": "mysql",
                    "database_uri": request.param,
                    "pool_size": 5,
                    "max_overflow": 5,
                }
            },
        },
    )
    domain.register(Note)
    domain.init(traverse=False)

    provider = domain.providers["default"]
    try:
        with domain.domain_context():
            # Touch the DAO inside the context: column mapping reads
            # ``identity_type`` off the active domain.
            domain.repository_for(Note)._dao
            provider._metadata.create_all(provider._engine)
            yield domain
    finally:
        provider._metadata.drop_all(provider._engine)
        provider.close()


def column_info(domain, column):
    """The ``information_schema`` row for one column of the ``note`` table."""
    provider = domain.providers["default"]
    with provider._engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT column_type, character_set_name, collation_name "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'note' "
                "AND column_name = :column"
            ),
            {"column": column},
        ).one()


class TestCollation:
    """The server default is accent-insensitive and case-insensitive on both
    servers, so without an explicit column collation every string lookup would
    match the wrong rows. The conformance battery expects case-sensitive
    behaviour, which the other three providers give."""

    @pytest.fixture(autouse=True)
    def _notes(self, mysql_domain):
        dao = mysql_domain.repository_for(Note)._dao
        for title in ("Alpha", "alpha", "ALPHA"):
            dao.create(title=title)

    @staticmethod
    def titles(mysql_domain, **criteria):
        found = mysql_domain.repository_for(Note)._dao.query.filter(**criteria).all()
        return sorted(note.title for note in found.items)

    def test_exact_is_case_sensitive(self, mysql_domain):
        assert self.titles(mysql_domain, title="Alpha") == ["Alpha"]

    def test_contains_is_case_sensitive(self, mysql_domain):
        assert self.titles(mysql_domain, title__contains="lph") == ["Alpha", "alpha"]

    def test_startswith_is_case_sensitive(self, mysql_domain):
        assert self.titles(mysql_domain, title__startswith="Al") == ["Alpha"]

    def test_endswith_is_case_sensitive(self, mysql_domain):
        assert self.titles(mysql_domain, title__endswith="PHA") == ["ALPHA"]

    def test_iexact_still_matches_every_case(self, mysql_domain):
        """The case-insensitive lookups must keep working on a collated column."""
        assert self.titles(mysql_domain, title__iexact="alpha") == [
            "ALPHA",
            "Alpha",
            "alpha",
        ]

    @pytest.mark.parametrize("column", ["title", "body"])
    def test_every_string_column_inherits_the_table_collation(
        self, mysql_domain, column
    ):
        """The collation is set once as a table default; VARCHAR and TEXT
        columns both pick it up."""
        _, charset, collation = column_info(mysql_domain, column)

        assert charset == "utf8mb4"
        assert collation == "utf8mb4_0900_as_cs"


class TestStoredColumnTypes:
    def test_a_bounded_string_is_a_varchar(self, mysql_domain):
        assert column_info(mysql_domain, "title")[0] == "varchar(50)"

    def test_an_unbounded_string_is_text(self, mysql_domain):
        """MySQL cannot create a VARCHAR with no length."""
        assert column_info(mysql_domain, "body")[0] == "text"

    def test_a_datetime_carries_six_fractional_digits(self, mysql_domain):
        assert column_info(mysql_domain, "written_at")[0] == "datetime(6)"

    def test_an_identifier_is_char_32(self, mysql_domain):
        """A UUID identity falls through the GUID type to CHAR(32) here."""
        assert column_info(mysql_domain, "id")[0] == "char(32)"


class TestRoundTrips:
    def test_microseconds_survive(self, mysql_domain):
        """A plain DATETIME drops them on write with no error."""
        written_at = datetime(2026, 9, 21, 13, 45, 6, 123456)
        dao = mysql_domain.repository_for(Note)._dao
        note = dao.create(title="Timed", written_at=written_at)

        assert dao.get(note.id).written_at == written_at

    def test_four_byte_characters_survive(self, mysql_domain):
        """An emoji needs utf8mb4; on utf8mb3 it truncates or raises."""
        dao = mysql_domain.repository_for(Note)._dao
        note = dao.create(title="Deploy 🚀 done")

        assert dao.get(note.id).title == "Deploy 🚀 done"

    def test_a_dict_round_trips_through_json(self, mysql_domain):
        dao = mysql_domain.repository_for(Note)._dao
        note = dao.create(title="Doc", extra={"owner": "ops", "retries": 3})

        assert dao.get(note.id).extra == {"owner": "ops", "retries": 3}

    def test_a_list_round_trips_through_json(self, mysql_domain):
        """MySQL has no array type, so a list is stored as JSON."""
        dao = mysql_domain.repository_for(Note)._dao
        note = dao.create(title="Doc", tags=["urgent", "ops"])

        assert dao.get(note.id).tags == ["urgent", "ops"]


class TestTransactionBehaviour:
    def test_the_session_runs_at_read_committed(self, mysql_domain):
        """InnoDB defaults to REPEATABLE READ, under which a transaction keeps
        reading the snapshot it opened with. ADR-0027 expects a read to see what
        other transactions have committed."""
        provider = mysql_domain.providers["default"]
        with provider._engine.connect() as conn:
            level = conn.execute(text("SELECT @@transaction_isolation")).scalar()

        assert level.replace("-", " ") == "READ COMMITTED"

    def test_a_rolled_back_unit_of_work_leaves_nothing_behind(self, mysql_domain):
        """InnoDB is transactional, so the whole UoW is one real transaction."""
        dao = mysql_domain.repository_for(Note)._dao
        with UnitOfWork():
            dao.create(title="Kept")

        with pytest.raises(RuntimeError), UnitOfWork():
            dao.create(title="Discarded")
            raise RuntimeError("abandon the unit of work")

        assert [note.title for note in dao.query.all().items] == ["Kept"]

    def test_ddl_commits_the_open_transaction(self, mysql_domain):
        """MySQL has no transactional DDL: a CREATE or DROP inside a transaction
        commits whatever is pending. The adapter creates tables on a connection
        of its own, outside any Unit of Work, so this only bites a caller who
        runs DDL mid-transaction. Pinned here so the constraint is visible."""
        provider = mysql_domain.providers["default"]
        with provider._engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO note (id, title, read_count) "
                    "VALUES ('0123456789abcdef0123456789abcdef', 'Kept', 0)"
                )
            )
            conn.execute(text("CREATE TABLE ddl_probe (id INT)"))
            conn.rollback()
            conn.execute(text("DROP TABLE ddl_probe"))

        with provider._engine.connect() as conn:
            surviving = conn.execute(text("SELECT COUNT(*) FROM note")).scalar()

        assert surviving == 1
