"""Tests for CLI outbox commands (protean outbox ...)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.cli import outbox as cli_outbox
from protean.exceptions import NoDomainException
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import Outbox, OutboxStatus
from tests.cli._envelope import assert_envelope

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

    def test_disabled_outbox_message_names_both_switches(self):
        domain = _mock_domain(has_outbox=False)
        with (
            patch("protean.cli._helpers.derive_domain", return_value=domain),
            patch("protean.cli.outbox.reconcile_outbox"),
        ):
            result = runner.invoke(app, ["outbox", "reconcile", "--domain", "x.py"])

        output = " ".join(result.output.split())  # undo terminal line wrapping
        assert 'default_subscription_type = "stream" under [server]' in output
        assert "enable_outbox = true" in output

    def test_reconcile_aborts_when_domain_not_found(self):
        with patch(
            "protean.cli._helpers.derive_domain",
            side_effect=NoDomainException("Could not find domain"),
        ):
            result = runner.invoke(app, ["outbox", "reconcile", "--domain", "nope.py"])

        assert result.exit_code != 0
        assert "Error loading Protean domain" in result.output


# ---------------------------------------------------------------------------
# halted, retry and discard, against a real domain
# ---------------------------------------------------------------------------

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
CATEGORY = "test::counter"


@pytest.fixture
def outbox_domain(test_domain):
    test_domain.config["enable_outbox"] = True
    test_domain.config["server"]["default_subscription_type"] = "stream"
    test_domain.init(traverse=False)
    with patch("protean.cli.outbox.load_domain", return_value=test_domain):
        yield test_domain


@pytest.fixture
def outbox_repo(outbox_domain):
    return outbox_domain._get_outbox_repo("default")


def _row(label: str, minute: int, status: str = OutboxStatus.PENDING.value) -> Outbox:
    metadata = Metadata(
        headers=MessageHeaders(id=label, type="Test.Bumped.v1", stream=CATEGORY),
        domain=DomainMeta(stream_category=CATEGORY),
    )
    row = Outbox.create_message(
        message_id=label,
        stream_name=f"{CATEGORY}-1",
        message_type="Test.Bumped.v1",
        data={"label": label},
        metadata=metadata,
        sequence_number=0,
        partition_key="client-1",
        stream_category=CATEGORY,
    )
    row.created_at = BASE_TIME + timedelta(minutes=minute)
    row.status = status
    if status == OutboxStatus.ABANDONED.value:
        row.retry_count = row.max_retries
        row.last_error = {"message": "broker rejected the payload"}
    return row


def _halted_key(outbox_repo) -> Outbox:
    """Seed a key whose head row is abandoned, with one row waiting behind it."""
    outbox_repo.add(_row("b", minute=1))
    head = _row("a", minute=0, status=OutboxStatus.ABANDONED.value)
    outbox_repo.add(head)
    return head


def _reload(outbox_repo, row: Outbox) -> Outbox:
    return outbox_repo.get(row.id)


def _flat(output: str) -> str:
    """Undo terminal line wrapping."""
    return " ".join(output.split())


def _invoke(*args: str):
    return runner.invoke(app, ["outbox", *args, "--domain", "x.py"])


class TestOutboxHalted:
    def test_lists_the_halted_key(self, outbox_repo):
        head = _halted_key(outbox_repo)

        result = _invoke("halted")

        assert result.exit_code == 0, result.output
        output = _flat(result.output)
        assert (
            "1 halted group(s) of broker, stream category, partition key and lane:"
            in output
        )
        assert f"default {CATEGORY} key=client-1 lane=primary" in output
        assert f"head row {head.id} is abandoned" in output
        assert "(broker rejected the payload)" in output
        assert "1 row(s) waiting" in output

    def test_an_abandoned_row_behind_a_failed_row_is_not_listed(self, outbox_repo):
        outbox_repo.add(_row("b", minute=1, status=OutboxStatus.ABANDONED.value))
        outbox_repo.add(_row("a", minute=0, status=OutboxStatus.FAILED.value))

        result = _invoke("halted")

        assert result.exit_code == 0, result.output
        assert "No partition key is halted." in _flat(result.output)

    def test_json_lists_each_key_in_the_envelope(self, outbox_repo):
        head = _halted_key(outbox_repo)

        result = _invoke("halted", "--json")

        assert result.exit_code == 0, result.output
        envelope = assert_envelope(result.stdout)
        assert envelope["status"] == "pass"
        assert envelope["data"]["halted"] == [
            {
                "target_broker": "default",
                "stream_category": CATEGORY,
                "partition_key": "client-1",
                "lane": "primary",
                "head_id": str(head.id),
                "status": OutboxStatus.ABANDONED.value,
                "last_error": {"message": "broker rejected the payload"},
                "waiting": 1,
            }
        ]

    def test_json_with_nothing_halted_is_an_empty_list(self, outbox_repo):
        result = _invoke("halted", "--json")

        assert result.exit_code == 0, result.output
        envelope = assert_envelope(result.stdout)
        assert envelope["data"] == {"halted": []}


class TestOutboxRetry:
    def test_retry_puts_the_head_back_to_pending(self, outbox_repo):
        head = _halted_key(outbox_repo)

        result = _invoke("retry", str(head.id))

        assert result.exit_code == 0, result.output
        assert f"Outbox row {head.id} is pending" in _flat(result.output)
        row = _reload(outbox_repo, head)
        assert row.status == OutboxStatus.PENDING.value
        assert row.retry_count == 0
        claimed = outbox_repo.claim_batch("worker-1", limit=10)
        assert [row.message_id for row in claimed] == ["a", "b"]


class TestOutboxDiscard:
    def test_discard_releases_the_rest_of_the_key(self, outbox_repo):
        head = _halted_key(outbox_repo)

        result = _invoke("discard", str(head.id), "--reason", "bad payload")

        assert result.exit_code == 0, result.output
        assert f"Outbox row {head.id} is discarded" in _flat(result.output)
        row = _reload(outbox_repo, head)
        assert row.status == OutboxStatus.DISCARDED.value
        assert row.last_error["message"] == "broker rejected the payload"
        assert row.last_error["discard_reason"] == "bad payload"
        claimed = outbox_repo.claim_batch("worker-1", limit=10)
        assert [row.message_id for row in claimed] == ["b"]

    def test_discard_needs_a_reason(self, outbox_repo):
        head = _halted_key(outbox_repo)

        result = _invoke("discard", str(head.id))

        assert result.exit_code == 2
        assert _reload(outbox_repo, head).status == OutboxStatus.ABANDONED.value

    @pytest.mark.parametrize("reason", ["", "   "], ids=["empty", "blank"])
    def test_discard_refuses_a_blank_reason(self, outbox_repo, reason):
        head = _halted_key(outbox_repo)

        result = _invoke("discard", str(head.id), "--reason", reason)

        assert result.exit_code == 2
        assert "give the reason the row is skipped" in _flat(result.output)
        assert _reload(outbox_repo, head).status == OutboxStatus.ABANDONED.value


class TestOutboxRetryAndDiscardRefuse:
    @pytest.mark.parametrize(
        "args", [("retry",), ("discard", "--reason", "skip")], ids=["retry", "discard"]
    )
    @pytest.mark.parametrize(
        "status", [OutboxStatus.PUBLISHED.value, OutboxStatus.PENDING.value]
    )
    def test_a_row_that_is_not_failed_or_abandoned_is_left_alone(
        self, outbox_repo, args, status
    ):
        row = _row("a", minute=0, status=status)
        row.retry_count = 2
        row.next_retry_at = BASE_TIME + timedelta(days=1)
        row.locked_by = "worker-9"
        row.locked_until = BASE_TIME + timedelta(days=1)
        outbox_repo.add(row)
        before = _reload(outbox_repo, row).to_dict()

        result = _invoke(args[0], str(row.id), *args[1:])

        assert result.exit_code == 1
        assert f"Outbox row {row.id} is {status}" in _flat(result.output)
        assert _reload(outbox_repo, row).to_dict() == before

    @pytest.mark.parametrize(
        "args", [("retry",), ("discard", "--reason", "skip")], ids=["retry", "discard"]
    )
    def test_an_unknown_id_is_reported(self, outbox_repo, args):
        head = _halted_key(outbox_repo)
        before = _reload(outbox_repo, head).to_dict()

        result = _invoke(args[0], "no-such-row", *args[1:])

        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        assert "No outbox row with id no-such-row." in _flat(result.output)
        assert _reload(outbox_repo, head).to_dict() == before

    @pytest.mark.parametrize(
        "args", [("retry",), ("discard", "--reason", "skip")], ids=["retry", "discard"]
    )
    def test_a_row_a_worker_claims_during_the_command_is_left_alone(
        self, outbox_repo, monkeypatch, args
    ):
        row = _row("a", minute=0, status=OutboxStatus.FAILED.value)
        outbox_repo.add(row)
        load_row = cli_outbox._load_row

        def load_then_claim(domain, repo, row_id):
            loaded = load_row(domain, repo, row_id)
            claimed = repo.claim_batch("worker-1", limit=10)
            assert [claimed_row.id for claimed_row in claimed] == [row.id]
            return loaded

        monkeypatch.setattr(cli_outbox, "_load_row", load_then_claim)

        result = _invoke(args[0], str(row.id), *args[1:])

        assert result.exit_code == 1
        assert f"Outbox row {row.id} changed while the command ran" in _flat(
            result.output
        )
        stored = _reload(outbox_repo, row)
        assert stored.status == OutboxStatus.PROCESSING.value
        assert stored.locked_by == "worker-1"
        assert stored.last_error is None


class TestRowIdShape:
    @pytest.mark.parametrize(
        "identity_type, row_id, well_formed",
        [
            ("uuid", "not-a-uuid", False),
            ("uuid", "4f6c8a3e-1b2d-4c5e-9f00-1234567890ab", True),
            ("integer", "abc", False),
            ("integer", "42", True),
            ("string", "anything", True),
        ],
    )
    def test_the_id_is_checked_against_the_identity_type(
        self, test_domain, identity_type, row_id, well_formed
    ):
        test_domain.config["identity_type"] = identity_type

        assert cli_outbox._is_well_formed(test_domain, row_id) is well_formed

    def test_a_malformed_id_is_reported_as_unknown(self, outbox_domain, outbox_repo):
        outbox_domain.config["identity_type"] = "uuid"

        result = _invoke("retry", "not-a-uuid")

        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        assert "No outbox row with id not-a-uuid." in _flat(result.output)


class TestNewCommandsNeedTheOutbox:
    @pytest.mark.parametrize(
        "args",
        [("halted",), ("retry", "1"), ("discard", "1", "--reason", "skip")],
        ids=["halted", "retry", "discard"],
    )
    def test_each_command_aborts_when_outbox_disabled(self, args):
        domain = _mock_domain(has_outbox=False)
        with patch("protean.cli._helpers.derive_domain", return_value=domain):
            result = _invoke(*args)

        assert result.exit_code == 1
        assert "Outbox is not enabled" in _flat(result.output)
        domain._get_outbox_repo.assert_not_called()

    def test_halted_json_reports_a_disabled_outbox_as_an_error_envelope(self):
        domain = _mock_domain(has_outbox=False)
        with patch("protean.cli._helpers.derive_domain", return_value=domain):
            result = _invoke("halted", "--json")

        assert result.exit_code == 2
        envelope = assert_envelope(result.stdout)
        assert envelope["status"] == "error"
        assert "under [server]" in envelope["data"]["error"]
        domain._get_outbox_repo.assert_not_called()


class TestUnknownProvider:
    def test_halted_json_reports_an_unknown_provider_as_an_error_envelope(
        self, outbox_domain
    ):
        result = _invoke("halted", "--json", "--provider", "no-such-provider")

        assert result.exit_code == 2
        envelope = assert_envelope(result.stdout)
        assert envelope["status"] == "error"
        assert "no-such-provider" in envelope["data"]["error"]

    @pytest.mark.parametrize(
        "args",
        [("halted",), ("retry", "1"), ("discard", "1", "--reason", "skip")],
        ids=["halted", "retry", "discard"],
    )
    def test_each_command_reports_an_unknown_provider(self, outbox_domain, args):
        result = _invoke(*args, "--provider", "no-such-provider")

        assert result.exit_code == 2
        assert "no-such-provider" in _flat(result.stderr)
