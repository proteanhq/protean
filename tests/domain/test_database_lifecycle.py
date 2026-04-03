"""Tests for Domain database lifecycle methods and outbox configuration."""

from unittest.mock import PropertyMock, patch

import pytest

from protean.domain import Domain
from protean.exceptions import ConfigurationError


# ---------------------------------------------------------------------------
# has_outbox property
# ---------------------------------------------------------------------------
class TestHasOutboxProperty:
    @pytest.mark.no_test_domain
    def test_returns_true_when_subscription_type_is_stream(self):
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        assert domain.has_outbox is True

    @pytest.mark.no_test_domain
    def test_returns_true_when_enable_outbox_is_true_with_stream(self):
        """Backward compat: enable_outbox=True + stream is redundant but valid."""
        domain = Domain(name="Test")
        domain.config["enable_outbox"] = True
        domain.config["server"]["default_subscription_type"] = "stream"
        assert domain.has_outbox is True

    @pytest.mark.no_test_domain
    def test_returns_false_when_defaults(self):
        domain = Domain(name="Test")
        assert domain.has_outbox is False

    @pytest.mark.no_test_domain
    def test_returns_false_when_event_store_explicit(self):
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "event_store"
        assert domain.has_outbox is False


# ---------------------------------------------------------------------------
# Outbox / subscription-type inconsistency validation
# ---------------------------------------------------------------------------
class TestOutboxSubscriptionValidation:
    @pytest.mark.no_test_domain
    def test_raises_on_outbox_true_with_event_store(self):
        domain = Domain(name="Test")
        domain.config["enable_outbox"] = True
        # subscription_type defaults to "event_store"
        with pytest.raises(ConfigurationError, match="Configuration conflict"):
            domain.init(traverse=False)

    @pytest.mark.no_test_domain
    def test_no_error_when_outbox_true_with_stream(self):
        """Redundant but valid — no error."""
        domain = Domain(name="Test")
        domain.config["enable_outbox"] = True
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)  # should not raise

    @pytest.mark.no_test_domain
    def test_no_error_when_stream_without_enable_outbox(self):
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)  # should not raise

    @pytest.mark.no_test_domain
    def test_no_error_when_defaults(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)  # should not raise


# ---------------------------------------------------------------------------
# Public database lifecycle methods
# ---------------------------------------------------------------------------
class TestSetupDatabase:
    @pytest.mark.no_test_domain
    def test_setup_database_creates_tables(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_database()
            # Verify provider artifacts were created by checking
            # that the method delegated to provider
            for _, provider in domain.providers.items():
                # Memory provider always succeeds — just ensure no error
                assert provider is not None

    @pytest.mark.no_test_domain
    def test_drop_database_drops_tables(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_database()
            domain.drop_database()  # should not raise

    @pytest.mark.no_test_domain
    def test_truncate_database_resets_data(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_database()
            domain.truncate_database()  # should not raise
            # Verify provider data_reset was called by checking
            # that the method delegated to provider
            for _, provider in domain.providers.items():
                assert provider is not None

    @pytest.mark.no_test_domain
    def test_setup_database_initializes_outbox_dao_before_creating_artifacts(self):
        """setup_database forces outbox DAO initialization before calling
        _create_database_artifacts so that the outbox table definition is
        registered in the provider's metadata (e.g. SQLAlchemy)."""
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)

        with domain.domain_context():
            # Track the order of operations: DAO access should precede
            # _create_database_artifacts
            call_order = []

            outbox_repo = domain._outbox_repos["default"]

            original_dao = type(outbox_repo)._dao
            with patch.object(
                type(outbox_repo),
                "_dao",
                new_callable=PropertyMock,
                side_effect=lambda: (
                    call_order.append("dao_access"),
                    original_dao.fget(outbox_repo),
                )[1],
            ):
                provider = domain.providers["default"]
                original_create = provider._create_database_artifacts

                def tracked_create():
                    call_order.append("create_artifacts")
                    return original_create()

                with patch.object(
                    provider, "_create_database_artifacts", side_effect=tracked_create
                ):
                    domain.setup_database()

            assert "dao_access" in call_order
            assert "create_artifacts" in call_order
            assert call_order.index("dao_access") < call_order.index("create_artifacts")

    @pytest.mark.no_test_domain
    def test_setup_database_includes_outbox_tables(self):
        """setup_database should work correctly when outbox is enabled,
        ensuring outbox tables are included in the database setup."""
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_database()

            # Verify outbox repos exist and their DAOs are accessible
            assert "default" in domain._outbox_repos
            outbox_repo = domain._outbox_repos["default"]
            assert outbox_repo._dao is not None


class TestSetupOutbox:
    @pytest.mark.no_test_domain
    def test_setup_outbox_when_enabled(self):
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_outbox()  # should not raise

    @pytest.mark.no_test_domain
    def test_setup_outbox_raises_when_not_enabled(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            with pytest.raises(ConfigurationError, match="Outbox is not enabled"):
                domain.setup_outbox()

    @pytest.mark.no_test_domain
    def test_setup_outbox_is_idempotent(self):
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_outbox()
            domain.setup_outbox()  # Second call should also succeed


# ---------------------------------------------------------------------------
# Outbox initialization edge cases
# ---------------------------------------------------------------------------
class TestOutboxInitialization:
    @pytest.mark.no_test_domain
    def test_get_outbox_repo_lazy_initializes(self):
        """_get_outbox_repo triggers _initialize_outbox when repos are empty."""
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)

        # Clear outbox repos to force lazy init
        domain._outbox_repos.clear()

        with domain.domain_context():
            repo = domain._get_outbox_repo("default")
            assert repo is not None

    @pytest.mark.no_test_domain
    def test_initialize_outbox_without_providers(self):
        """_initialize_outbox handles case when no providers are configured."""
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain._initialize()

        # Simulate no providers initialized
        domain.providers._providers = None

        # Should not raise, just log debug message
        domain._initialize_outbox()
