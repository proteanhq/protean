"""Trace-validation harness for the transactional outbox (:issue:`#1383`).

Three layers, matching the OCC harness (#1382):

- the recorder in ``protean.utils.outbox_trace`` — a diagnostic seam, inactive by
  default, activated by a process-wide :func:`~protean.utils.outbox_trace.capture`;
- the instrumentation on the real ``OutboxProcessor`` claim/publish/mark path, which
  must emit the spec's transitions when a capture is active and nothing otherwise;
- the ``specs/outbox_trace.py`` log-to-TLA+ converter and its reject branches, which
  ``check.sh`` only exercises on the happy path so its guards would rot here.

The three ``check.sh`` outcomes (a real trace accepted, the divergence fixture
rejected on conformance, the no-redelivery fixture rejected on coverage) are the
machine oracle; these tests pin the Python contracts underneath it.
"""

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from protean.core.unit_of_work import UnitOfWork
from protean.server import Engine
from protean.server.outbox_processor import OutboxProcessor
from protean.utils import outbox_trace
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import Outbox, OutboxStatus
from tests.shared import FrozenClock

# ──────────────────────────────────────────────────────────────────────
# Recorder unit tests (pure — no domain, mirroring the occ_trace tests)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.no_test_domain
def test_inactive_by_default():
    assert outbox_trace.is_active() is False


@pytest.mark.no_test_domain
def test_record_is_a_noop_when_inactive():
    outbox_trace.record(action="claim", worker="w1", message="m1")
    assert outbox_trace.is_active() is False


@pytest.mark.no_test_domain
def test_capture_activates_collects_and_restores():
    assert outbox_trace.is_active() is False
    with outbox_trace.capture() as events:
        assert outbox_trace.is_active() is True
        outbox_trace.record(action="claim", worker="w1", message="m1")
        outbox_trace.record(action="publish", worker="w1", message="m1", outcome="ok")
        outbox_trace.record(
            action="mark", worker="w1", message="m1", outcome="published"
        )
    assert outbox_trace.is_active() is False
    assert events == [
        {"action": "claim", "worker": "w1", "message": "m1", "outcome": None},
        {"action": "publish", "worker": "w1", "message": "m1", "outcome": "ok"},
        {"action": "mark", "worker": "w1", "message": "m1", "outcome": "published"},
    ]


@pytest.mark.no_test_domain
def test_capture_restores_even_on_error():
    with pytest.raises(RuntimeError):
        with outbox_trace.capture():
            assert outbox_trace.is_active() is True
            raise RuntimeError("boom")
    assert outbox_trace.is_active() is False


@pytest.mark.no_test_domain
def test_nested_captures_do_not_leak():
    with outbox_trace.capture() as outer:
        outbox_trace.record(action="claim", worker="w1", message="m1")
        with outbox_trace.capture() as inner:
            outbox_trace.record(action="claim", worker="w2", message="m2")
        assert [e["worker"] for e in inner] == ["w2"]
        assert outbox_trace.is_active() is True
        outbox_trace.record(action="crash", worker="w1", message="m1")
    assert [e["action"] for e in outer] == ["claim", "crash"]
    assert outbox_trace.is_active() is False


# ──────────────────────────────────────────────────────────────────────
# Instrumentation tests (drive the real OutboxProcessor)
# ──────────────────────────────────────────────────────────────────────

_FROZEN = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def outbox_domain(test_domain):
    """`test_domain` with the outbox enabled and a frozen clock, so lock expiry is
    deterministic rather than wall-clock dependent."""
    test_domain.config["enable_outbox"] = True
    test_domain.config["server"]["default_subscription_type"] = "stream"
    test_domain.init(traverse=False)
    test_domain.clock = FrozenClock(_FROZEN)
    return test_domain


def _persist_row(domain, message_id: str = "m1", stream: str = "test-stream") -> str:
    """Persist one PENDING outbox row and return its surrogate id."""
    repo = domain._get_outbox_repo("default")
    metadata = Metadata(
        headers=MessageHeaders(id=message_id, type="DummyEvent", stream=stream),
        domain=DomainMeta(stream_category=stream),
    )
    with UnitOfWork():
        repo.add(
            Outbox.create_message(
                message_id=message_id,
                stream_name=stream,
                message_type="DummyEvent",
                data={"value": 1},
                metadata=metadata,
            )
        )
    return str(repo.find_by_message_id(message_id).id)


def _make_processor(domain, worker_id: str) -> OutboxProcessor:
    engine = Engine(domain=domain, test_mode=False)
    return OutboxProcessor(
        engine=engine,
        database_provider_name="default",
        broker_provider_name="default",
        worker_id=worker_id,
    )


@pytest.mark.asyncio
async def test_success_emits_claim_publish_mark_in_order(outbox_domain):
    """A successful pass emits, in order, the claim, the broker publish (ok), and the
    mark (published) for that row — the spec's Claim, Publish, MarkPublished."""
    row_id = _persist_row(outbox_domain)
    processor = _make_processor(outbox_domain, "w1")
    await processor.initialize()

    with outbox_trace.capture() as events:
        batch = await processor.get_next_batch_of_messages()
        await processor.process_batch(batch)

    assert [e["action"] for e in events] == ["claim", "publish", "mark"]
    assert all(e["message"] == row_id for e in events)
    assert all(e["worker"] == "w1" for e in events)
    assert events[1]["outcome"] == "ok"
    assert events[2]["outcome"] == OutboxStatus.PUBLISHED.value


@pytest.mark.asyncio
async def test_publish_failure_emits_fail_and_mark_failed(outbox_domain):
    """A broker publish that raises emits a publish with outcome fail and a mark with
    the resulting FAILED status — the spec's Publish (fail branch) then MarkFailed."""
    _persist_row(outbox_domain)
    processor = _make_processor(outbox_domain, "w1")
    await processor.initialize()

    with patch.object(processor.broker, "publish", side_effect=Exception("boom")):
        with outbox_trace.capture() as events:
            batch = await processor.get_next_batch_of_messages()
            await processor.process_batch(batch)

    assert [e["action"] for e in events] == ["claim", "publish", "mark"]
    assert events[1]["outcome"] == "fail"
    assert events[2]["outcome"] == OutboxStatus.FAILED.value


@pytest.mark.asyncio
async def test_publish_failure_at_last_retry_emits_mark_abandoned(outbox_domain):
    """When retries are exhausted, a failed publish marks the row ABANDONED, and the
    mark emit carries that terminal status. This ties the status the real processor
    emits for abandonment to the ``abandoned`` value the converter accepts — the third
    mark outcome the crash-redelivery and failed-once paths never reach."""
    _persist_row(outbox_domain)
    processor = _make_processor(outbox_domain, "w1")
    await processor.initialize()
    # Abandon on the first failure: retry_count 0 -> 1, and 1 is not < 1.
    processor.retry_config["max_attempts"] = 1

    with patch.object(processor.broker, "publish", side_effect=Exception("boom")):
        with outbox_trace.capture() as events:
            batch = await processor.get_next_batch_of_messages()
            await processor.process_batch(batch)

    assert [e["action"] for e in events] == ["claim", "publish", "mark"]
    assert events[1]["outcome"] == "fail"
    assert events[2]["outcome"] == OutboxStatus.ABANDONED.value


@pytest.mark.asyncio
async def test_claim_alone_emits_only_claim(outbox_domain):
    """Claiming a batch without processing it emits only the claim — never a publish
    or a mark. The boundary-only contract, negative side: no phantom publish/mark
    appears just because a row was claimed."""
    _persist_row(outbox_domain)
    processor = _make_processor(outbox_domain, "w1")
    await processor.initialize()

    with outbox_trace.capture() as events:
        await processor.get_next_batch_of_messages()

    assert [e["action"] for e in events] == ["claim"]
    assert not any(e["action"] in ("publish", "mark") for e in events)


@pytest.mark.asyncio
async def test_processing_outside_a_capture_records_nothing(outbox_domain):
    """The recorder is inactive by default: a full publish outside a capture emits
    nothing and leaves the recorder inactive."""
    _persist_row(outbox_domain)
    processor = _make_processor(outbox_domain, "w1")
    await processor.initialize()

    batch = await processor.get_next_batch_of_messages()
    successful = await processor.process_batch(batch)

    assert successful == 1  # the work still happened
    assert outbox_trace.is_active() is False


@pytest.mark.asyncio
async def test_crash_redelivery_republishes_the_reclaimed_row(outbox_domain):
    """A worker claims and publishes a row, then crashes before the mark. The lock
    lapses, a second worker reclaims the still-PROCESSING row and publishes it again
    (the at-least-once duplicate) before marking it — the redelivery the coverage
    check witnesses."""
    row_id = _persist_row(outbox_domain)
    worker1 = _make_processor(outbox_domain, "w1")
    worker2 = _make_processor(outbox_domain, "w2")
    await worker1.initialize()
    await worker2.initialize()

    with outbox_trace.capture() as events:
        batch = await worker1.get_next_batch_of_messages()  # claim
        success, _ = await worker1._publish_message(batch[0])  # publish (ok)
        assert success is True

        # Crash before the mark; the row stays PROCESSING under a live lock.
        outbox_trace.record(action="crash", worker="w1", message=row_id)

        # The lock lapses once the clock passes locked_until.
        outbox_domain.clock.advance(timedelta(minutes=10))
        outbox_trace.record(action="lock_expire", worker="w1", message=row_id)

        batch2 = await worker2.get_next_batch_of_messages()  # reclaim
        assert len(batch2) == 1
        await worker2.process_batch(batch2)  # publish (duplicate) + mark

    assert [e["action"] for e in events] == [
        "claim",
        "publish",
        "crash",
        "lock_expire",
        "claim",
        "publish",
        "mark",
    ]
    # Both publishes are for the same row: the second is the duplicate.
    publishes = [e for e in events if e["action"] == "publish"]
    assert len(publishes) == 2
    assert all(e["message"] == row_id and e["outcome"] == "ok" for e in publishes)
    # The reclaim is by a different worker, and the row ends PUBLISHED.
    claims = [e for e in events if e["action"] == "claim"]
    assert [e["worker"] for e in claims] == ["w1", "w2"]
    assert events[-1] == {
        "action": "mark",
        "worker": "w2",
        "message": row_id,
        "outcome": OutboxStatus.PUBLISHED.value,
    }


# ──────────────────────────────────────────────────────────────────────
# Converter tests (specs/outbox_trace.py to-tla and its reject branches)
# ──────────────────────────────────────────────────────────────────────

_SPEC = Path(__file__).resolve().parents[2] / "specs" / "outbox_trace.py"
_module_spec = importlib.util.spec_from_file_location("specs_outbox_trace", _SPEC)
outbox_trace_script = importlib.util.module_from_spec(_module_spec)
_module_spec.loader.exec_module(outbox_trace_script)


def _write(path: Path, events: list[dict]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


def _redelivery_log() -> list[dict]:
    return [
        {"action": "claim", "worker": "wa", "message": "ma", "outcome": None},
        {"action": "publish", "worker": "wa", "message": "ma", "outcome": "ok"},
        {"action": "crash", "worker": "wa", "message": "ma", "outcome": None},
        {"action": "lock_expire", "worker": "wa", "message": "ma", "outcome": None},
        {"action": "claim", "worker": "wb", "message": "ma", "outcome": None},
        {"action": "publish", "worker": "wb", "message": "ma", "outcome": "ok"},
        {"action": "mark", "worker": "wb", "message": "ma", "outcome": "published"},
    ]


@pytest.mark.no_test_domain
def test_valid_log_converts_to_a_runnable_module(tmp_path):
    # Two distinct workers and one message pin WorkersDef == 1..2 and MessagesDef ==
    # 1..1; one crash pins MaxCrashesDef as a real count, not a constant-folded value.
    log = _write(tmp_path / "log.jsonl", _redelivery_log())
    out = tmp_path / "OutboxTrace_run.tla"

    assert outbox_trace_script._to_tla(log, out) == 0

    text = out.read_text(encoding="utf-8")
    assert "---- MODULE OutboxTrace_run ----" in text
    assert "EXTENDS OutboxTrace" in text
    assert 'action |-> "publish", worker |-> 1, msg |-> 1, outcome |-> "ok"' in text
    assert 'action |-> "claim", worker |-> 2, msg |-> 1, outcome |-> "none"' in text
    assert "MessagesDef == 1..1" in text
    assert "WorkersDef == 1..2" in text  # two distinct workers
    assert "MaxCrashesDef == 1" in text  # the crash counted
    assert "MaxRetriesDef == 1" in text  # no failing marks → floored at 1


@pytest.mark.no_test_domain
def test_failing_marks_raise_the_retry_bound(tmp_path):
    # A message that fails then is abandoned walks a retry ladder of depth 2, so the
    # retry bound must cover it (a message reaches ABANDONED when its failing-mark
    # count hits MaxRetries).
    log = _write(
        tmp_path / "fail.jsonl",
        [
            {"action": "claim", "worker": "w", "message": "m", "outcome": None},
            {"action": "publish", "worker": "w", "message": "m", "outcome": "fail"},
            {"action": "mark", "worker": "w", "message": "m", "outcome": "failed"},
            {"action": "publish", "worker": "w", "message": "m", "outcome": "fail"},
            {"action": "mark", "worker": "w", "message": "m", "outcome": "abandoned"},
        ],
    )
    out = tmp_path / "o.tla"
    assert outbox_trace_script._to_tla(log, out) == 0
    text = out.read_text(encoding="utf-8")
    assert "MaxRetriesDef == 2" in text
    assert 'outcome |-> "abandoned"' in text


@pytest.mark.no_test_domain
def test_empty_log_is_rejected(tmp_path):
    log = _write(tmp_path / "empty.jsonl", [])
    assert outbox_trace_script._to_tla(log, tmp_path / "o.tla") == 2


@pytest.mark.no_test_domain
def test_unknown_action_is_rejected(tmp_path):
    log = _write(
        tmp_path / "bad.jsonl",
        [{"action": "teleport", "worker": "w", "message": "m"}],
    )
    assert outbox_trace_script._to_tla(log, tmp_path / "o.tla") == 2


@pytest.mark.no_test_domain
def test_missing_required_field_is_rejected(tmp_path):
    # A missing "message" must reject cleanly, not raise a KeyError.
    log = _write(tmp_path / "missing.jsonl", [{"action": "claim", "worker": "w"}])
    assert outbox_trace_script._to_tla(log, tmp_path / "o.tla") == 2


@pytest.mark.no_test_domain
def test_non_scalar_id_is_rejected(tmp_path):
    # Workers/messages are mapped by identity, so a non-scalar id (list, dict, bool,
    # float, null) is malformed rather than stringified.
    for bad in ([1], {"a": 1}, True, 1.5, None):
        log = _write(
            tmp_path / "id.jsonl",
            [{"action": "claim", "worker": bad, "message": "m"}],
        )
        assert outbox_trace_script._to_tla(log, tmp_path / "o.tla") == 2, bad


@pytest.mark.no_test_domain
def test_publish_without_valid_outcome_is_rejected(tmp_path):
    # The model reads a publish outcome to pin the broker-receive branch, so a publish
    # without ok/fail is malformed.
    for outcome in (None, "maybe", "published"):
        log = _write(
            tmp_path / "pub.jsonl",
            [{"action": "publish", "worker": "w", "message": "m", "outcome": outcome}],
        )
        assert outbox_trace_script._to_tla(log, tmp_path / "o.tla") == 2, outcome


@pytest.mark.no_test_domain
def test_mark_without_valid_outcome_is_rejected(tmp_path):
    # The model reads a mark outcome to pin the terminal status, so a mark without a
    # valid status is malformed.
    for outcome in (None, "ok", "done"):
        log = _write(
            tmp_path / "mark.jsonl",
            [{"action": "mark", "worker": "w", "message": "m", "outcome": outcome}],
        )
        assert outbox_trace_script._to_tla(log, tmp_path / "o.tla") == 2, outcome


@pytest.mark.no_test_domain
def test_too_many_ids_is_rejected(tmp_path):
    # A runaway id count is malformed input, rejected rather than expanded into a
    # giant generated module.
    events = [
        {"action": "claim", "worker": f"w{i}", "message": "m"}
        for i in range(outbox_trace_script.MAX_IDS + 1)
    ]
    log = _write(tmp_path / "many.jsonl", events)
    assert outbox_trace_script._to_tla(log, tmp_path / "o.tla") == 2


@pytest.mark.no_test_domain
def test_invalid_json_line_is_rejected(tmp_path):
    (tmp_path / "broken.jsonl").write_text('{"action": oops}\n', encoding="utf-8")
    assert (
        outbox_trace_script._to_tla(tmp_path / "broken.jsonl", tmp_path / "o.tla") == 2
    )


@pytest.mark.no_test_domain
def test_non_object_line_is_rejected(tmp_path):
    (tmp_path / "scalar.jsonl").write_text("42\n", encoding="utf-8")
    assert (
        outbox_trace_script._to_tla(tmp_path / "scalar.jsonl", tmp_path / "o.tla") == 2
    )


@pytest.mark.no_test_domain
def test_witnesses_redelivery_needs_a_post_crash_republish():
    """The recorder's anti-vacuity guard: it only reports a witness when a message is
    published again *after* a crash while already published. check.sh drives this on
    the happy path only, so its branches would rot untested without these."""
    witnesses = outbox_trace_script._witnesses_redelivery

    # publish → crash → publish (same message): the redelivery window.
    assert witnesses(_redelivery_log())
    # No crash: a second publish of the same message is not a crash redelivery.
    assert not witnesses(
        [
            {"action": "publish", "worker": "w", "message": "m", "outcome": "ok"},
            {"action": "publish", "worker": "w", "message": "m", "outcome": "ok"},
        ]
    )
    # The republish is a failed publish: the broker did not receive it, so no witness.
    assert not witnesses(
        [
            {"action": "publish", "worker": "w", "message": "m", "outcome": "ok"},
            {"action": "crash", "worker": "w", "message": "m", "outcome": None},
            {"action": "publish", "worker": "w", "message": "m", "outcome": "fail"},
        ]
    )
    # The post-crash publish is a different, never-published message: no witness.
    assert not witnesses(
        [
            {"action": "publish", "worker": "w", "message": "m1", "outcome": "ok"},
            {"action": "crash", "worker": "w", "message": "m1", "outcome": None},
            {"action": "publish", "worker": "w", "message": "m2", "outcome": "ok"},
        ]
    )


@pytest.mark.no_test_domain
def test_converter_reads_the_recorder_schema_fields():
    # Guard against drift: the converter reads these keys by name off each event, so a
    # rename in OutboxEvent must be matched here or the script breaks at runtime.
    from protean.utils.outbox_trace import OutboxEvent

    assert set(OutboxEvent.__annotations__) == {
        "action",
        "worker",
        "message",
        "outcome",
    }
