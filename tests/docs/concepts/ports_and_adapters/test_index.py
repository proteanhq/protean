"""Run the example on ``docs/concepts/ports-and-adapters/index.md``."""

import importlib.util

import pytest

from protean.exceptions import ConfigurationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_init_halts_when_the_database_cannot_be_reached():
    # The PostgreSQL provider registers only when SQLAlchemy is installed.
    # Without it the provider is unknown. With it, the connection to the
    # missing database fails, as the page shows.
    if importlib.util.find_spec("sqlalchemy") is None:
        expected = "Unknown database provider 'postgresql'"
    else:
        expected = (
            "Could not connect to database at "
            "postgresql://postgres:postgres@localhost:5444/foobar"
        )

    with pytest.raises(ConfigurationError, match=expected):
        load_example("adapters/001.py")
