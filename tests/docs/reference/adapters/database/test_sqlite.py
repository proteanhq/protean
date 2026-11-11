"""Run the example on ``docs/reference/adapters/database/sqlite.md``."""

import pytest
import sqlalchemy as sa

from protean.adapters.repository.sqlalchemy import SqliteProvider
from tests.docs.support import domain_from_config, load_example

pytestmark = [pytest.mark.no_test_domain, pytest.mark.sqlite]


def test_custom_model_uses_its_own_columns(monkeypatch, tmp_path):
    # The example writes test.db to the working directory
    monkeypatch.chdir(tmp_path)
    example = load_example("adapters/database/sqlite/001.py")

    with example.domain.domain_context():
        model = example.domain.repository_for(example.User)._database_model
        columns = model.__table__.columns

    assert isinstance(columns["name"].type, sa.String)
    assert columns["name"].type.length == 100
    assert columns["email"].type.length == 255
    assert columns["email"].unique is True
    assert not columns["name"].unique


def test_configuration_shown_builds_a_sqlite_provider(tmp_path, monkeypatch):
    database = tmp_path / "app.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    domain = domain_from_config("adapters/database/sqlite/configuration.toml", tmp_path)
    domain.init(traverse=False)

    provider = domain.providers["default"]
    assert type(provider) is SqliteProvider
    assert provider._engine.url.database == str(database)


def test_configuration_shown_defaults_to_the_documented_uri(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    domain = domain_from_config("adapters/database/sqlite/configuration.toml", tmp_path)

    assert domain.config["databases"]["default"]["database_uri"] == "sqlite:///app.db"
