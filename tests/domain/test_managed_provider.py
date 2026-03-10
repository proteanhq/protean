"""Tests for the provider `managed` flag.

When a provider has ``managed = false`` in its connection info, the framework
should skip it during database setup, truncation, drop, outbox initialization,
and outbox setup — but still register the provider normally.
"""

from unittest.mock import patch

import pytest

from protean.domain import Domain


# ---------------------------------------------------------------------------
# BaseProvider.managed attribute
# ---------------------------------------------------------------------------
class TestProviderManagedFlag:
    @pytest.mark.no_test_domain
    def test_managed_defaults_to_true(self):
        """Providers are managed by default when no explicit flag is set."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            provider = domain.providers["default"]
            assert provider.managed is True

    @pytest.mark.no_test_domain
    def test_managed_false_from_config(self):
        """A provider with ``managed: false`` in conn_info is marked unmanaged."""
        domain = Domain(name="Test")
        domain.config["databases"]["unmanaged"] = {
            "provider": "memory",
            "managed": False,
        }
        domain.init(traverse=False)

        with domain.domain_context():
            assert domain.providers["default"].managed is True
            assert domain.providers["unmanaged"].managed is False

    @pytest.mark.no_test_domain
    def test_managed_true_explicit(self):
        """Explicitly setting ``managed: true`` works the same as the default."""
        domain = Domain(name="Test")
        domain.config["databases"]["explicit"] = {
            "provider": "memory",
            "managed": True,
        }
        domain.init(traverse=False)

        with domain.domain_context():
            assert domain.providers["explicit"].managed is True


# ---------------------------------------------------------------------------
# InfrastructureManager.setup_database
# ---------------------------------------------------------------------------
class TestSetupDatabaseSkipsUnmanaged:
    @pytest.mark.no_test_domain
    def test_setup_database_skips_unmanaged_provider(self):
        """setup_database should not call _create_database_artifacts on unmanaged providers."""
        domain = Domain(name="Test")
        domain.config["databases"]["unmanaged"] = {
            "provider": "memory",
            "managed": False,
        }
        domain.init(traverse=False)

        with domain.domain_context():
            unmanaged = domain.providers["unmanaged"]
            with patch.object(unmanaged, "_create_database_artifacts") as mock_create:
                domain.setup_database()
                mock_create.assert_not_called()

    @pytest.mark.no_test_domain
    def test_setup_database_calls_managed_provider(self):
        """setup_database should call _create_database_artifacts on managed providers."""
        domain = Domain(name="Test")
        domain.config["databases"]["secondary"] = {
            "provider": "memory",
            "managed": True,
        }
        domain.init(traverse=False)

        with domain.domain_context():
            managed = domain.providers["secondary"]
            with patch.object(managed, "_create_database_artifacts") as mock_create:
                domain.setup_database()
                mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# InfrastructureManager.drop_database
# ---------------------------------------------------------------------------
class TestDropDatabaseSkipsUnmanaged:
    @pytest.mark.no_test_domain
    def test_drop_database_skips_unmanaged_provider(self):
        """drop_database should not call _drop_database_artifacts on unmanaged providers."""
        domain = Domain(name="Test")
        domain.config["databases"]["unmanaged"] = {
            "provider": "memory",
            "managed": False,
        }
        domain.init(traverse=False)

        with domain.domain_context():
            unmanaged = domain.providers["unmanaged"]
            with patch.object(unmanaged, "_drop_database_artifacts") as mock_drop:
                domain.drop_database()
                mock_drop.assert_not_called()

    @pytest.mark.no_test_domain
    def test_drop_database_calls_managed_provider(self):
        """drop_database should call _drop_database_artifacts on managed providers."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            managed = domain.providers["default"]
            with patch.object(managed, "_drop_database_artifacts") as mock_drop:
                domain.drop_database()
                mock_drop.assert_called_once()


# ---------------------------------------------------------------------------
# InfrastructureManager.truncate_database
# ---------------------------------------------------------------------------
class TestTruncateDatabaseSkipsUnmanaged:
    @pytest.mark.no_test_domain
    def test_truncate_database_skips_unmanaged_provider(self):
        """truncate_database should not call _data_reset on unmanaged providers."""
        domain = Domain(name="Test")
        domain.config["databases"]["unmanaged"] = {
            "provider": "memory",
            "managed": False,
        }
        domain.init(traverse=False)

        with domain.domain_context():
            unmanaged = domain.providers["unmanaged"]
            with patch.object(unmanaged, "_data_reset") as mock_reset:
                # Also patch _create_database_artifacts to avoid side effects
                with patch.object(
                    unmanaged, "_create_database_artifacts"
                ) as mock_create:
                    domain.truncate_database()
                    mock_reset.assert_not_called()
                    mock_create.assert_not_called()

    @pytest.mark.no_test_domain
    def test_truncate_database_calls_managed_provider(self):
        """truncate_database should call _data_reset on managed providers."""
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            managed = domain.providers["default"]
            with patch.object(managed, "_data_reset") as mock_reset:
                domain.truncate_database()
                mock_reset.assert_called_once()


# ---------------------------------------------------------------------------
# InfrastructureManager.initialize_outbox
# ---------------------------------------------------------------------------
class TestOutboxInitializationSkipsUnmanaged:
    @pytest.mark.no_test_domain
    def test_outbox_not_created_for_unmanaged_provider(self):
        """Outbox repos should not be created for unmanaged providers."""
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.config["databases"]["unmanaged"] = {
            "provider": "memory",
            "managed": False,
        }
        domain.init(traverse=False)

        with domain.domain_context():
            # Outbox repos should only exist for managed providers
            assert "default" in domain._outbox_repos
            assert "unmanaged" not in domain._outbox_repos

    @pytest.mark.no_test_domain
    def test_outbox_created_for_managed_provider(self):
        """Outbox repos should be created for managed providers."""
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.config["databases"]["secondary"] = {
            "provider": "memory",
            "managed": True,
        }
        domain.init(traverse=False)

        with domain.domain_context():
            assert "default" in domain._outbox_repos
            assert "secondary" in domain._outbox_repos


# ---------------------------------------------------------------------------
# InfrastructureManager.setup_outbox
# ---------------------------------------------------------------------------
class TestSetupOutboxSkipsUnmanaged:
    @pytest.mark.no_test_domain
    def test_setup_outbox_skips_unmanaged_provider(self):
        """setup_outbox should not create artifacts for unmanaged providers."""
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.config["databases"]["unmanaged"] = {
            "provider": "memory",
            "managed": False,
        }
        domain.init(traverse=False)

        with domain.domain_context():
            unmanaged = domain.providers["unmanaged"]
            with patch.object(unmanaged, "_create_database_artifacts") as mock_create:
                domain.setup_outbox()
                mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# Mixed managed/unmanaged: only managed providers participate
# ---------------------------------------------------------------------------
class TestMixedManagedUnmanaged:
    @pytest.mark.no_test_domain
    def test_only_managed_providers_in_full_lifecycle(self):
        """Full lifecycle (setup → truncate → drop) only touches managed providers."""
        domain = Domain(name="Test")
        domain.config["databases"]["managed_extra"] = {
            "provider": "memory",
            "managed": True,
        }
        domain.config["databases"]["unmanaged_extra"] = {
            "provider": "memory",
            "managed": False,
        }
        domain.init(traverse=False)

        with domain.domain_context():
            unmanaged = domain.providers["unmanaged_extra"]

            with (
                patch.object(unmanaged, "_create_database_artifacts") as mock_create,
                patch.object(unmanaged, "_data_reset") as mock_reset,
                patch.object(unmanaged, "_drop_database_artifacts") as mock_drop,
            ):
                domain.setup_database()
                domain.truncate_database()
                domain.drop_database()

                mock_create.assert_not_called()
                mock_reset.assert_not_called()
                mock_drop.assert_not_called()
