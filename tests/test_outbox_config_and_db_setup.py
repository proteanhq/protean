"""Tests for outbox/subscription-type configuration, database lifecycle API, and CLI db commands."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.domain import Domain
from protean.exceptions import ConfigurationError, NoDomainException
from tests.shared import change_working_directory_to

runner = CliRunner()


# ---------------------------------------------------------------------------
# has_outbox property
# ---------------------------------------------------------------------------
class TestHasOutboxProperty:
    def test_returns_true_when_subscription_type_is_stream(self):
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        assert domain.has_outbox is True

    def test_returns_true_when_enable_outbox_is_true_with_stream(self):
        """Backward compat: enable_outbox=True + stream is redundant but valid."""
        domain = Domain(name="Test")
        domain.config["enable_outbox"] = True
        domain.config["server"]["default_subscription_type"] = "stream"
        assert domain.has_outbox is True

    def test_returns_false_when_defaults(self):
        domain = Domain(name="Test")
        assert domain.has_outbox is False

    def test_returns_false_when_event_store_explicit(self):
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "event_store"
        assert domain.has_outbox is False


# ---------------------------------------------------------------------------
# Inconsistency validation
# ---------------------------------------------------------------------------
class TestOutboxSubscriptionValidation:
    def test_raises_on_outbox_true_with_event_store(self):
        domain = Domain(name="Test")
        domain.config["enable_outbox"] = True
        # subscription_type defaults to "event_store"
        with pytest.raises(ConfigurationError, match="Configuration conflict"):
            domain.init(traverse=False)

    def test_no_error_when_outbox_true_with_stream(self):
        """Redundant but valid — no error."""
        domain = Domain(name="Test")
        domain.config["enable_outbox"] = True
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)  # should not raise

    def test_no_error_when_stream_without_enable_outbox(self):
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)  # should not raise

    def test_no_error_when_defaults(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)  # should not raise


# ---------------------------------------------------------------------------
# Public database setup methods
# ---------------------------------------------------------------------------
class TestSetupDatabase:
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

    def test_drop_database_drops_tables(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_database()
            domain.drop_database()  # should not raise

    def test_setup_outbox_when_enabled(self):
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_outbox()  # should not raise

    def test_setup_outbox_raises_when_not_enabled(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            with pytest.raises(ConfigurationError, match="Outbox is not enabled"):
                domain.setup_outbox()

    def test_setup_outbox_is_idempotent(self):
        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_outbox()
            domain.setup_outbox()  # Second call should also succeed


# ---------------------------------------------------------------------------
# DomainFixture uses public API
# ---------------------------------------------------------------------------
class TestDomainFixture:
    def test_setup_delegates_to_setup_database(self):
        from protean.integrations.pytest.testbed import DomainFixture

        domain = Domain(name="Test")
        fixture = DomainFixture(domain)

        with patch.object(domain, "setup_database") as mock_setup:
            with patch.object(domain, "init"):
                # setup_database requires domain_context, so we need to patch
                # domain_context as well
                fixture.domain.init = MagicMock()
                fixture.domain.setup_database = mock_setup
                fixture.domain.domain_context = MagicMock()
                fixture.domain.domain_context.return_value.__enter__ = MagicMock()
                fixture.domain.domain_context.return_value.__exit__ = MagicMock(
                    return_value=False
                )

                fixture.setup()
                mock_setup.assert_called_once()

    def test_teardown_delegates_to_drop_database(self):
        from protean.integrations.pytest.testbed import DomainFixture

        domain = Domain(name="Test")
        fixture = DomainFixture(domain)

        with patch.object(domain, "drop_database") as mock_drop:
            fixture.domain.drop_database = mock_drop
            fixture.domain.domain_context = MagicMock()
            fixture.domain.domain_context.return_value.__enter__ = MagicMock()
            fixture.domain.domain_context.return_value.__exit__ = MagicMock(
                return_value=False
            )

            fixture.teardown()
            mock_drop.assert_called_once()


# ---------------------------------------------------------------------------
# CLI db commands
# ---------------------------------------------------------------------------
class TestCLIDbCommands:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_db_setup_creates_tables(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.has_outbox = False

        with patch("protean.cli.database.derive_domain", return_value=mock_domain):
            result = runner.invoke(app, ["db", "setup", "--domain", "publishing7.py"])
            assert result.exit_code == 0
            assert "Database tables created successfully" in result.output
            mock_domain.init.assert_called_once()
            mock_domain.setup_database.assert_called_once()

    def test_db_setup_with_invalid_domain(self):
        with patch(
            "protean.cli.database.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(app, ["db", "setup", "--domain", "invalid.py"])
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output

    def test_db_drop_with_confirmation(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.has_outbox = False

        with patch("protean.cli.database.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app, ["db", "drop", "--domain", "publishing7.py", "--yes"]
            )
            assert result.exit_code == 0
            assert "Database tables dropped successfully" in result.output
            mock_domain.drop_database.assert_called_once()

    def test_db_drop_aborts_without_confirmation(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()

        with patch("protean.cli.database.derive_domain", return_value=mock_domain):
            # Send "n" to the confirmation prompt
            result = runner.invoke(
                app, ["db", "drop", "--domain", "publishing7.py"], input="n\n"
            )
            assert result.exit_code != 0
            mock_domain.drop_database.assert_not_called()

    def test_db_drop_with_invalid_domain(self):
        with patch(
            "protean.cli.database.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(
                app, ["db", "drop", "--domain", "invalid.py", "--yes"]
            )
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output

    def test_db_setup_outbox(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.has_outbox = True

        with patch("protean.cli.database.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app, ["db", "setup-outbox", "--domain", "publishing7.py"]
            )
            assert result.exit_code == 0
            assert "Outbox tables created successfully" in result.output
            mock_domain.setup_outbox.assert_called_once()

    def test_db_setup_outbox_with_invalid_domain(self):
        with patch(
            "protean.cli.database.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(
                app, ["db", "setup-outbox", "--domain", "invalid.py"]
            )
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output

    def test_db_setup_outbox_when_not_enabled(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.setup_outbox.side_effect = ConfigurationError(
            "Outbox is not enabled."
        )

        with patch("protean.cli.database.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app, ["db", "setup-outbox", "--domain", "publishing7.py"]
            )
            assert result.exit_code != 0
            assert "Error" in result.output


# ---------------------------------------------------------------------------
# Engine startup validation
# ---------------------------------------------------------------------------
class TestEngineOutboxValidation:
    def test_engine_starts_normally_without_outbox(self):
        """Engine should start when outbox is not enabled (event_store mode)."""
        from protean.server.engine import Engine

        domain = Domain(name="Test")
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            assert len(engine._outbox_processors) == 0

    def test_engine_starts_normally_with_outbox_and_tables(self):
        """Engine should start when outbox is enabled and repos are initialised."""
        from protean.server.engine import Engine

        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)

        with domain.domain_context():
            domain.setup_database()
            engine = Engine(domain, test_mode=True)
            assert len(engine._outbox_processors) > 0

    def test_engine_raises_when_outbox_table_missing(self):
        """Engine should raise ConfigurationError when outbox DAO is not accessible."""
        from protean.server.engine import Engine

        domain = Domain(name="Test")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)

        with domain.domain_context():
            # Sabotage the outbox repo to simulate missing table
            for provider_name, outbox_repo in domain._outbox_repos.items():
                original_dao = type(outbox_repo)._dao
                type(outbox_repo)._dao = property(
                    lambda self: (_ for _ in ()).throw(Exception("table not found"))
                )

                try:
                    with pytest.raises(
                        ConfigurationError,
                        match="Outbox table not found",
                    ):
                        Engine(domain, test_mode=True)
                finally:
                    type(outbox_repo)._dao = original_dao
