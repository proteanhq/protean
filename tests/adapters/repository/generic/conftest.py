"""Conftest for generic database capability tests.

Deselects tests at collection time when the current --db provider
does not support the capability required by the test's marker.
This avoids noisy SKIPPED messages in default (Memory) test runs.
"""

# Static mapping from --db option to supported capability markers.
# Mirrors the database_capability_markers in src/protean/cli/test.py.
_DB_CAPABILITY_MARKERS: dict[str, set[str]] = {
    "MEMORY": {"basic_storage", "transactional", "raw_queries"},
    "POSTGRESQL": {
        "basic_storage",
        "transactional",
        "atomic_transactions",
        "raw_queries",
        "schema_management",
        "native_json",
        "native_array",
    },
    "SQLITE": {
        "basic_storage",
        "transactional",
        "atomic_transactions",
        "raw_queries",
        "schema_management",
    },
    "MSSQL": {
        "basic_storage",
        "transactional",
        "atomic_transactions",
        "raw_queries",
        "schema_management",
        "native_json",
        "native_array",
    },
    "ELASTICSEARCH": {"basic_storage", "schema_management"},
}

# All capability markers that gate tests in this directory
_ALL_CAPABILITY_MARKERS = {
    "basic_storage",
    "transactional",
    "atomic_transactions",
    "raw_queries",
    "schema_management",
    "native_json",
    "native_array",
}


def pytest_collection_modifyitems(config, items):
    """Deselect tests whose capability marker is not supported by the current --db."""
    db_option = config.getoption("--db", "MEMORY").upper()
    supported = _DB_CAPABILITY_MARKERS.get(db_option, set())

    deselected = []
    remaining = []

    for item in items:
        marker_name = None
        for name in _ALL_CAPABILITY_MARKERS:
            if item.get_closest_marker(name):
                marker_name = name
                break

        if marker_name is not None and marker_name not in supported:
            deselected.append(item)
        else:
            remaining.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = remaining
