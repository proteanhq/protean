"""Fields with ``choices`` save and load back on SQLite.

An ``Integer`` field with ``choices`` used to get a ``VARCHAR`` column. SQLite
stored the value as text, and the reloaded ``"2"`` then failed the field's
``Literal[1, 2, 3]`` check.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String


class Ticket(BaseAggregate):
    status: String(max_length=20, choices=["open", "closed"], required=True)
    level: Integer(choices=[1, 2, 3], required=True)


@pytest.fixture
def ticket_repository(test_domain):
    test_domain.register(Ticket)
    test_domain.init(traverse=False)

    provider = test_domain.providers["default"]
    repository = test_domain.repository_for(Ticket)
    table = repository._dao.database_model_cls.__table__
    # The test database is a file, so a table left by an earlier run would
    # hide the column types this run builds.
    table.drop(provider._engine, checkfirst=True)
    table.create(provider._engine)
    return repository


@pytest.mark.sqlite
class TestChoicesRoundTripOnSqlite:
    def test_the_columns_take_the_declared_types(self, ticket_repository):
        columns = ticket_repository._dao.database_model_cls.__table__.columns

        assert str(columns["status"].type) == "VARCHAR(20)"
        assert str(columns["level"].type) == "INTEGER"

    def test_an_integer_choice_loads_back_as_an_int(self, ticket_repository):
        ticket = Ticket(status="open", level=2)
        ticket_repository.add(ticket)

        reloaded = ticket_repository.get(ticket.id)

        assert reloaded.level == 2
        assert type(reloaded.level) is int
        assert reloaded.status == "open"

    def test_the_stored_value_is_an_integer(self, ticket_repository, test_domain):
        ticket_repository.add(Ticket(status="closed", level=3))

        rows = test_domain.providers["default"].raw("SELECT typeof(level) FROM ticket")

        assert [row[0] for row in rows] == ["integer"]
