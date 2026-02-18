"""Tests for CLI observatory command (protean observatory ...)."""

import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.exceptions import NoDomainException
from tests.shared import change_working_directory_to

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

runner = CliRunner()

# Observatory is lazily imported inside the CLI function body, so we patch at its source.
OBSERVATORY_CLS = "protean.server.observatory.Observatory"


class TestObservatoryCommand:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_observatory_with_invalid_domain(self):
        """Test that the observatory command fails when an invalid domain is provided."""
        args = ["observatory", "--domain", "foobar"]
        result = runner.invoke(app, args)
        assert result.exit_code != 0
        assert isinstance(result.exception, SystemExit)
        assert "Aborted" in result.output

    def test_observatory_with_valid_domain(self):
        """Test that the observatory command initializes and runs with a valid domain."""
        change_working_directory_to("test7")

        with patch(OBSERVATORY_CLS) as MockObservatory:
            mock_obs = MockObservatory.return_value

            args = ["observatory", "--domain", "publishing7.py"]
            result = runner.invoke(app, args)

            assert result.exit_code == 0
            MockObservatory.assert_called_once()
            mock_obs.run.assert_called_once_with(host="0.0.0.0", port=9000)

    def test_observatory_initializes_domain(self):
        """Test that the observatory command correctly derives and initializes the domain."""
        change_working_directory_to("test7")

        mock_domain = MagicMock()

        with patch(
            "protean.cli.observatory.derive_domain", return_value=mock_domain
        ) as mock_derive:
            with patch(OBSERVATORY_CLS) as MockObservatory:
                mock_obs = MockObservatory.return_value

                args = ["observatory", "--domain", "publishing7.py"]
                result = runner.invoke(app, args)

                assert result.exit_code == 0
                mock_derive.assert_called_once_with("publishing7.py")
                mock_domain.init.assert_called_once()
                MockObservatory.assert_called_once_with(
                    domains=[mock_domain], title="Protean Observatory"
                )
                mock_obs.run.assert_called_once()

    def test_observatory_handles_no_domain_exception(self):
        """Test that the observatory command gracefully handles NoDomainException."""
        with patch(
            "protean.cli.observatory.derive_domain",
            side_effect=NoDomainException("Domain not found"),
        ):
            args = ["observatory", "--domain", "invalid_domain.py"]
            result = runner.invoke(app, args)

            assert result.exit_code != 0
            assert (
                "Error loading Protean domain 'invalid_domain.py': Domain not found"
                in result.output
            )
            assert isinstance(result.exception, SystemExit)

    def test_observatory_with_no_domain_option(self):
        """Test that the observatory command fails when no --domain is provided."""
        args = ["observatory"]
        result = runner.invoke(app, args)
        # Typer requires --domain since it has no default
        assert result.exit_code != 0

    def test_observatory_custom_host(self):
        """Test that observatory accepts a custom host."""
        change_working_directory_to("test7")

        with patch(OBSERVATORY_CLS) as MockObservatory:
            mock_obs = MockObservatory.return_value

            args = [
                "observatory",
                "--domain",
                "publishing7.py",
                "--host",
                "127.0.0.1",
            ]
            result = runner.invoke(app, args)

            assert result.exit_code == 0
            mock_obs.run.assert_called_once_with(host="127.0.0.1", port=9000)

    def test_observatory_custom_port(self):
        """Test that observatory accepts a custom port."""
        change_working_directory_to("test7")

        with patch(OBSERVATORY_CLS) as MockObservatory:
            mock_obs = MockObservatory.return_value

            args = [
                "observatory",
                "--domain",
                "publishing7.py",
                "--port",
                "8080",
            ]
            result = runner.invoke(app, args)

            assert result.exit_code == 0
            mock_obs.run.assert_called_once_with(host="0.0.0.0", port=8080)

    def test_observatory_custom_title(self):
        """Test that observatory accepts a custom title."""
        change_working_directory_to("test7")

        mock_domain = MagicMock()

        with patch("protean.cli.observatory.derive_domain", return_value=mock_domain):
            with patch(OBSERVATORY_CLS) as MockObservatory:
                MockObservatory.return_value

                args = [
                    "observatory",
                    "--domain",
                    "publishing7.py",
                    "--title",
                    "My Dashboard",
                ]
                result = runner.invoke(app, args)

                assert result.exit_code == 0
                MockObservatory.assert_called_once_with(
                    domains=[mock_domain], title="My Dashboard"
                )

    def test_observatory_debug_mode(self):
        """Test that observatory enables debug logging when --debug is set."""
        change_working_directory_to("test7")

        with patch(OBSERVATORY_CLS):
            with patch("protean.cli.observatory.configure_logging") as mock_logging:
                args = [
                    "observatory",
                    "--domain",
                    "publishing7.py",
                    "--debug",
                ]
                result = runner.invoke(app, args)

                assert result.exit_code == 0
                mock_logging.assert_called_once_with(level="DEBUG")

    def test_observatory_default_logging_level(self):
        """Test that observatory uses INFO logging by default."""
        change_working_directory_to("test7")

        with patch(OBSERVATORY_CLS):
            with patch("protean.cli.observatory.configure_logging") as mock_logging:
                args = ["observatory", "--domain", "publishing7.py"]
                result = runner.invoke(app, args)

                assert result.exit_code == 0
                mock_logging.assert_called_once_with(level="INFO")

    def test_observatory_multiple_domains(self):
        """Test that observatory accepts multiple --domain options."""
        change_working_directory_to("test7")

        mock_domain1 = MagicMock()
        mock_domain2 = MagicMock()

        call_count = 0

        def derive_side_effect(path: str) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return mock_domain1 if call_count == 1 else mock_domain2

        with patch(
            "protean.cli.observatory.derive_domain",
            side_effect=derive_side_effect,
        ):
            with patch(OBSERVATORY_CLS) as MockObservatory:
                mock_obs = MockObservatory.return_value

                args = [
                    "observatory",
                    "--domain",
                    "publishing7.py",
                    "--domain",
                    "publishing7.py",
                ]
                result = runner.invoke(app, args)

                assert result.exit_code == 0
                mock_domain1.init.assert_called_once()
                mock_domain2.init.assert_called_once()
                MockObservatory.assert_called_once_with(
                    domains=[mock_domain1, mock_domain2],
                    title="Protean Observatory",
                )
                mock_obs.run.assert_called_once()

    def test_observatory_second_domain_invalid(self):
        """Test that observatory aborts if any domain in a multi-domain list is invalid."""
        change_working_directory_to("test7")

        mock_domain1 = MagicMock()

        def derive_side_effect(path: str) -> MagicMock:
            if path == "publishing7.py":
                return mock_domain1
            raise NoDomainException("Not found")

        with patch(
            "protean.cli.observatory.derive_domain",
            side_effect=derive_side_effect,
        ):
            args = [
                "observatory",
                "--domain",
                "publishing7.py",
                "--domain",
                "nonexistent.py",
            ]
            result = runner.invoke(app, args)

            assert result.exit_code != 0
            assert "Error loading Protean domain 'nonexistent.py'" in result.output
            assert isinstance(result.exception, SystemExit)

    def test_observatory_all_options_combined(self):
        """Test observatory with all options specified together."""
        change_working_directory_to("test7")

        mock_domain = MagicMock()

        with patch("protean.cli.observatory.derive_domain", return_value=mock_domain):
            with patch(OBSERVATORY_CLS) as MockObservatory:
                mock_obs = MockObservatory.return_value
                with patch("protean.cli.observatory.configure_logging") as mock_logging:
                    args = [
                        "observatory",
                        "--domain",
                        "publishing7.py",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "3000",
                        "--title",
                        "Custom Title",
                        "--debug",
                    ]
                    result = runner.invoke(app, args)

                    assert result.exit_code == 0
                    mock_logging.assert_called_once_with(level="DEBUG")
                    MockObservatory.assert_called_once_with(
                        domains=[mock_domain], title="Custom Title"
                    )
                    mock_obs.run.assert_called_once_with(host="127.0.0.1", port=3000)

    def test_observatory_run_exception_propagates(self):
        """Test that an exception from Observatory.run propagates correctly."""
        change_working_directory_to("test7")

        with patch(OBSERVATORY_CLS) as MockObservatory:
            mock_obs = MockObservatory.return_value
            mock_obs.run.side_effect = RuntimeError("Server startup failed")

            args = ["observatory", "--domain", "publishing7.py"]
            result = runner.invoke(app, args)

            assert result.exit_code != 0
            assert isinstance(result.exception, RuntimeError)

    def test_observatory_help(self):
        """Test that the observatory --help output shows the correct description."""
        result = runner.invoke(app, ["observatory", "--help"])
        assert result.exit_code == 0
        # Strip ANSI escape codes so assertions work in CI (Rich/Typer output)
        output = _ANSI_RE.sub("", result.output)
        assert "Observatory" in output
        assert "--domain" in output
        assert "--host" in output
        assert "--port" in output
        assert "--title" in output
        assert "--debug" in output
