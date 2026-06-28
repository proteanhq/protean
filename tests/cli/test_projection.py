"""Tests for CLI projection commands (protean projection ...)."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.exceptions import NoDomainException
from protean.server.projection_status import ProjectionStatus
from protean.utils.projection_rebuilder import RebuildResult
from tests.shared import change_working_directory_to

runner = CliRunner()


class TestProjectionRebuildSingle:
    """Tests for `protean projection rebuild --projection X`."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_rebuild_specific_projection(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.rebuild_projection.return_value = RebuildResult(
            projection_name="Balances",
            projectors_processed=1,
            categories_processed=2,
            events_dispatched=42,
        )
        # Include multiple projections so _resolve_projection iterates
        mock_record_other = MagicMock()
        mock_record_other.cls.__name__ = "OtherProjection"
        mock_record = MagicMock()
        mock_record.cls.__name__ = "Balances"
        mock_domain.registry._elements = {
            "PROJECTION": {
                "some.fqn.Other": mock_record_other,
                "some.fqn.Balances": mock_record,
            }
        }

        with patch("protean.cli.projection.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "projection",
                    "rebuild",
                    "--domain",
                    "publishing7.py",
                    "--projection",
                    "Balances",
                ],
            )
            assert result.exit_code == 0
            assert "42 events processed" in result.output
            assert "1 projector(s)" in result.output

    def test_rebuild_with_skipped_events(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.rebuild_projection.return_value = RebuildResult(
            projection_name="Balances",
            projectors_processed=1,
            categories_processed=1,
            events_dispatched=10,
            events_skipped=3,
        )
        mock_record = MagicMock()
        mock_record.cls.__name__ = "Balances"
        mock_domain.registry._elements = {
            "PROJECTION": {"some.fqn.Balances": mock_record}
        }

        with patch("protean.cli.projection.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "projection",
                    "rebuild",
                    "--domain",
                    "publishing7.py",
                    "--projection",
                    "Balances",
                ],
            )
            assert result.exit_code == 0
            assert "3 events skipped" in result.output

    def test_rebuild_with_errors(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.rebuild_projection.return_value = RebuildResult(
            projection_name="Balances",
            errors=["No projectors found for projection `Balances`"],
        )
        mock_record = MagicMock()
        mock_record.cls.__name__ = "Balances"
        mock_domain.registry._elements = {
            "PROJECTION": {"some.fqn.Balances": mock_record}
        }

        with patch("protean.cli.projection.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "projection",
                    "rebuild",
                    "--domain",
                    "publishing7.py",
                    "--projection",
                    "Balances",
                ],
            )
            assert result.exit_code != 0
            assert "Error" in result.output


class TestProjectionRebuildAll:
    """Tests for `protean projection rebuild` (all projections)."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_rebuild_all_projections(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.rebuild_all_projections.return_value = {
            "Balances": RebuildResult(projection_name="Balances", events_dispatched=20),
            "UserDirectory": RebuildResult(
                projection_name="UserDirectory", events_dispatched=10
            ),
        }

        with patch("protean.cli.projection.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                ["projection", "rebuild", "--domain", "publishing7.py"],
            )
            assert result.exit_code == 0
            assert "Balances: 20 events processed" in result.output
            assert "UserDirectory: 10 events processed" in result.output
            assert "30 total events processed" in result.output

    def test_rebuild_all_no_projections(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.rebuild_all_projections.return_value = {}

        with patch("protean.cli.projection.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                ["projection", "rebuild", "--domain", "publishing7.py"],
            )
            assert result.exit_code == 0
            assert "No projections found" in result.output

    def test_rebuild_all_with_errors(self):
        """When rebuild_all returns a result with errors, the error is shown."""
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.rebuild_all_projections.return_value = {
            "Balances": RebuildResult(projection_name="Balances", events_dispatched=20),
            "Broken": RebuildResult(
                projection_name="Broken",
                errors=["No projectors found for projection `Broken`"],
            ),
        }

        with patch("protean.cli.projection.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                ["projection", "rebuild", "--domain", "publishing7.py"],
            )
            assert result.exit_code == 0
            assert "Balances: 20 events processed" in result.output
            assert "Broken: ERROR" in result.output


class TestProjectionRebuildEdgeCases:
    """Tests for error handling and edge cases."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_unknown_projection(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.registry._elements = {"PROJECTION": {}}

        with patch("protean.cli.projection.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "projection",
                    "rebuild",
                    "--domain",
                    "publishing7.py",
                    "--projection",
                    "NonExistent",
                ],
            )
            assert result.exit_code != 0
            assert "Projection 'NonExistent' not found" in result.output

    def test_invalid_domain(self):
        with patch(
            "protean.cli.projection.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(
                app, ["projection", "rebuild", "--domain", "invalid.py"]
            )
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output


class TestProjectionStatus:
    """Tests for `protean projection status`."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    @staticmethod
    def _status(
        projection_name="Balances",
        projectors=("BalancesProjector",),
        last_updated="2026-06-27T12:00:00+00:00",
        staleness_seconds=90.0,
        lag=5,
        row_count=3,
        status="lagging",
    ):
        return ProjectionStatus(
            projection_name=projection_name,
            projectors=list(projectors),
            last_updated=last_updated,
            staleness_seconds=staleness_seconds,
            lag=lag,
            row_count=row_count,
            status=status,
        )

    def _run(self, statuses, *extra):
        change_working_directory_to("test7")
        mock_domain = MagicMock()
        mock_domain.name = "test-domain"
        with (
            patch("protean.cli.projection.derive_domain", return_value=mock_domain),
            patch(
                "protean.server.projection_status.collect_projection_statuses",
                return_value=statuses,
            ),
        ):
            return runner.invoke(
                app,
                ["projection", "status", "--domain", "publishing7.py", *extra],
            )

    def test_shows_table(self):
        result = self._run([self._status(), self._status("Tokens", status="ok", lag=0)])
        assert result.exit_code == 0
        assert "Balances" in result.output
        assert "2 projection(s)" in result.output
        assert "1 lagging" in result.output
        assert "1 ok" in result.output

    def test_empty_message(self):
        result = self._run([])
        assert result.exit_code == 0
        assert "No projections found" in result.output

    def test_json_output(self):
        result = self._run([self._status()], "--json")
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        assert parsed[0]["projection_name"] == "Balances"
        assert parsed[0]["staleness_seconds"] == 90.0

    def test_json_output_empty(self):
        result = self._run([], "--json")
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def test_renders_dashes_for_unknown(self):
        result = self._run(
            [
                self._status(
                    status="unknown",
                    lag=None,
                    staleness_seconds=None,
                    row_count=None,
                    last_updated=None,
                    projectors=(),
                )
            ]
        )
        assert result.exit_code == 0
        assert "1 unknown" in result.output

    def test_domain_loading_error(self):
        change_working_directory_to("test7")
        with patch(
            "protean.cli.projection.derive_domain",
            side_effect=NoDomainException("not found"),
        ):
            result = runner.invoke(
                app, ["projection", "status", "--domain", "nonexistent.py"]
            )
        assert result.exit_code != 0
