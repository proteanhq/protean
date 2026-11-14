"""``protean db migrate``, ``upgrade`` and ``downgrade`` on MySQL and MariaDB.

Each test creates a database of its own on the test server and drops it after.
"""

from collections.abc import Iterator

import pytest

from tests.shared import MARIADB_URI, MYSQL_URI
from tests.support.migrations import (
    MigrationsProject,
    assert_check_matches_at_head,
    assert_no_change_at_head,
    assert_raw_indexes_migrate,
    columns,
    fresh_database,
    make_project,
    migrate_add_field_and_upgrade,
    row_count,
)

pytestmark = [pytest.mark.mysql, pytest.mark.no_test_domain]


@pytest.fixture(
    params=[
        pytest.param((MYSQL_URI, "mysql"), id="mysql"),
        pytest.param((MARIADB_URI, "mariadb"), id="mariadb"),
    ]
)
def server(request) -> tuple[str, str]:
    """The server URL and the dialect name SQLAlchemy reports for it."""
    return request.param


@pytest.fixture
def database(server) -> Iterator[str]:
    with fresh_database(server[0]) as url:
        yield url


@pytest.fixture
def project(tmp_path, monkeypatch, database) -> Iterator[MigrationsProject]:
    project = make_project(
        tmp_path,
        monkeypatch,
        {"default": {"provider": "mysql", "database_uri": database}},
        "uuid",
    )
    yield project
    project.forget_modules()


def test_a_new_field_becomes_a_column_and_the_rows_stay(project, database):
    migrate_add_field_and_upgrade(project)

    assert columns(database, "product") == {"id", "name", "price", "_version"}
    assert row_count(database, "product") == 2


def test_an_unchanged_model_writes_no_file(project, server):
    assert_no_change_at_head(project, server[1])


def test_check_finds_an_unchanged_model_matches(project, server):
    assert_check_matches_at_head(project, server[1])


def test_raw_indexes_are_created_and_compared(project, database, server):
    assert_raw_indexes_migrate(project, database, server[1])
