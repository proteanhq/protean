"""``protean db migrate``, ``upgrade`` and ``downgrade`` against SQL Server.

Each test creates a database of its own on the test server and drops it after.
"""

from collections.abc import Iterator

import pytest

from tests.shared import MSSQL_URI
from tests.support.migrations import (
    MigrationsProject,
    assert_no_change_at_head,
    assert_raw_indexes_migrate,
    columns,
    fresh_database,
    make_project,
    migrate_add_field_and_upgrade,
    row_count,
)

pytestmark = [pytest.mark.mssql, pytest.mark.no_test_domain]


@pytest.fixture
def database() -> Iterator[str]:
    with fresh_database(MSSQL_URI) as url:
        yield url


@pytest.fixture
def project(tmp_path, monkeypatch, database) -> Iterator[MigrationsProject]:
    project = make_project(
        tmp_path,
        monkeypatch,
        {"default": {"provider": "mssql", "database_uri": database}},
        "uuid",
    )
    yield project
    project.forget_modules()


def test_a_new_field_becomes_a_column_and_the_rows_stay(project, database):
    migrate_add_field_and_upgrade(project)

    assert columns(database, "product") == {"id", "name", "price", "_version"}
    assert row_count(database, "product") == 2


def test_an_unchanged_model_writes_no_file(project):
    assert_no_change_at_head(project, "mssql")


def test_raw_indexes_are_created_and_compared(project, database):
    assert_raw_indexes_migrate(project, database, "mssql")
