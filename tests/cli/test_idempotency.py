"""Tests for CLI idempotency commands (protean idempotency ...)."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from protean.cli import app
from protean.exceptions import NoDomainException

runner = CliRunner()


class TestIdempotencyCleanup:
    def test_cleanup_reports_deleted_markers(self):
        domain = MagicMock()
        with (
            patch("protean.cli._helpers.derive_domain", return_value=domain),
            patch(
                "protean.cli.idempotency.cleanup_processed_messages", return_value=7
            ) as cleanup,
        ):
            result = runner.invoke(app, ["idempotency", "cleanup", "--domain", "x.py"])

        assert result.exit_code == 0, result.output
        assert "Deleted 7 idempotency marker(s)" in result.output
        domain.init.assert_called_once()
        cleanup.assert_called_once_with(domain, retention_hours=None, batch_size=None)

    def test_cleanup_reports_nothing_to_do(self):
        domain = MagicMock()
        with (
            patch("protean.cli._helpers.derive_domain", return_value=domain),
            patch("protean.cli.idempotency.cleanup_processed_messages", return_value=0),
        ):
            result = runner.invoke(app, ["idempotency", "cleanup", "--domain", "x.py"])

        assert result.exit_code == 0, result.output
        assert "No idempotency markers to clean up" in result.output

    def test_cleanup_passes_retention_and_batch_through(self):
        domain = MagicMock()
        with (
            patch("protean.cli._helpers.derive_domain", return_value=domain),
            patch(
                "protean.cli.idempotency.cleanup_processed_messages", return_value=0
            ) as cleanup,
        ):
            result = runner.invoke(
                app,
                [
                    "idempotency",
                    "cleanup",
                    "--domain",
                    "x.py",
                    "--retention-hours",
                    "24",
                    "--batch-size",
                    "100",
                ],
            )

        assert result.exit_code == 0, result.output
        cleanup.assert_called_once_with(domain, retention_hours=24, batch_size=100)

    def test_cleanup_aborts_when_domain_not_found(self):
        with patch(
            "protean.cli._helpers.derive_domain",
            side_effect=NoDomainException("Could not find domain"),
        ):
            result = runner.invoke(
                app, ["idempotency", "cleanup", "--domain", "nope.py"]
            )

        assert result.exit_code != 0
        assert "Error loading Protean domain" in result.output
