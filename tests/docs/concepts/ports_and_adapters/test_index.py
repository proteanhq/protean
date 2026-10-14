"""Run the example on ``docs/concepts/ports-and-adapters/index.md``."""

import importlib

import pytest

from protean.exceptions import ConfigurationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _imports(module: str) -> bool:
    try:
        importlib.import_module(module)
    except ImportError:
        return False
    return True


# The page shows the error for an install that has the PostgreSQL adapter.
# Without SQLAlchemy or a PostgreSQL driver, ``domain.init()`` fails earlier,
# with a different error, so the page's claim cannot be checked.
requires_postgresql_adapter = pytest.mark.skipif(
    not _imports("sqlalchemy") or not (_imports("psycopg") or _imports("psycopg2")),
    reason="needs SQLAlchemy and a PostgreSQL driver",
)


@requires_postgresql_adapter
def test_init_halts_when_the_database_cannot_be_reached():
    with pytest.raises(
        ConfigurationError,
        match=(
            "Could not connect to database at "
            "postgresql://postgres:postgres@localhost:5444/foobar"
        ),
    ):
        load_example("adapters/001.py")
