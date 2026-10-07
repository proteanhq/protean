"""Run the examples on ``docs/reference/adapters/database/mysql.md``."""

import pytest
from sqlalchemy.dialects import mysql

from protean.exceptions import IncorrectUsageError
from tests.docs.support import load_example
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
