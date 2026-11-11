"""Run the examples on ``docs/reference/adapters/database/mysql.md``."""

import pytest
from sqlalchemy.dialects import mysql

from protean.exceptions import IncorrectUsageError
from protean.infra import registry
from tests.docs.support import domain_from_config, load_example
from tests.shared import MYSQL_URI

pytestmark = [pytest.mark.no_test_domain, pytest.mark.mysql]


@pytest.fixture(autouse=True)
def mysql_url(monkeypatch):
    monkeypatch.setenv("MYSQL_URL", MYSQL_URI)


def test_unique_column_past_the_key_limit_raises():
    example = load_example("adapters/database/mysql/001.py")

    with example.domain.domain_context():
        with pytest.raises(IncorrectUsageError) as exc:
            example.domain.repository_for(example.User)._database_model

    message = str(exc.value)
    assert "token" in message
    assert "768" in message
    # The 255-character email is within the limit, so it is not named
    assert "email" not in message


def test_composite_index_past_the_key_limit_raises():
    example = load_example("adapters/database/mysql/001.py")

    with example.domain.domain_context():
        with pytest.raises(IncorrectUsageError) as exc:
            example.domain.repository_for(example.Document)._database_model

    message = str(exc.value)
    assert "tenant, slug" in message
    assert "4000 bytes" in message


def test_custom_model_uses_mysql_column_types():
    example = load_example("adapters/database/mysql/002.py")

    with example.domain.domain_context():
        model = example.domain.repository_for(example.User)._database_model
        columns = model.__table__.columns

    assert isinstance(columns["name"].type, mysql.VARCHAR)
    assert columns["name"].type.length == 100
    assert isinstance(columns["preferences"].type, mysql.JSON)


@pytest.mark.parametrize(
    "path, drivername",
    [
        ("adapters/database/mysql/mysql.toml", "mysql+pymysql"),
        ("adapters/database/mysql/mariadb.toml", "mariadb+pymysql"),
    ],
    ids=["mysql", "mariadb"],
)
def test_configuration_shown_carries_the_password(
    path, drivername, tmp_path, monkeypatch
):
    monkeypatch.setenv("MYSQL_PASSWORD", "secret-pass")
    domain = domain_from_config(path, tmp_path)
    conn_info = dict(domain.config["databases"]["default"])

    provider = registry.providers.get(conn_info["provider"])(
        "default", domain, conn_info
    )

    url = provider._engine.url
    assert url.drivername == drivername
    assert (url.username, url.password) == ("app", "secret-pass")
    assert (url.host, url.port, url.database) == ("localhost", 3306, "appdb")
