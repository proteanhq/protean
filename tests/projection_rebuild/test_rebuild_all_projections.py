"""Tests for rebuilding all projections."""

from unittest.mock import MagicMock, patch

import pytest

from protean import current_domain
from protean.utils.projection_rebuilder import rebuild_all_projections

from .elements import (
    Balances,
    Registered,
    Transacted,
    Transaction,
    TransactionProjector,
    User,
    UserDirectory,
    UserDirectoryProjector,
)


class TestRebuildAllWithNoProjections:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        # Register only aggregates, no projections
        test_domain.register(User)
        test_domain.register(Registered, part_of=User)
        test_domain.init(traverse=False)

    def test_rebuild_all_returns_empty_dict(self, test_domain):
        """rebuild_all_projections returns empty dict when no projections exist."""
        results = test_domain.rebuild_all_projections()
        assert results == {}


class TestRebuildAllWithMultipleProjections:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
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
        test_domain.register(UserDirectory)
        test_domain.register(
            UserDirectoryProjector,
            projector_for=UserDirectory,
            aggregates=[User],
        )
        test_domain.init(traverse=False)

    def test_rebuild_all_rebuilds_every_projection(self, test_domain):
        """rebuild_all_projections rebuilds all registered projections."""
        user = User.register(email="all@example.com", name="All")
        current_domain.repository_for(User).add(user)

        txn = Transaction.transact(user_id=user.id, amount=50.0)
        current_domain.repository_for(Transaction).add(txn)

        results = test_domain.rebuild_all_projections()

        assert "Balances" in results
        assert "UserDirectory" in results
        assert results["Balances"].success
        assert results["UserDirectory"].success

        # Verify data was rebuilt correctly
        balance = current_domain.repository_for(Balances).get(user.id)
        assert balance is not None
        assert balance.balance == 50.0

        directory = current_domain.repository_for(UserDirectory).get(user.id)
        assert directory is not None
        assert directory.email == "all@example.com"

    def test_rebuild_all_returns_results_dict(self, test_domain):
        """rebuild_all_projections returns a dict keyed by projection name."""
        results = test_domain.rebuild_all_projections()

        assert isinstance(results, dict)
        assert len(results) == 2
        for name, result in results.items():
            assert isinstance(name, str)
            assert result.success


class TestRebuildAllSkipsInternalProjections:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User)
        test_domain.register(Registered, part_of=User)
        test_domain.register(Balances)
        test_domain.register(
            TransactionProjector,
            projector_for=Balances,
            aggregates=[User],
        )
        test_domain.init(traverse=False)

    def test_internal_projections_skipped(self, test_domain):
        """rebuild_all_projections skips projections marked as internal."""
        # Inject a fake internal record into the registry
        internal_record = MagicMock()
        internal_record.internal = True
        internal_record.cls.__name__ = "InternalProjection"

        original_elements = test_domain.registry._elements["PROJECTION"]
        patched_elements = dict(original_elements)
        patched_elements["fake.internal.Projection"] = internal_record

        with patch.dict(
            test_domain.registry._elements["PROJECTION"],
            patched_elements,
            clear=True,
        ):
            results = rebuild_all_projections(test_domain)

        # Only Balances should be rebuilt, InternalProjection should be skipped
        assert "Balances" in results
        assert "InternalProjection" not in results
