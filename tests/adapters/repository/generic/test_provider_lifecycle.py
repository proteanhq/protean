"""Generic provider lifecycle tests that run against all database providers.

Covers is_alive() lifecycle method on the provider across different states.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import String


class LifecycleUser(BaseAggregate):
    name: String(max_length=100, required=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(LifecycleUser)
    test_domain.init(traverse=False)


@pytest.mark.basic_storage
class TestProviderIsAlive:
    """Verify is_alive() returns True when provider is operational."""

    def test_is_alive_after_initialization(self, test_domain):
        provider = test_domain.providers["default"]
        assert provider.is_alive() is True

    def test_is_alive_after_operations(self, test_domain):
        # Perform some operations
        test_domain.repository_for(LifecycleUser).add(LifecycleUser(name="Alice"))
        results = test_domain.repository_for(LifecycleUser)._dao.query.all()
        assert results.total == 1

        # Provider should still be alive
        provider = test_domain.providers["default"]
        assert provider.is_alive() is True

    def test_is_alive_after_multiple_operations(self, test_domain):
        # Multiple sequential operations
        for i in range(3):
            test_domain.repository_for(LifecycleUser).add(
                LifecycleUser(name=f"User-{i}")
            )

        results = test_domain.repository_for(LifecycleUser)._dao.query.all()
        assert results.total == 3

        provider = test_domain.providers["default"]
        assert provider.is_alive() is True


@pytest.mark.basic_storage
class TestProviderClose:
    """Verify close() is a callable method on all providers.

    Note: Actually calling close() on the active provider would prevent
    test teardown from working (e.g., _data_reset needs the connection).
    This test verifies the method exists and is callable without
    actually closing the active test connection.
    """

    def test_close_is_callable(self, test_domain):
        provider = test_domain.providers["default"]
        assert callable(provider.close)
