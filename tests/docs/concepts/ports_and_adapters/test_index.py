"""Run the example on ``docs/concepts/ports-and-adapters/index.md``."""

import pytest

from protean.exceptions import ConfigurationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_init_halts_when_the_database_cannot_be_reached():
    # The message differs by lane: without the PostgreSQL extra installed the
    # provider is unknown, with it the connection fails. Both halt init.
    with pytest.raises(ConfigurationError):
        load_example("adapters/001.py")
