"""Shared pytest configuration for the diagnostics tests.

Every test in this package builds its own ``Domain`` to trigger a specific
diagnostic, so none of them want the autouse default ``test_domain`` fixture
(``tests/conftest.py``) — running inside its ``domain_context()`` is both wasted
setup and an unwanted active context. The monolith this package was split from
marked each class ``@pytest.mark.no_test_domain`` by hand; applying it here
package-wide means a new rule file inherits it automatically, with no per-file
marker to remember.
"""

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "ir/diagnostics/" in item.nodeid:
            item.add_marker(pytest.mark.no_test_domain)
