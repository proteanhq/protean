"""Conftest for generic database capability tests.

Automatically skips tests when the current database provider
does not have the capability required by the test's marker.
"""

import pytest

from protean.port.provider import DatabaseCapabilities

# Mapping from marker name to the DatabaseCapabilities flag(s) required
MARKER_TO_CAPABILITY = {
    "basic_storage": DatabaseCapabilities.BASIC_STORAGE,
    "transactional": (
        DatabaseCapabilities.TRANSACTIONS | DatabaseCapabilities.SIMULATED_TRANSACTIONS
    ),
    "atomic_transactions": DatabaseCapabilities.TRANSACTIONS,
    "raw_queries": DatabaseCapabilities.RAW_QUERIES,
    "schema_management": DatabaseCapabilities.SCHEMA_MANAGEMENT,
    "native_json": DatabaseCapabilities.NATIVE_JSON,
    "native_array": DatabaseCapabilities.NATIVE_ARRAY,
}


def pytest_collection_modifyitems(config, items):
    """Skip tests whose capability marker is not satisfied by the current provider."""
    for item in items:
        for marker_name, required_caps in MARKER_TO_CAPABILITY.items():
            marker = item.get_closest_marker(marker_name)
            if marker is None:
                continue

            # Store the required capability on the item for the fixture to check
            item._database_required_capability = (marker_name, required_caps)
            break  # A test should only have one capability marker


@pytest.fixture(autouse=True)
def _skip_if_provider_lacks_capability(request, test_domain):
    """Skip the test if the provider lacks the required capability."""
    cap_info = getattr(request.node, "_database_required_capability", None)
    if cap_info is None:
        return

    marker_name, required_caps = cap_info
    provider = test_domain.providers["default"]

    # For `transactional`, the provider needs TRANSACTIONS or SIMULATED_TRANSACTIONS
    if marker_name == "transactional":
        if not provider.has_any_capability(required_caps):
            pytest.skip(
                f"Provider '{provider.name}' ({provider.__class__.__name__}) "
                f"lacks transaction support (real or simulated)"
            )
    else:
        # For all other markers, ALL flag bits must be present
        if not provider.has_all_capabilities(required_caps):
            pytest.skip(
                f"Provider '{provider.name}' ({provider.__class__.__name__}) "
                f"lacks required capability: {marker_name}"
            )
