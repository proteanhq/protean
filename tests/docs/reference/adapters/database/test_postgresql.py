"""Run the examples on ``docs/reference/adapters/database/postgresql.md``."""

import pytest
import sqlalchemy as sa

from protean.adapters.repository.sqlalchemy import SqlalchemyModel
from tests.docs.support import load_example
from tests.shared import POSTGRES_URI

pytestmark = [pytest.mark.no_test_domain, pytest.mark.postgresql]


@pytest.fixture(autouse=True)
def database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", POSTGRES_URI)


def test_custom_model_replaces_the_generated_columns():
    example = load_example("adapters/database/postgresql/001.py")

    with example.domain.domain_context():
        model = example.domain.repository_for(example.Provider)._database_model
        columns = model.__table__.columns

    assert issubclass(model, SqlalchemyModel)
    assert isinstance(columns["name"].type, sa.Text)
    assert isinstance(columns["age"].type, sa.Integer)


def test_raw_query_reads_the_users_table():
    example = load_example("adapters/database/postgresql/002.py")

    with example.domain.domain_context():
        provider = example.domain.providers["default"]
        provider._create_database_artifacts()
        try:
            repo = example.domain.repository_for(example.User)
            repo.add(example.User(name="Ada", age=36))
            repo.add(example.User(name="Tim", age=17))

            rows = [(row.name, row.age) for row in example.users_older_than(21)]
            nobody = list(example.users_older_than(99))
        finally:
            provider._drop_database_artifacts()

    assert rows == [("Ada", 36)]
    assert nobody == []
