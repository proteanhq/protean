"""Edge case tests for projection rebuilding."""

from unittest.mock import MagicMock, patch

import pytest

from protean import current_domain
from protean.exceptions import ConfigurationError
from protean.utils.projection_rebuilder import (
    RebuildResult,
    _replay_projector,
    _truncate_projection,
)

from .elements import (
    Balances,
    Registered,
    Transaction,
    TransactionProjector,
    Transacted,
    User,
    UserDirectory,
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


class TestProjectionWithoutProjectors:
    @pytest.fixture(autouse=True)
    def register_orphan(self, test_domain):
        """Register a projection with no projector targeting it."""
        test_domain.register(UserDirectory)
        # Note: no projector registered for UserDirectory

    def test_rebuild_returns_error(self, test_domain):
        """Rebuilding a projection with no projectors returns an error."""
        result = test_domain.rebuild_projection(UserDirectory)

        assert not result.success
        assert len(result.errors) == 1
        assert "No projectors found" in result.errors[0]


class TestLargeEventCount:
    def test_many_events_processed_correctly(self, test_domain):
        """All events are replayed correctly regardless of event count."""
        user = User.register(email="batch@example.com", name="Batch")
        current_domain.repository_for(User).add(user)

        for i in range(25):
            txn = Transaction.transact(user_id=user.id, amount=1.0)
            current_domain.repository_for(Transaction).add(txn)

        result = test_domain.rebuild_projection(Balances)

        assert result.success
        # 1 Registered + 25 Transacted = 26 events dispatched
        assert result.events_dispatched == 26

        balance = current_domain.repository_for(Balances).get(user.id)
        assert balance is not None
        assert balance.balance == 25.0


class TestCacheBackedProjectionTruncation:
    def test_truncate_uses_cache_when_cache_backed(self):
        """_truncate_projection uses cache.remove_by_key_pattern for cached projections."""
        mock_cache = MagicMock()
        mock_projection_cls = MagicMock()
        mock_projection_cls.meta_.cache = "default"
        mock_projection_cls.__name__ = "CachedView"

        mock_domain = MagicMock()
        mock_domain.cache_for.return_value = mock_cache

        _truncate_projection(mock_domain, mock_projection_cls)

        mock_domain.cache_for.assert_called_once_with(mock_projection_cls)
        mock_cache.remove_by_key_pattern.assert_called_once_with("cached_view::*")

    def test_truncate_uses_dao_when_database_backed(self):
        """_truncate_projection uses dao._delete_all for database-backed projections."""
        mock_dao = MagicMock()
        mock_repo = MagicMock()
        mock_repo._dao = mock_dao

        mock_projection_cls = MagicMock()
        mock_projection_cls.meta_.cache = None
        mock_projection_cls.__name__ = "DbView"

        mock_domain = MagicMock()
        mock_domain.repository_for.return_value = mock_repo

        _truncate_projection(mock_domain, mock_projection_cls)

        mock_domain.repository_for.assert_called_once_with(mock_projection_cls)
        mock_dao._delete_all.assert_called_once()


class TestHandlerExceptionSkipsEvent:
    def test_generic_exception_is_caught_and_skipped(self, test_domain):
        """An exception during _handle() is caught and the event is skipped."""
        user = User.register(email="fail@example.com", name="Fail")
        current_domain.repository_for(User).add(user)

        with patch.object(
            TransactionProjector,
            "_handle",
            side_effect=RuntimeError("Handler failure"),
        ):
            dispatched, skipped = _replay_projector(
                test_domain,
                TransactionProjector,
                list(TransactionProjector.meta_.stream_categories),
                500,
            )

        assert dispatched == 0
        assert skipped >= 1


class TestConfigurationErrorSkipsEvent:
    def test_unresolvable_event_skipped(self, test_domain):
        """A ConfigurationError from to_domain_object() is caught and skipped."""
        user = User.register(email="unresolvable@example.com", name="Unresolvable")
        current_domain.repository_for(User).add(user)

        with patch.object(
            TransactionProjector,
            "_handle",
            side_effect=ConfigurationError("Unknown event type"),
        ):
            result = test_domain.rebuild_projection(Balances)

        assert result.success  # no errors list entries — just skipped
        assert result.events_skipped >= 1
        assert result.events_dispatched == 0


class TestRebuildResultDataclass:
    def test_success_when_no_errors(self):
        """RebuildResult.success is True when errors list is empty."""
        result = RebuildResult(projection_name="Test")
        assert result.success is True

    def test_failure_when_errors_present(self):
        """RebuildResult.success is False when errors list is non-empty."""
        result = RebuildResult(projection_name="Test", errors=["Something went wrong"])
        assert result.success is False

    def test_default_values(self):
        """RebuildResult has sensible defaults."""
        result = RebuildResult(projection_name="Test")
        assert result.projectors_processed == 0
        assert result.categories_processed == 0
        assert result.events_dispatched == 0
        assert result.events_skipped == 0
        assert result.errors == []
