"""An ``Integer`` field with ``choices`` saves and loads back on PostgreSQL.

The field used to get a ``VARCHAR`` column, so the value came back as a string
that failed the field's ``Literal[1, 2, 3]`` check.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.fields import Integer, String
from tests.shared import POSTGRES_URI


class Grade(BaseAggregate):
    status: String(max_length=20, choices=["open", "closed"], required=True)
    level: Integer(choices=[1, 2, 3], required=True)


@pytest.mark.postgresql
@pytest.mark.no_test_domain
def test_choices_columns_save_and_load_back():
    domain = Domain(
        name="PostgresChoices",
        config={
            "databases": {
                "default": {"provider": "postgresql", "database_uri": POSTGRES_URI}
            }
        },
    )
    domain.register(Grade)
    domain.init(traverse=False)

    with domain.domain_context():
        repo = domain.repository_for(Grade)
        provider = domain.providers["default"]
        columns = repo._dao.database_model_cls.__table__.columns
        dialect = provider._engine.dialect
        assert columns["status"].type.compile(dialect=dialect) == "VARCHAR(20)"
        assert columns["level"].type.compile(dialect=dialect) == "INTEGER"

        provider._metadata.create_all(provider._engine)
        try:
            saved = Grade(status="open", level=2)
            repo.add(saved)
            loaded = repo.get(saved.id)
        finally:
            provider._metadata.drop_all(provider._engine)
            domain.providers.close()

    assert loaded.level == 2
    assert type(loaded.level) is int
    assert loaded.status == "open"
