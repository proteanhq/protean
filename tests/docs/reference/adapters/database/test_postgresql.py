"""Run the examples on ``docs/reference/adapters/database/postgresql.md``."""

import pytest
import sqlalchemy as sa

from protean.adapters.repository.sqlalchemy import (
    PostgresqlProvider,
    SqlalchemyModel,
    _maybe_log_query,
)
from tests.docs.support import DOCS_SRC, domain_from_config, load_example
from tests.shared import POSTGRES_PORT, POSTGRES_URI

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


def test_configuration_shown_builds_a_postgresql_provider(tmp_path):
    domain = domain_from_config(
        "adapters/database/postgresql/configuration.toml", tmp_path
    )
    domain.init(traverse=False)

    provider = domain.providers["default"]
    assert type(provider) is PostgresqlProvider
    url = provider._engine.url
    assert (url.host, url.port, url.database) == (
        "localhost",
        POSTGRES_PORT,
        "postgres",
    )


def test_configuration_shown_defaults_to_the_documented_uri(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    domain = domain_from_config(
        "adapters/database/postgresql/configuration.toml", tmp_path
    )

    assert (
        domain.config["databases"]["default"]["database_uri"]
        == "postgresql://postgres:postgres@localhost:5432/postgres"
    )


SLOW_QUERIES = "adapters/database/postgresql/slow_queries.toml"


def _slow_query_records(text, duration_ms, tmp_path, caplog):
    domain = domain_from_config(SLOW_QUERIES, tmp_path, text=text)
    caplog.clear()
    with domain.domain_context():
        _maybe_log_query("SELECT " + "x" * 1000, {}, duration_ms)
    return [r for r in caplog.records if r.getMessage().endswith("slow_query")]


def test_slow_query_settings_shown_reach_the_query_log(tmp_path, caplog):
    text = (DOCS_SRC / SLOW_QUERIES).read_text()
    caplog.set_level("WARNING")

    assert _slow_query_records(text, 100, tmp_path, caplog) == []
    [record] = _slow_query_records(text, 101, tmp_path, caplog)
    assert record.threshold_ms == 100
    assert len(record.statement) == 500 + len("...")


def test_changed_slow_query_settings_reach_the_query_log(tmp_path, caplog):
    # The documented values equal the defaults, so change each one to show
    # that the query log reads the key.
    text = (DOCS_SRC / SLOW_QUERIES).read_text()
    for old, new in [
        ("slow_query_threshold_ms = 100", "slow_query_threshold_ms = 250"),
        ("slow_query_truncate_chars = 500", "slow_query_truncate_chars = 40"),
    ]:
        assert old in text
        text = text.replace(old, new)
    caplog.set_level("WARNING")

    assert _slow_query_records(text, 200, tmp_path, caplog) == []
    [record] = _slow_query_records(text, 251, tmp_path, caplog)
    assert record.threshold_ms == 250
    assert len(record.statement) == 40 + len("...")
