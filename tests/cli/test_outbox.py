"""Tests for CLI outbox commands (protean outbox ...)."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from protean.cli import app
from protean.exceptions import NoDomainException

runner = CliRunner()


def _mock_domain(has_outbox: bool = True) -> MagicMock:
    """A domain whose ``load_domain`` machinery is fully stubbed out."""
    domain = MagicMock()
    domain.has_outbox = has_outbox
    return domain


class TestOutboxReconcile:
    def test_reconcile_reports_recreated_rows(self):
        domain = _mock_domain()
        with (
            patch("protean.cli._helpers.derive_domain", return_value=domain),
            patch("protean.cli.outbox.reconcile_outbox", return_value=3) as reconcile,
        ):
            result = runner.invoke(app, ["outbox", "reconcile", "--domain", "x.py"])

        assert result.exit_code == 0, result.output
        assert "Reconciled 3 outbox row(s)" in result.output
        # The command must initialize the domain and delegate to the reconciler.
        domain.init.assert_called_once()
        reconcile.assert_called_once_with(domain, provider_name="default", limit=1000)

    def test_reconcile_reports_a_clean_outbox(self):
        domain = _mock_domain()
        with (
            patch("protean.cli._helpers.derive_domain", return_value=domain),
            patch("protean.cli.outbox.reconcile_outbox", return_value=0),
        ):
            result = runner.invoke(app, ["outbox", "reconcile", "--domain", "x.py"])

        assert result.exit_code == 0, result.output
        assert "Nothing to reconcile" in result.output

    def test_reconcile_passes_provider_and_limit_through(self):
        domain = _mock_domain()
        with (
            patch("protean.cli._helpers.derive_domain", return_value=domain),
            patch("protean.cli.outbox.reconcile_outbox", return_value=0) as reconcile,
        ):
            result = runner.invoke(
                app,
                [
                    "outbox",
                    "reconcile",
                    "--domain",
                    "x.py",
                    "--provider",
                    "secondary",
                    "--limit",
                    "50",
                ],
            )

        assert result.exit_code == 0, result.output
        reconcile.assert_called_once_with(domain, provider_name="secondary", limit=50)

    def test_reconcile_aborts_when_outbox_disabled(self):
        domain = _mock_domain(has_outbox=False)
        with (
            patch("protean.cli._helpers.derive_domain", return_value=domain),
            patch("protean.cli.outbox.reconcile_outbox") as reconcile,
        ):
            result = runner.invoke(app, ["outbox", "reconcile", "--domain", "x.py"])

        assert result.exit_code != 0
        assert "Outbox is not enabled" in result.output
        reconcile.assert_not_called()

    def test_reconcile_aborts_when_domain_not_found(self):
        with patch(
            "protean.cli._helpers.derive_domain",
            side_effect=NoDomainException("Could not find domain"),
        ):
            result = runner.invoke(app, ["outbox", "reconcile", "--domain", "nope.py"])

        assert result.exit_code != 0
        assert "Error loading Protean domain" in result.output
