"""Tests for domain.rebuild_projection() and domain.rebuild_all_projections()."""

import pytest

from protean import current_domain
from protean.utils.projection_rebuilder import RebuildResult

from .elements import (
    Balances,
    Registered,
    Transaction,
    TransactionProjector,
    Transacted,
    User,
)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Transaction)
    test_domain.register(Transacted, part_of=Transaction)
    test_domain.register(Balances)
    test_domain.register(
        TransactionProjector,
        projector_for=Balances,
        aggregates=[Transaction, User],
    )
    test_domain.init(traverse=False)


class TestDomainRebuildProjection:
    def test_method_exists(self, test_domain):
        """Domain has a rebuild_projection method."""
        assert hasattr(test_domain, "rebuild_projection")
        assert callable(test_domain.rebuild_projection)

    def test_returns_rebuild_result(self, test_domain):
        """rebuild_projection returns a RebuildResult instance."""
        result = test_domain.rebuild_projection(Balances)
        assert isinstance(result, RebuildResult)

    def test_delegates_correctly(self, test_domain):
        """rebuild_projection actually processes events."""
        user = User.register(email="api@example.com", name="API")
        current_domain.repository_for(User).add(user)

        result = test_domain.rebuild_projection(Balances)

        assert result.success
        assert result.events_dispatched >= 1

        balance = current_domain.repository_for(Balances).get(user.id)
        assert balance is not None

    def test_custom_batch_size(self, test_domain):
        """rebuild_projection accepts a custom batch_size."""
        result = test_domain.rebuild_projection(Balances, batch_size=10)
        assert result.success


class TestDomainRebuildAllProjections:
    def test_method_exists(self, test_domain):
        """Domain has a rebuild_all_projections method."""
        assert hasattr(test_domain, "rebuild_all_projections")
        assert callable(test_domain.rebuild_all_projections)

    def test_returns_dict(self, test_domain):
        """rebuild_all_projections returns a dict."""
        results = test_domain.rebuild_all_projections()
        assert isinstance(results, dict)

    def test_delegates_correctly(self, test_domain):
        """rebuild_all_projections processes all projections."""
        user = User.register(email="allapi@example.com", name="AllAPI")
        current_domain.repository_for(User).add(user)

        results = test_domain.rebuild_all_projections()

        assert "Balances" in results
        assert results["Balances"].success
