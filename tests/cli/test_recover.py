"""Tests for the CLI recover command (protean recover --verify-checkpoints)."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.exceptions import NoDomainException
from protean.server.subscription_status import (
    RecoveryCheckpointStatus,
    SubscriptionStatus,
)
from tests.cli._envelope import assert_envelope
from tests.shared import change_working_directory_to

# These stub ``derive_domain``/``collect_subscription_statuses`` and never touch
# a real domain; the autouse ``test_domain`` fixture would build one per test for
# nothing.
pytestmark = pytest.mark.no_test_domain

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_status(
    handler_name: str = "OrderHandler",
    subscription_type: str = "event_store",
    stream_category: str = "order",
    current_position: str | None = "10",
    head_position: str | None = "10",
) -> SubscriptionStatus:
    return SubscriptionStatus(
        name=f"sub-{handler_name.lower()}",
        handler_name=handler_name,
        subscription_type=subscription_type,
        stream_category=stream_category,
        lag=0,
        pending=0,
        current_position=current_position,
        head_position=head_position,
        status="ok",
        consumer_count=0,
        dlq_depth=0,
    )


def _mock_domain_for_cli() -> MagicMock:
    mock_domain = MagicMock()
    mock_domain.name = "test-domain"
    return mock_domain


def _make_recovery_finding(
    handler_name: str = "OrderProjector",
    stream_category: str = "order",
    stale_positions: list[int] | None = None,
    head_position: int = 5,
    verdict: str = "stale",
) -> RecoveryCheckpointStatus:
    positions = [10, 12] if stale_positions is None else stale_positions
    return RecoveryCheckpointStatus(
        name=f"sub-{handler_name.lower()}",
        handler_name=handler_name,
        stream_category=stream_category,
        recovery_checkpoint_stream=(
            f"recovery-checkpoint-{handler_name}-{stream_category}"
        ),
        head_position=head_position,
        verdict=verdict,
        stale_positions=positions,
        unresolved={
            p: {"retry_count": 1, "stream_name": None, "stream_position": None}
            for p in positions
        },
        watermark=0,
    )


def _make_recovery_unknown(
    handler_name: str = "OrderProjector",
    stream_category: str = "order",
    head_position: int = 5,
) -> RecoveryCheckpointStatus:
    return RecoveryCheckpointStatus(
        name=f"sub-{handler_name.lower()}",
        handler_name=handler_name,
        stream_category=stream_category,
        recovery_checkpoint_stream=(
            f"recovery-checkpoint-{handler_name}-{stream_category}"
        ),
        head_position=head_position,
        verdict="unknown",
        stale_positions=[],
        unresolved={},
        watermark=0,
    )


def _invoke(statuses, extra_args=None, recovery_findings=None):
    mock_domain = _mock_domain_for_cli()
    with (
        patch("protean.cli._helpers.derive_domain", return_value=mock_domain),
        patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=statuses,
        ),
        patch(
            "protean.server.subscription_status.collect_recovery_checkpoint_statuses",
            return_value=recovery_findings or [],
        ),
    ):
        return runner.invoke(
            app,
            ["recover", "--verify-checkpoints", "--domain", "publishing7.py"]
            + (extra_args or []),
        )


class TestRecoverVerifyCheckpoints:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_beyond_head_is_flagged_and_named(self):
        """Criterion 1: a checkpoint past the head fails, naming the subscription
        and both positions."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("OrderHandler", current_position="10", head_position="5"),
        ]
        result = _invoke(statuses)

        assert result.exit_code == 1
        assert "beyond head" in result.output
        # Pin the values to their columns (Checkpoint before Head before
        # Verdict), so a swapped-column bug would fail rather than pass on the
        # bare presence of the digits.
        row = next(
            line for line in result.output.splitlines() if "OrderHandler" in line
        )
        assert row.index("10") < row.index("5") < row.index("beyond head")

    def test_all_consistent_exits_zero(self):
        """Criterion 2: every checkpoint at or behind the head exits 0."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("A", current_position="5", head_position="5"),
            _make_status("B", current_position="3", head_position="9"),
        ]
        result = _invoke(statuses)

        assert result.exit_code == 0
        assert "consistent" in result.output

    def test_fresh_subscription_is_consistent(self):
        """Criterion 4: a fresh checkpoint (-1) against a real head reads
        consistent, exit 0."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("Fresh", current_position="-1", head_position="7"),
        ]
        result = _invoke(statuses)

        assert result.exit_code == 0
        assert "beyond head" not in result.output

    def test_non_event_store_is_ignored(self):
        """Negative test for the event-store filter: a broker subscription whose
        numeric current is past head is never flagged."""
        change_working_directory_to("test7")

        statuses = [
            _make_status(
                "BrokerHandler",
                subscription_type="broker",
                current_position="99",
                head_position="1",
            ),
        ]
        result = _invoke(statuses)

        assert result.exit_code == 0
        assert "No event-store subscriptions found" in result.output
        assert "BrokerHandler" not in result.output

    def test_unknown_status_is_skipped_not_flagged(self):
        """An unreachable store (None positions) is not a violation and does not
        crash the int comparison."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("Unknown", current_position=None, head_position=None),
        ]
        result = _invoke(statuses)

        assert result.exit_code == 0
        assert "unknown" in result.output
        assert "beyond head" not in result.output
        # An unverified row is not "consistent"; the summary must say so.
        assert "could not be verified" in result.output
        assert "All " not in result.output

    def test_non_numeric_position_does_not_crash(self):
        """A foreign store can hold a non-numeric position ("5.0", "abc"); it is
        treated as unknown, not a crash or a false verdict."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("Floaty", current_position="5.0", head_position="3"),
            _make_status("Texty", current_position="abc", head_position="3"),
        ]
        result = _invoke(statuses)

        assert result.exit_code == 0
        assert "beyond head" not in result.output
        assert "could not be verified" in result.output
        # The rows here are unknown because the positions do not parse, not
        # because the store is offline, so the summary must not name only one
        # cause. Rich wraps the line, so compare on collapsed whitespace.
        collapsed = " ".join(result.output.split())
        assert "the position is not a number" in collapsed

    def test_mixed_beyond_and_unknown(self):
        """One beyond-head plus one unknown in the same run: fails on the
        beyond-head one and still surfaces the unverified one."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("Bad", current_position="10", head_position="5"),
            _make_status("Offline", current_position=None, head_position=None),
        ]
        result = _invoke(statuses)

        assert result.exit_code == 1
        assert "1 of 2 checkpoint(s) point past" in result.output
        assert "could not be verified" in result.output

    def test_empty_list_reports_none_found(self):
        """No event-store subscriptions at all: the empty-list branch reports it
        and exits 0."""
        change_working_directory_to("test7")

        result = _invoke([])

        assert result.exit_code == 0
        assert "No event-store subscriptions found" in result.output

    def test_no_flag_prints_hint_and_exits_zero(self):
        """Without --verify-checkpoints the command prints its hint and exits 0
        without loading the domain."""
        change_working_directory_to("test7")

        with patch("protean.cli._helpers.derive_domain") as derive:
            result = runner.invoke(app, ["recover"])

        assert result.exit_code == 0
        assert "--verify-checkpoints" in result.output
        derive.assert_not_called()

    def test_domain_loading_error(self):
        """A missing domain exits non-zero on the human path (typer.Abort)."""
        change_working_directory_to("test7")

        with patch(
            "protean.cli._helpers.derive_domain",
            side_effect=NoDomainException("not found"),
        ):
            result = runner.invoke(
                app,
                ["recover", "--verify-checkpoints", "--domain", "nonexistent.py"],
            )

        assert result.exit_code == 1


class TestRecoverJson:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_json_fail_when_beyond_head(self):
        """Criterion 3: --json fails with the envelope, status=fail, and the
        per-subscription checkpoint/head/beyond_head fields."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("OrderHandler", current_position="10", head_position="5"),
        ]
        result = _invoke(statuses, ["--json"])

        assert result.exit_code == 1
        env = assert_envelope(result.stdout)
        assert env["status"] == "fail"
        subs = env["data"]["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["checkpoint_position"] == "10"
        assert subs[0]["head_position"] == "5"
        assert subs[0]["beyond_head"] is True
        assert subs[0]["verdict"] == "beyond_head"
        assert env["data"]["summary"] == {
            "checked": 1,
            "consistent": 0,
            "beyond_head": 1,
            "unknown": 0,
        }

    def test_json_pass_when_consistent(self):
        """--json passes (status=pass, exit 0) when no checkpoint is beyond head."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("OrderHandler", current_position="5", head_position="5"),
        ]
        result = _invoke(statuses, ["--json"])

        assert result.exit_code == 0
        env = assert_envelope(result.stdout)
        assert env["status"] == "pass"
        assert env["data"]["subscriptions"][0]["beyond_head"] is False
        assert env["data"]["subscriptions"][0]["verdict"] == "consistent"
        assert env["data"]["summary"] == {
            "checked": 1,
            "consistent": 1,
            "beyond_head": 0,
            "unknown": 0,
        }

    def test_json_unknown_is_reported_not_clear(self):
        """--json on an unreachable store passes (unknown is not a violation) but
        marks the subscription unknown and counts it, so a machine consumer can
        tell "could not read" from "checked and fine"."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("Offline", current_position=None, head_position=None),
        ]
        result = _invoke(statuses, ["--json"])

        assert result.exit_code == 0
        env = assert_envelope(result.stdout)
        assert env["status"] == "pass"
        assert env["data"]["subscriptions"][0]["verdict"] == "unknown"
        assert env["data"]["subscriptions"][0]["beyond_head"] is False
        assert env["data"]["summary"] == {
            "checked": 1,
            "consistent": 0,
            "beyond_head": 0,
            "unknown": 1,
        }

    def test_json_zero_event_store_subscriptions(self):
        """--json with no event-store subscriptions is a pass with an empty list
        and checked=0."""
        change_working_directory_to("test7")

        result = _invoke([], ["--json"])

        assert result.exit_code == 0
        env = assert_envelope(result.stdout)
        assert env["status"] == "pass"
        assert env["data"]["subscriptions"] == []
        assert env["data"]["summary"] == {
            "checked": 0,
            "consistent": 0,
            "beyond_head": 0,
            "unknown": 0,
        }

    def test_json_only_event_store_in_payload(self):
        """--json lists only event-store subscriptions; a broker one is excluded."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("OrderHandler", current_position="5", head_position="5"),
            _make_status(
                "BrokerHandler",
                subscription_type="broker",
                current_position="99",
                head_position="1",
            ),
        ]
        result = _invoke(statuses, ["--json"])

        assert result.exit_code == 0
        env = assert_envelope(result.stdout)
        names = [s["handler_name"] for s in env["data"]["subscriptions"]]
        assert names == ["OrderHandler"]

    def test_json_domain_load_error_is_envelope(self):
        """A domain-load failure under --json is the error envelope on stdout,
        exit 2, no rich markup leaked."""
        from protean.cli.result import EXIT_USAGE

        change_working_directory_to("test7")

        with patch(
            "protean.cli._helpers.derive_domain",
            side_effect=NoDomainException("not found"),
        ):
            result = runner.invoke(
                app,
                [
                    "recover",
                    "--verify-checkpoints",
                    "--domain",
                    "nonexistent.py",
                    "--json",
                ],
            )

        assert result.exit_code == EXIT_USAGE
        env = assert_envelope(result.stdout)
        assert env["status"] == "error"
        assert "Error loading Protean domain" in env["data"]["error"]
        assert "[red]" not in result.stdout


class TestBeyondHead:
    """Unit tests for the core comparison. Collectors read positions as ints and
    ``str()``-ify them onto ``SubscriptionStatus``, so what arrives here is a
    numeric string, ``None``, or something unparseable from a foreign store."""

    @pytest.mark.parametrize(
        "current, head, expected",
        [
            ("10", "5", True),  # strictly ahead: the case the command exists for
            ("5", "5", False),  # caught up
            ("3", "9", False),  # behind
            ("-1", "7", False),  # fresh subscription against a real head
            ("-1", "-1", False),  # fresh against an empty stream
            (None, "5", None),  # unreachable store
            ("5", None, None),
            ("5.0", "3", None),  # foreign store: non-numeric, not a crash
            ("abc", "3", None),
            ("", "3", None),
        ],
    )
    def test_beyond_head(self, current, head, expected):
        from protean.cli.recover import _beyond_head

        status = _make_status(current_position=current, head_position=head)
        assert _beyond_head(status) is expected

    def test_verdict_tokens(self):
        from protean.cli.recover import _verdict

        assert _verdict(_make_status(current_position="10", head_position="5")) == (
            "beyond_head"
        )
        assert (
            _verdict(_make_status(current_position="5", head_position="5"))
            == "consistent"
        )
        assert (
            _verdict(_make_status(current_position=None, head_position=None))
            == "unknown"
        )


def _invoke_reset(
    statuses,
    reset_mock,
    extra_args=None,
    recovery_findings=None,
    recovery_reset_mock=None,
):
    """Invoke ``recover --verify-checkpoints --reset-beyond-head`` with the status
    collector and both checkpoint writers stubbed."""
    mock_domain = _mock_domain_for_cli()
    with (
        patch("protean.cli._helpers.derive_domain", return_value=mock_domain),
        patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=statuses,
        ),
        patch(
            "protean.server.subscription_status.reset_checkpoint_to_head",
            reset_mock,
        ),
        patch(
            "protean.server.subscription_status.collect_recovery_checkpoint_statuses",
            return_value=recovery_findings or [],
        ),
        patch(
            "protean.server.subscription_status.reset_recovery_checkpoint",
            recovery_reset_mock
            or MagicMock(side_effect=lambda _d, f: f.stale_positions),
        ),
    ):
        return runner.invoke(
            app,
            [
                "recover",
                "--verify-checkpoints",
                "--reset-beyond-head",
                "--domain",
                "publishing7.py",
            ]
            + (extra_args or []),
        )


class TestRecoverResetBeyondHead:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_reset_snaps_beyond_head_and_exits_zero(self):
        """Acceptance: a beyond-head checkpoint is snapped to head, the run
        reports the change, and it exits 0."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("OrderHandler", current_position="10", head_position="5"),
        ]
        reset_mock = MagicMock(return_value=5)
        result = _invoke_reset(statuses, reset_mock)

        assert result.exit_code == 0
        assert "Reset 1 beyond-head checkpoint" in result.output
        # The reported change names the transition; the reset line carries the
        # arrow, the verification table row does not.
        row = next(
            line
            for line in result.output.splitlines()
            if "OrderHandler" in line and "->" in line
        )
        assert "10 -> 5" in row
        reset_mock.assert_called_once()
        assert reset_mock.call_args.args[1].handler_name == "OrderHandler"

    def test_reset_leaves_consistent_and_unknown_untouched(self):
        """Acceptance (scope): only the beyond-head checkpoint is reset; a
        consistent one and an unknown one are never written."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("Good", current_position="5", head_position="5"),
            _make_status("Bad", current_position="10", head_position="5"),
            _make_status("Offline", current_position=None, head_position=None),
        ]
        reset_mock = MagicMock(return_value=5)
        result = _invoke_reset(statuses, reset_mock)

        assert result.exit_code == 0
        reset_mock.assert_called_once()
        assert reset_mock.call_args.args[1].handler_name == "Bad"

    def test_reset_without_beyond_head_reports_nothing_and_writes_nothing(self):
        """With nothing beyond head, --reset-beyond-head reports it and makes no
        write."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("Good", current_position="5", head_position="5"),
        ]
        reset_mock = MagicMock(return_value=5)
        result = _invoke_reset(statuses, reset_mock)

        assert result.exit_code == 0
        assert "No beyond-head checkpoints to reset" in result.output
        reset_mock.assert_not_called()

    def test_reset_reports_unverified_alongside_resets(self):
        """A reset run still surfaces the unverified rows it could not check."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("Bad", current_position="10", head_position="5"),
            _make_status("Offline", current_position=None, head_position=None),
        ]
        reset_mock = MagicMock(return_value=5)
        result = _invoke_reset(statuses, reset_mock)

        assert result.exit_code == 0
        assert "Reset 1 beyond-head checkpoint" in result.output
        assert "could not be verified" in result.output

    def test_reset_requires_verify_checkpoints(self):
        """--reset-beyond-head on its own is a usage error and loads no domain."""
        change_working_directory_to("test7")

        with patch("protean.cli._helpers.derive_domain") as derive:
            result = runner.invoke(app, ["recover", "--reset-beyond-head"])

        assert result.exit_code == 2
        assert "requires --verify-checkpoints" in result.output
        derive.assert_not_called()

    def test_reset_requires_verify_checkpoints_json(self):
        """The same guard under --json is the error envelope on stdout, exit 2."""
        from protean.cli.result import EXIT_USAGE

        change_working_directory_to("test7")

        result = runner.invoke(app, ["recover", "--reset-beyond-head", "--json"])

        assert result.exit_code == EXIT_USAGE
        env = assert_envelope(result.stdout)
        assert env["status"] == "error"
        assert "requires --verify-checkpoints" in env["data"]["error"]

    def test_plain_verify_never_calls_the_reset_writer(self):
        """Criterion 2: a --verify-checkpoints run without --reset-beyond-head
        never invokes the checkpoint writer, even with a beyond-head subscription
        present."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("Bad", current_position="10", head_position="5"),
        ]
        mock_domain = _mock_domain_for_cli()
        with (
            patch("protean.cli._helpers.derive_domain", return_value=mock_domain),
            patch(
                "protean.server.subscription_status.collect_subscription_statuses",
                return_value=statuses,
            ),
            patch(
                "protean.server.subscription_status.reset_checkpoint_to_head"
            ) as reset,
        ):
            result = runner.invoke(
                app,
                ["recover", "--verify-checkpoints", "--domain", "publishing7.py"],
            )

        assert result.exit_code == 1
        reset.assert_not_called()

    def test_reset_write_failure_is_reported_and_exits_two(self):
        """A reset write that fails mid-run: the reachable checkpoint is still
        reset and reported, the failure is named, and the run exits 2."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("First", current_position="10", head_position="5"),
            _make_status("Second", current_position="12", head_position="4"),
        ]
        reset_mock = MagicMock(side_effect=[5, RuntimeError("store down")])
        result = _invoke_reset(statuses, reset_mock)

        assert result.exit_code == 2
        assert "Reset 1 beyond-head checkpoint" in result.output
        assert "could not be reset" in result.output
        assert "Second" in result.output
        assert "store down" in result.output

    def test_reset_all_writes_fail_does_not_claim_none_to_reset(self):
        """When every beyond-head write fails, the run reports the failures and
        does not also claim there was nothing to reset."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("Bad", current_position="10", head_position="5"),
        ]
        reset_mock = MagicMock(side_effect=RuntimeError("store down"))
        result = _invoke_reset(statuses, reset_mock)

        assert result.exit_code == 2
        assert "could not be reset" in result.output
        assert "No beyond-head checkpoints to reset" not in result.output


class TestRecoverResetJson:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_json_reset_includes_reset_list_and_passes(self):
        """--json --reset-beyond-head passes, adds a reset count to the summary,
        and lists each change under data.reset while still reporting the finding."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("OrderHandler", current_position="10", head_position="5"),
        ]
        reset_mock = MagicMock(return_value=5)
        result = _invoke_reset(statuses, reset_mock, ["--json"])

        assert result.exit_code == 0
        env = assert_envelope(result.stdout)
        assert env["status"] == "pass"
        assert env["data"]["summary"] == {
            "checked": 1,
            "consistent": 0,
            "beyond_head": 1,
            "unknown": 0,
            "reset": 1,
            "reset_failed": 0,
        }
        assert env["data"]["reset"] == [
            {
                "name": "sub-orderhandler",
                "handler_name": "OrderHandler",
                "stream_category": "order",
                "previous_position": "10",
                "new_position": "5",
            }
        ]
        assert env["data"]["reset_failures"] == []
        # The finding is still reported so a consumer sees what was reset.
        assert env["data"]["subscriptions"][0]["verdict"] == "beyond_head"

    def test_json_reset_lists_only_beyond_head(self):
        """Only the beyond-head subscription appears in data.reset."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("Good", current_position="5", head_position="5"),
            _make_status("Bad", current_position="10", head_position="5"),
        ]
        reset_mock = MagicMock(return_value=5)
        result = _invoke_reset(statuses, reset_mock, ["--json"])

        assert result.exit_code == 0
        env = assert_envelope(result.stdout)
        assert [r["handler_name"] for r in env["data"]["reset"]] == ["Bad"]
        assert env["data"]["summary"]["reset"] == 1

    def test_json_reset_write_failure_is_error_envelope(self):
        """A reset write failure under --json still emits one envelope: status
        error, exit 2, the successful reset under data.reset and the failed one
        under data.reset_failures."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("First", current_position="10", head_position="5"),
            _make_status("Second", current_position="12", head_position="4"),
        ]
        reset_mock = MagicMock(side_effect=[5, RuntimeError("store down")])
        result = _invoke_reset(statuses, reset_mock, ["--json"])

        assert result.exit_code == 2
        env = assert_envelope(result.stdout)
        assert env["status"] == "error"
        assert [r["handler_name"] for r in env["data"]["reset"]] == ["First"]
        assert len(env["data"]["reset_failures"]) == 1
        assert env["data"]["reset_failures"][0]["handler_name"] == "Second"
        assert "store down" in env["data"]["reset_failures"][0]["error"]
        assert env["data"]["summary"]["reset"] == 1
        assert env["data"]["summary"]["reset_failed"] == 1


class TestRecoverRecoveryVerify:
    """Recovery-tracking findings on the human --verify-checkpoints path."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_stale_recovery_entry_flagged_and_named(self):
        """AC1: a stale recovery entry fails the run and names the subscription
        and its positions, even when every read-position checkpoint is fine."""
        change_working_directory_to("test7")

        statuses = [_make_status("Order", current_position="5", head_position="5")]
        findings = [
            _make_recovery_finding("OrderProjector", "order", stale_positions=[10, 12])
        ]
        result = _invoke(statuses, recovery_findings=findings)

        assert result.exit_code == 1
        assert "recovery-tracking entry(ies)" in result.output
        row = next(
            line
            for line in result.output.splitlines()
            if "OrderProjector" in line and "order" in line
        )
        assert "10, 12" in row

    def test_recovery_and_checkpoint_both_flagged(self):
        """A beyond-head checkpoint and a stale recovery entry together both fail
        the run and are both reported."""
        change_working_directory_to("test7")

        statuses = [_make_status("Bad", current_position="10", head_position="5")]
        findings = [
            _make_recovery_finding("PayProjector", "payment", stale_positions=[8])
        ]
        result = _invoke(statuses, recovery_findings=findings)

        assert result.exit_code == 1
        assert "point past the" in result.output
        assert "recovery-tracking entry(ies)" in result.output
        assert "PayProjector" in result.output

    def test_no_recovery_findings_all_consistent(self):
        """No recovery findings and consistent checkpoints exits 0."""
        change_working_directory_to("test7")

        statuses = [_make_status("Order", current_position="5", head_position="5")]
        result = _invoke(statuses, recovery_findings=[])

        assert result.exit_code == 0
        assert "consistent" in result.output
        assert "recovery-tracking" not in result.output

    def test_unknown_recovery_finding_is_reported_not_failed(self):
        """A recovery finding whose streams could not be read is surfaced as
        unverified and does not fail the run (exit 0), so it is never read as
        clean."""
        change_working_directory_to("test7")

        statuses = [_make_status("Order", current_position="5", head_position="5")]
        findings = [_make_recovery_unknown("OrderProjector", "order")]
        result = _invoke(statuses, recovery_findings=findings)

        assert result.exit_code == 0
        assert "could not be verified" in result.output
        assert "recovery-tracking entry(ies)" not in result.output

    def test_stale_and_unknown_recovery_findings_together(self):
        """A stale finding fails the run and an unknown one is still surfaced
        alongside it."""
        change_working_directory_to("test7")

        statuses = [_make_status("Order", current_position="5", head_position="5")]
        findings = [
            _make_recovery_finding("Stale", "order", stale_positions=[10]),
            _make_recovery_unknown("Offline", "payment"),
        ]
        result = _invoke(statuses, recovery_findings=findings)

        assert result.exit_code == 1
        assert "recovery-tracking entry(ies)" in result.output
        assert "could not be verified" in result.output

    def test_plain_verify_never_calls_recovery_reset_writer(self):
        """AC3: a --verify-checkpoints run without --reset-beyond-head never
        invokes the recovery reset writer, even with a stale entry present."""
        change_working_directory_to("test7")

        statuses = [_make_status("Order", current_position="5", head_position="5")]
        findings = [_make_recovery_finding("OrderProjector", "order")]
        mock_domain = _mock_domain_for_cli()
        with (
            patch("protean.cli._helpers.derive_domain", return_value=mock_domain),
            patch(
                "protean.server.subscription_status.collect_subscription_statuses",
                return_value=statuses,
            ),
            patch(
                "protean.server.subscription_status.collect_recovery_checkpoint_statuses",
                return_value=findings,
            ),
            patch(
                "protean.server.subscription_status.reset_recovery_checkpoint"
            ) as reset,
        ):
            result = runner.invoke(
                app,
                ["recover", "--verify-checkpoints", "--domain", "publishing7.py"],
            )

        assert result.exit_code == 1
        reset.assert_not_called()


class TestRecoverRecoveryVerifyJson:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_json_stale_recovery_entry_fails(self):
        """--json fails with the recovery findings under data.recovery and the
        summary counts."""
        change_working_directory_to("test7")

        statuses = [_make_status("Order", current_position="5", head_position="5")]
        findings = [
            _make_recovery_finding(
                "OrderProjector", "order", stale_positions=[10, 12], head_position=5
            )
        ]
        result = _invoke(statuses, ["--json"], recovery_findings=findings)

        assert result.exit_code == 1
        env = assert_envelope(result.stdout)
        assert env["status"] == "fail"
        assert env["data"]["recovery"] == [
            {
                "name": "sub-orderprojector",
                "handler_name": "OrderProjector",
                "stream_category": "order",
                "recovery_checkpoint_stream": "recovery-checkpoint-OrderProjector-order",
                "head_position": 5,
                "verdict": "stale",
                "stale_positions": [10, 12],
            }
        ]
        assert env["data"]["summary"]["recovery_stale"] == 1
        assert env["data"]["summary"]["recovery_stale_positions"] == 2
        assert env["data"]["summary"]["recovery_unknown"] == 0

    def test_json_no_recovery_findings_keeps_exact_shape(self):
        """Without a recovery finding, the --json payload carries no recovery
        keys and the summary is the plain four-key dict."""
        change_working_directory_to("test7")

        statuses = [_make_status("Order", current_position="5", head_position="5")]
        result = _invoke(statuses, ["--json"], recovery_findings=[])

        assert result.exit_code == 0
        env = assert_envelope(result.stdout)
        assert "recovery" not in env["data"]
        assert env["data"]["summary"] == {
            "checked": 1,
            "consistent": 1,
            "beyond_head": 0,
            "unknown": 0,
        }

    def test_json_unknown_recovery_finding_passes_and_is_counted(self):
        """An unverified recovery finding passes (exit 0) but is counted under
        summary.recovery_unknown and carries verdict "unknown", so a consumer can
        tell "could not read" from "checked and clean"."""
        change_working_directory_to("test7")

        statuses = [_make_status("Order", current_position="5", head_position="5")]
        findings = [_make_recovery_unknown("OrderProjector", "order")]
        result = _invoke(statuses, ["--json"], recovery_findings=findings)

        assert result.exit_code == 0
        env = assert_envelope(result.stdout)
        assert env["status"] == "pass"
        assert env["data"]["recovery"][0]["verdict"] == "unknown"
        assert env["data"]["summary"]["recovery_unknown"] == 1
        assert env["data"]["summary"]["recovery_stale"] == 0


class TestRecoverRecoveryReset:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_reset_clears_stale_recovery_entries_and_exits_zero(self):
        """AC2: --reset-beyond-head clears the stale recovery entries, reports
        what it cleared, and exits 0."""
        change_working_directory_to("test7")

        statuses = [_make_status("Order", current_position="5", head_position="5")]
        findings = [
            _make_recovery_finding("OrderProjector", "order", stale_positions=[10, 12])
        ]
        recovery_reset = MagicMock(side_effect=lambda _d, f: f.stale_positions)
        reset_mock = MagicMock(return_value=5)
        result = _invoke_reset(
            statuses,
            reset_mock,
            recovery_findings=findings,
            recovery_reset_mock=recovery_reset,
        )

        assert result.exit_code == 0
        assert "Cleared 2 stale recovery-tracking entry(ies)" in result.output
        row = next(
            line
            for line in result.output.splitlines()
            if "OrderProjector" in line and "10, 12" in line
        )
        assert "10, 12" in row
        recovery_reset.assert_called_once()
        assert recovery_reset.call_args.args[1].handler_name == "OrderProjector"

    def test_reset_both_lanes_together(self):
        """A single --reset-beyond-head run resets both a beyond-head checkpoint
        and a stale recovery entry, reporting each in its own block, exit 0."""
        change_working_directory_to("test7")

        statuses = [_make_status("Bad", current_position="10", head_position="5")]
        findings = [
            _make_recovery_finding("OrderProjector", "order", stale_positions=[9])
        ]
        recovery_reset = MagicMock(side_effect=lambda _d, f: f.stale_positions)
        checkpoint_reset = MagicMock(return_value=5)
        result = _invoke_reset(
            statuses,
            checkpoint_reset,
            recovery_findings=findings,
            recovery_reset_mock=recovery_reset,
        )

        assert result.exit_code == 0
        # Both lanes reported, both writers called.
        assert "Reset 1 beyond-head checkpoint" in result.output
        assert "Cleared 1 stale recovery-tracking entry(ies)" in result.output
        checkpoint_reset.assert_called_once()
        recovery_reset.assert_called_once()

    def test_reset_recovery_only_suppresses_none_to_reset_line(self):
        """With no beyond-head checkpoint but a stale recovery entry, the run does
        not claim there was nothing to reset."""
        change_working_directory_to("test7")

        statuses = [_make_status("Order", current_position="5", head_position="5")]
        findings = [_make_recovery_finding("OrderProjector", "order")]
        reset_mock = MagicMock(return_value=5)
        result = _invoke_reset(statuses, reset_mock, recovery_findings=findings)

        assert result.exit_code == 0
        assert "No beyond-head checkpoints to reset" not in result.output
        assert "Cleared" in result.output
        reset_mock.assert_not_called()

    def test_reset_recovery_write_failure_exits_two(self):
        """A recovery reset write that fails is named and the run exits 2."""
        change_working_directory_to("test7")

        statuses = [_make_status("Order", current_position="5", head_position="5")]
        findings = [_make_recovery_finding("OrderProjector", "order")]
        recovery_reset = MagicMock(side_effect=RuntimeError("store down"))
        reset_mock = MagicMock(return_value=5)
        result = _invoke_reset(
            statuses,
            reset_mock,
            recovery_findings=findings,
            recovery_reset_mock=recovery_reset,
        )

        assert result.exit_code == 2
        assert "recovery checkpoint(s) could not be reset" in result.output
        assert "store down" in result.output


class TestRecoverRecoveryResetJson:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_json_reset_recovery_passes_with_reset_data(self):
        """--json --reset-beyond-head passes and lists what was cleared under
        data.recovery_reset with a summary count."""
        change_working_directory_to("test7")

        statuses = [_make_status("Order", current_position="5", head_position="5")]
        findings = [
            _make_recovery_finding("OrderProjector", "order", stale_positions=[10, 12])
        ]
        recovery_reset = MagicMock(side_effect=lambda _d, f: f.stale_positions)
        reset_mock = MagicMock(return_value=5)
        result = _invoke_reset(
            statuses,
            reset_mock,
            extra_args=["--json"],
            recovery_findings=findings,
            recovery_reset_mock=recovery_reset,
        )

        assert result.exit_code == 0
        env = assert_envelope(result.stdout)
        assert env["status"] == "pass"
        assert env["data"]["recovery_reset"] == [
            {
                "name": "sub-orderprojector",
                "handler_name": "OrderProjector",
                "stream_category": "order",
                "cleared_positions": [10, 12],
            }
        ]
        assert env["data"]["recovery_reset_failures"] == []
        assert env["data"]["summary"]["recovery_reset"] == 2
        assert env["data"]["summary"]["recovery_reset_failed"] == 0

    def test_json_reset_recovery_write_failure_is_error_envelope(self):
        """A recovery reset write failure under --json is the error envelope, exit
        2, with the failure under data.recovery_reset_failures."""
        change_working_directory_to("test7")

        statuses = [_make_status("Order", current_position="5", head_position="5")]
        findings = [_make_recovery_finding("OrderProjector", "order")]
        recovery_reset = MagicMock(side_effect=RuntimeError("store down"))
        reset_mock = MagicMock(return_value=5)
        result = _invoke_reset(
            statuses,
            reset_mock,
            extra_args=["--json"],
            recovery_findings=findings,
            recovery_reset_mock=recovery_reset,
        )

        assert result.exit_code == 2
        env = assert_envelope(result.stdout)
        assert env["status"] == "error"
        assert len(env["data"]["recovery_reset_failures"]) == 1
        assert env["data"]["recovery_reset_failures"][0]["handler_name"] == (
            "OrderProjector"
        )
        assert "store down" in env["data"]["recovery_reset_failures"][0]["error"]
        assert env["data"]["summary"]["recovery_reset_failed"] == 1
