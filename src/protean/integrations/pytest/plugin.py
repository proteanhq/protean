"""Protean pytest plugin — auto-registered via the ``pytest11`` entry point.

Sets ``PROTEAN_ENV`` **before** test collection so that domain.toml
environment overlays are applied when Domain instances are constructed
at import time.  Also registers standard test-category markers.
"""

import os


def pytest_addoption(parser):
    """Add ``--protean-env`` and ``--update-snapshots`` CLI options."""
    parser.addoption(
        "--protean-env",
        action="store",
        default="test",
        help="Protean environment overlay to activate (maps to PROTEAN_ENV)",
    )
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Regenerate all assert_snapshot() reference files",
    )


def pytest_configure(config):
    """Set PROTEAN_ENV before test collection.

    Domain modules are imported at collection time (test files import
    aggregates/commands which import the Domain instance).  The Domain
    reads domain.toml and applies environment overlays during construction,
    so PROTEAN_ENV must be set before any domain module is imported.
    """
    env = config.getoption("--protean-env", default="test")
    os.environ.setdefault("PROTEAN_ENV", env)

    # Propagate --update-snapshots to the testing module
    if config.getoption("--update-snapshots", default=False):
        import protean.testing as _testing

        _testing._update_snapshots = True

    # Register standard markers so --strict-markers doesn't complain
    config.addinivalue_line("markers", "domain: pure domain logic tests (no DB)")
    config.addinivalue_line("markers", "application: command handler tests (with DB)")
    config.addinivalue_line(
        "markers", "integration: cross-domain event/projection tests"
    )
    config.addinivalue_line("markers", "slow: slow-running tests")
    config.addinivalue_line("markers", "bdd: behavior-driven tests")
