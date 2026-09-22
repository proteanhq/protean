"""The database capability table is written down twice; keep the copies equal.

``protean test`` picks the marker expression for a ``--db`` leg from
``TestRunner.database_capabilities`` and ``database_capability_markers`` in
``src/protean/cli/test.py``. The generic conformance conftest deselects on the
same information from its own ``_DB_CAPABILITY_MARKERS``. Neither reads the
other, so adding a provider to one and forgetting the other silently runs a leg
with the wrong set of tests: too few and the gap is invisible, too many and the
leg fails for a capability the provider never claimed.

This test diffs the two, so the second copy cannot be forgotten.
"""

from protean.cli.test import TestRunner
from tests.adapters.repository.generic.conftest import (
    _ALL_CAPABILITY_MARKERS,
    _DB_CAPABILITY_MARKERS,
)


def cli_markers_by_database():
    """Flatten the CLI's two-step table into ``{database: {marker, ...}}``."""
    runner = TestRunner()
    return {
        database: runner.database_capability_markers[capability]
        for database, capability in runner.database_capabilities.items()
    }


def test_both_copies_cover_the_same_databases():
    assert set(cli_markers_by_database()) == set(_DB_CAPABILITY_MARKERS)


def test_both_copies_agree_on_every_database():
    assert cli_markers_by_database() == _DB_CAPABILITY_MARKERS


def test_every_marker_used_is_a_known_capability_marker():
    """A typo in either copy would otherwise deselect or select nothing."""
    for database, markers in _DB_CAPABILITY_MARKERS.items():
        assert markers <= _ALL_CAPABILITY_MARKERS, database
