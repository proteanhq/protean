"""Tests for CLI database lifecycle commands (protean db ...)."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.exceptions import ConfigurationError, NoDomainException
from tests.shared import change_working_directory_to

runner = CliRunner()


class TestDbSetup:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_creates_tables(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.has_outbox = False

        with patch("protean.cli.database.derive_domain", return_value=mock_domain):
            result = runner.invoke(app, ["db", "setup", "--domain", "publishing7.py"])
            assert result.exit_code == 0
            assert "Database tables created successfully" in result.output
            mock_domain.init.assert_called_once()
            mock_domain.setup_database.assert_called_once()

    def test_with_invalid_domain(self):
        with patch(
            "protean.cli.database.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(app, ["db", "setup", "--domain", "invalid.py"])
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output


class TestDbDrop:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_with_confirmation(self):
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

    def test_aborts_without_confirmation(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()

        with patch("protean.cli.database.derive_domain", return_value=mock_domain):
            # Send "n" to the confirmation prompt
            result = runner.invoke(
                app, ["db", "drop", "--domain", "publishing7.py"], input="n\n"
            )
            assert result.exit_code != 0
            mock_domain.drop_database.assert_not_called()

    def test_with_invalid_domain(self):
        with patch(
            "protean.cli.database.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(
                app, ["db", "drop", "--domain", "invalid.py", "--yes"]
            )
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output


class TestDbTruncate:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_with_confirmation(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()

        with patch("protean.cli.database.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app, ["db", "truncate", "--domain", "publishing7.py", "--yes"]
            )
            assert result.exit_code == 0
            assert "All table data deleted successfully" in result.output
            mock_domain.truncate_database.assert_called_once()

    def test_aborts_without_confirmation(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()

        with patch("protean.cli.database.derive_domain", return_value=mock_domain):
            # Send "n" to the confirmation prompt
            result = runner.invoke(
                app, ["db", "truncate", "--domain", "publishing7.py"], input="n\n"
            )
            assert result.exit_code != 0
            mock_domain.truncate_database.assert_not_called()

    def test_with_invalid_domain(self):
        with patch(
            "protean.cli.database.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(
                app, ["db", "truncate", "--domain", "invalid.py", "--yes"]
            )
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output


class TestDbSetupOutbox:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_creates_outbox_tables(self):
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

    def test_with_invalid_domain(self):
        with patch(
            "protean.cli.database.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(
                app, ["db", "setup-outbox", "--domain", "invalid.py"]
            )
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output

    def test_when_outbox_not_enabled(self):
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
