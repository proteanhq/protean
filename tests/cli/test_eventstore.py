"""Tests for CLI event-store commands (protean eventstore ...)."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.exceptions import NoDomainException
from protean.port.event_store import BaseEventStore, IntegrityReport, IntegrityViolation
from tests.shared import change_working_directory_to

# A wide terminal so Rich never wraps a violation token mid-string, keeping the
# human-output substring assertions stable regardless of the runner's width.
runner = CliRunner(env={"COLUMNS": "200"})


def _mock_domain_with_report(report: IntegrityReport) -> MagicMock:
    """A mock domain whose event store returns ``report`` from ``verify()``."""
    mock_domain = MagicMock()
    mock_domain.event_store.store.verify.return_value = report
    mock_domain.domain_context.return_value.__enter__.return_value = None
    mock_domain.domain_context.return_value.__exit__.return_value = False
    return mock_domain


class TestEventStoreVerify:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def _invoke(self, report: IntegrityReport, *extra_args: str):
        change_working_directory_to("test7")
        mock_domain = _mock_domain_with_report(report)
        with patch("protean.cli._helpers.derive_domain", return_value=mock_domain):
            return runner.invoke(
                app,
                ["eventstore", "verify", "--domain", "publishing7.py", *extra_args],
            )

    def test_clean_store_exits_zero(self):
        report = IntegrityReport(message_count=3, stream_count=2, violations=[])
        result = self._invoke(report)

        assert result.exit_code == 0
        assert "consistent" in result.output
        assert "3 message(s)" in result.output
        assert "2 stream(s)" in result.output
        assert "0 violations" in result.output

    def test_violations_exit_non_zero_and_name_stream_and_position(self):
        report = IntegrityReport(
            message_count=2,
            stream_count=1,
            violations=[
                IntegrityViolation(
                    kind="duplicate_message_id",
                    stream="test::user-abc",
                    position=1,
                    detail="Message id 'dup' appears more than once.",
                )
            ],
        )
        result = self._invoke(report)

        assert result.exit_code == 1
        assert "duplicate_message_id" in result.output
        assert "test::user-abc" in result.output
        assert "appears more than once" in result.output
        assert "1 violation(s)" in result.output

    def test_position_gap_violation_names_missing_position(self):
        report = IntegrityReport(
            message_count=2,
            stream_count=1,
            violations=[
                IntegrityViolation(
                    kind="position_gap",
                    stream="test::user-abc",
                    position=2,
                    detail="Stream 'test::user-abc' jumps to position 2; expected 1.",
                )
            ],
        )
        result = self._invoke(report)

        assert result.exit_code == 1
        assert "position_gap" in result.output
        # The rendered row carries both the jumped-to position and the expected one.
        assert "expected 1" in result.output

    def test_none_stream_and_position_render_as_dash(self):
        # A snapshot-ahead violation carries position=None; the human table must
        # render the empty cells as "-" without error.
        report = IntegrityReport(
            message_count=3,
            stream_count=2,
            violations=[
                IntegrityViolation(
                    kind="snapshot_ahead_of_stream",
                    stream="test::user:snapshot-abc",
                    position=None,
                    detail="Snapshot _version 5 exceeds the head position 1 of "
                    "aggregate stream 'test::user-abc'.",
                )
            ],
        )
        result = self._invoke(report)

        assert result.exit_code == 1
        assert "snapshot_ahead_of_stream" in result.output
        assert "-" in result.output

    def test_json_clean_emits_pass_envelope(self):
        report = IntegrityReport(message_count=3, stream_count=2, violations=[])
        result = self._invoke(report, "--json")

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "pass"
        assert payload["version"] == "0.1.0"
        assert payload["diagnostics"] == []
        assert payload["data"]["ok"] is True
        assert payload["data"]["message_count"] == 3
        assert payload["data"]["stream_count"] == 2
        assert payload["data"]["violations"] == []

    def test_json_data_shape_is_exactly_the_documented_keys(self):
        report = IntegrityReport(
            message_count=1,
            stream_count=1,
            violations=[
                IntegrityViolation(
                    kind="position_gap",
                    stream="test::user-abc",
                    position=2,
                    detail="gap",
                )
            ],
        )
        result = self._invoke(report, "--json")

        payload = json.loads(result.stdout)
        assert set(payload["data"].keys()) == {
            "ok",
            "message_count",
            "stream_count",
            "violations",
        }
        assert set(payload["data"]["violations"][0].keys()) == {
            "kind",
            "stream",
            "position",
            "detail",
        }

    def test_json_violations_emit_fail_envelope_and_exit_one(self):
        report = IntegrityReport(
            message_count=2,
            stream_count=1,
            violations=[
                IntegrityViolation(
                    kind="non_monotonic_global_position",
                    stream="test::user-def",
                    position=0,
                    detail="global_position 1 does not exceed the previous 1.",
                )
            ],
        )
        result = self._invoke(report, "--json")

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "fail"
        assert payload["data"]["ok"] is False
        assert len(payload["data"]["violations"]) == 1
        violation = payload["data"]["violations"][0]
        assert violation["kind"] == "non_monotonic_global_position"
        assert violation["stream"] == "test::user-def"
        assert violation["position"] == 0
        assert "does not exceed" in violation["detail"]

    def test_missing_domain_human_mode_exits_one(self):
        # Human mode mirrors every other command: a load failure aborts (exit 1),
        # the same non-zero code as a violation. Exit 2 is reserved for --json.
        change_working_directory_to("test7")
        with patch(
            "protean.cli._helpers.derive_domain",
            side_effect=NoDomainException({"error": "No domain found"}),
        ):
            result = runner.invoke(
                app, ["eventstore", "verify", "--domain", "nonexistent.py"]
            )

        assert result.exit_code == 1

    def test_missing_domain_json_emits_error_envelope_exit_two(self):
        change_working_directory_to("test7")
        with patch(
            "protean.cli._helpers.derive_domain",
            side_effect=NoDomainException({"error": "No domain found"}),
        ):
            result = runner.invoke(
                app,
                ["eventstore", "verify", "--domain", "nonexistent.py", "--json"],
            )

        assert result.exit_code == 2
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"


class TestEventStoreVerifyEndToEnd:
    """Run the command against a real domain, exercising verify -> envelope -> exit."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def _write_domain(self, tmp_path: Path) -> Path:
        (tmp_path / "domain.toml").write_text(
            '[event_store]\nprovider = "memory"\n', encoding="utf-8"
        )
        domain_file = tmp_path / "verify_domain.py"
        domain_file.write_text(
            "from protean import Domain\n\ndomain = Domain(name='VerifyDemo')\n",
            encoding="utf-8",
        )
        return domain_file

    def test_real_clean_store_human(self, tmp_path):
        domain_file = self._write_domain(tmp_path)
        os.chdir(tmp_path)

        result = runner.invoke(
            app, ["eventstore", "verify", "--domain", str(domain_file)]
        )

        assert result.exit_code == 0
        assert "consistent" in result.output

    def test_real_clean_store_json(self, tmp_path):
        domain_file = self._write_domain(tmp_path)
        os.chdir(tmp_path)

        result = runner.invoke(
            app, ["eventstore", "verify", "--domain", str(domain_file), "--json"]
        )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "pass"
        assert payload["data"]["ok"] is True


@pytest.mark.no_test_domain
def test_documented_violation_kinds_match_the_constants():
    """Every ``VERIFY_*`` kind the code can emit is listed in the CLI docs.

    Guards the hand-maintained kind list in
    ``docs/reference/cli/data/eventstore.md`` against drift as new kinds are
    added, deriving the code side from the constants rather than a second list.
    """
    repo_root = Path(__file__).resolve().parents[2]
    doc = (repo_root / "docs/reference/cli/data/eventstore.md").read_text(
        encoding="utf-8"
    )

    kinds = {
        value
        for name, value in vars(BaseEventStore).items()
        if name.startswith("VERIFY_") and isinstance(value, str)
    }
    assert kinds, "expected VERIFY_* kind constants on BaseEventStore"

    missing = sorted(kind for kind in kinds if kind not in doc)
    assert not missing, (
        "docs/reference/cli/data/eventstore.md does not mention these violation "
        f"kinds: {missing}. Add each to the kind list."
    )
