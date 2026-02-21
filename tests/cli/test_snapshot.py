"""Tests for CLI snapshot commands (protean snapshot ...)."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.exceptions import (
    IncorrectUsageError,
    NoDomainException,
    ObjectNotFoundError,
)
from tests.shared import change_working_directory_to

runner = CliRunner()


class TestSnapshotCreateSingle:
    """Tests for `protean snapshot create --aggregate X --identifier Y`."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_single_aggregate_instance(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.create_snapshot.return_value = True
        # Set up registry with multiple aggregates so _resolve_aggregate
        # iterates past non-matching records before finding the target.
        mock_other = MagicMock()
        mock_other.cls.__name__ = "Order"
        mock_record = MagicMock()
        mock_record.cls.__name__ = "User"
        mock_domain.registry._elements = {
            "AGGREGATE": {
                "some.fqn.Order": mock_other,
                "some.fqn.User": mock_record,
            }
        }

        with patch("protean.cli.snapshot.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "snapshot",
                    "create",
                    "--domain",
                    "publishing7.py",
                    "--aggregate",
                    "User",
                    "--identifier",
                    "abc123",
                ],
            )
            assert result.exit_code == 0
            assert "Snapshot created for User with identifier abc123" in result.output
            mock_domain.create_snapshot.assert_called_once_with(
                mock_record.cls, "abc123"
            )

    def test_nonexistent_aggregate_instance(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.create_snapshot.side_effect = ObjectNotFoundError("Not found")
        mock_record = MagicMock()
        mock_record.cls.__name__ = "User"
        mock_domain.registry._elements = {"AGGREGATE": {"some.fqn.User": mock_record}}

        with patch("protean.cli.snapshot.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "snapshot",
                    "create",
                    "--domain",
                    "publishing7.py",
                    "--aggregate",
                    "User",
                    "--identifier",
                    "nonexistent",
                ],
            )
            assert result.exit_code != 0
            assert "Error" in result.output

    def test_non_es_aggregate_for_single(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.create_snapshot.side_effect = IncorrectUsageError(
            "not an event-sourced aggregate"
        )
        mock_record = MagicMock()
        mock_record.cls.__name__ = "Order"
        mock_domain.registry._elements = {"AGGREGATE": {"some.fqn.Order": mock_record}}

        with patch("protean.cli.snapshot.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "snapshot",
                    "create",
                    "--domain",
                    "publishing7.py",
                    "--aggregate",
                    "Order",
                    "--identifier",
                    "abc123",
                ],
            )
            assert result.exit_code != 0
            assert "not an event-sourced aggregate" in result.output


class TestSnapshotCreateBulk:
    """Tests for `protean snapshot create --aggregate X` (all instances)."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_all_instances_of_aggregate(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.create_snapshots.return_value = 5
        mock_record = MagicMock()
        mock_record.cls.__name__ = "User"
        mock_domain.registry._elements = {"AGGREGATE": {"some.fqn.User": mock_record}}

        with patch("protean.cli.snapshot.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "snapshot",
                    "create",
                    "--domain",
                    "publishing7.py",
                    "--aggregate",
                    "User",
                ],
            )
            assert result.exit_code == 0
            assert "Created 5 snapshot(s) for User" in result.output

    def test_non_es_aggregate_for_bulk(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.create_snapshots.side_effect = IncorrectUsageError(
            "not an event-sourced aggregate"
        )
        mock_record = MagicMock()
        mock_record.cls.__name__ = "Order"
        mock_domain.registry._elements = {"AGGREGATE": {"some.fqn.Order": mock_record}}

        with patch("protean.cli.snapshot.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "snapshot",
                    "create",
                    "--domain",
                    "publishing7.py",
                    "--aggregate",
                    "Order",
                ],
            )
            assert result.exit_code != 0
            assert "not an event-sourced aggregate" in result.output


class TestSnapshotCreateAll:
    """Tests for `protean snapshot create` (all ES aggregates)."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_all_es_aggregates(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.create_all_snapshots.return_value = {"User": 3, "Order": 2}

        with patch("protean.cli.snapshot.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                ["snapshot", "create", "--domain", "publishing7.py"],
            )
            assert result.exit_code == 0
            assert "User: 3 snapshot(s)" in result.output
            assert "Order: 2 snapshot(s)" in result.output
            assert "Created 5 snapshot(s) across 2 aggregate(s)" in result.output

    def test_no_es_aggregates_in_domain(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.create_all_snapshots.return_value = {}

        with patch("protean.cli.snapshot.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app, ["snapshot", "create", "--domain", "publishing7.py"]
            )
            assert result.exit_code == 0
            assert "No event-sourced aggregates found" in result.output


class TestSnapshotCreateEdgeCases:
    """Tests for error handling and edge cases."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_identifier_without_aggregate_aborts(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()

        with patch("protean.cli.snapshot.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "snapshot",
                    "create",
                    "--domain",
                    "publishing7.py",
                    "--identifier",
                    "abc123",
                ],
            )
            assert result.exit_code != 0
            assert "--identifier requires --aggregate" in result.output

    def test_invalid_domain_aborts(self):
        with patch(
            "protean.cli.snapshot.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(
                app, ["snapshot", "create", "--domain", "invalid.py"]
            )
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output

    def test_aggregate_not_in_registry(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.registry._elements = {"AGGREGATE": {}}

        with patch("protean.cli.snapshot.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "snapshot",
                    "create",
                    "--domain",
                    "publishing7.py",
                    "--aggregate",
                    "NonExistent",
                ],
            )
            assert result.exit_code != 0
            assert "Aggregate 'NonExistent' not found" in result.output

    def test_aggregate_not_in_registry_with_identifier(self):
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.registry._elements = {"AGGREGATE": {}}

        with patch("protean.cli.snapshot.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "snapshot",
                    "create",
                    "--domain",
                    "publishing7.py",
                    "--aggregate",
                    "NonExistent",
                    "--identifier",
                    "abc123",
                ],
            )
            assert result.exit_code != 0
            assert "Aggregate 'NonExistent' not found" in result.output
