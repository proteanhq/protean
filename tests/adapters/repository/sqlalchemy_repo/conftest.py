"""Conftest for SQLAlchemy-specific repository tests.

Deselects tests marked with @pytest.mark.sa_provider at collection time
when --db is not a SQLAlchemy-backed database, avoiding noisy SKIPPED messages.
"""

# Database types backed by SQLAlchemy
_SA_DATABASES = {"POSTGRESQL", "SQLITE", "MSSQL"}


def pytest_collection_modifyitems(config, items):
    """Deselect sa_provider-marked tests when --db is not an SA database."""
    db_option = config.getoption("--db", "MEMORY").upper()
    if db_option in _SA_DATABASES:
        return

    deselected = []
    remaining = []

    for item in items:
        if item.get_closest_marker("sa_provider"):
            deselected.append(item)
        else:
            remaining.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = remaining
