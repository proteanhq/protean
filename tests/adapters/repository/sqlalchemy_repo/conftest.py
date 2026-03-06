"""Conftest for SQLAlchemy-specific repository tests."""

import pytest

from protean.adapters.repository.sqlalchemy import SAProvider


@pytest.fixture
def require_sa_provider(test_domain):
    """Skip the test if the default provider is not an SAProvider.

    Use as a class-level or test-level autouse fixture for tests that
    only make sense with an SQLAlchemy provider.
    """
    provider = test_domain.providers["default"]
    if not isinstance(provider, SAProvider):
        pytest.skip("Only applicable to SQLAlchemy providers")
