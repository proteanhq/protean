"""Trace-validation harness for the recovery protocol (:issue:`#1385`).

Three layers, matching the OCC harness (#1382):

- the recorder in ``protean.utils.recovery_trace`` — a diagnostic seam, inactive by
  default, activated by a process-wide :func:`~protean.utils.recovery_trace.capture`;
- the instrumentation on the real ``EventStoreSubscription`` recovery path, which
  must emit the spec's transitions when a capture is active and nothing otherwise;
- the ``specs/recovery_trace.py`` log-to-TLA+ converter and its reject branches,
  which ``check.sh`` only exercises on the happy path so its guards would rot here.

The three ``check.sh`` outcomes (a real trace accepted, the divergence fixture
rejected on conformance, the no-crash fixture rejected on coverage) are the machine
oracle; these tests pin the Python contracts underneath it.
"""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.event_store_subscription import EventStoreSubscription
from protean.utils import recovery_trace
from protean.utils.eventing import EventStoreMeta, Message, Metadata
from protean.utils.mixins import handle

# ──────────────────────────────────────────────────────────────────────
# Recorder unit tests (pure — no domain, mirroring the occ_trace tests)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.no_test_domain
def test_inactive_by_default():
    assert recovery_trace.is_active() is False


@pytest.mark.no_test_domain
def test_record_is_a_noop_when_inactive():
    recovery_trace.record(action="fail", position=1)
    assert recovery_trace.is_active() is False


@pytest.mark.no_test_domain
def test_capture_activates_collects_and_restores():
    assert recovery_trace.is_active() is False
    with recovery_trace.capture() as events:
        assert recovery_trace.is_active() is True
        recovery_trace.record(action="fail", position=1)
        recovery_trace.record(action="record", position=1)
        recovery_trace.record(action="recover", position=1, delivered=True)
    assert recovery_trace.is_active() is False
    assert events == [
        {"action": "fail", "position": 1, "delivered": None},
        {"action": "record", "position": 1, "delivered": None},
        {"action": "recover", "position": 1, "delivered": True},
    ]


@pytest.mark.no_test_domain
def test_capture_restores_even_on_error():
    with pytest.raises(RuntimeError):
        with recovery_trace.capture():
            assert recovery_trace.is_active() is True
            raise RuntimeError("boom")
    assert recovery_trace.is_active() is False


@pytest.mark.no_test_domain
def test_nested_captures_do_not_leak():
    with recovery_trace.capture() as outer:
        recovery_trace.record(action="fail", position=1)
        with recovery_trace.capture() as inner:
            recovery_trace.record(action="fail", position=2)
        assert [e["position"] for e in inner] == [2]
        assert recovery_trace.is_active() is True
        recovery_trace.record(action="advance", position=1)
    assert [e["action"] for e in outer] == ["fail", "advance"]
    assert recovery_trace.is_active() is False


# ──────────────────────────────────────────────────────────────────────
# Instrumentation tests (drive the real EventStoreSubscription)
# ──────────────────────────────────────────────────────────────────────


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()


class User(BaseAggregate):
    email = String()
    name = String()

    @apply
    def on_registered(self, event: Registered) -> None:
        self.email = event.email
        self.name = event.name


_fail_budget = 0  # module-level so the handler's failures are controllable per test


class BudgetedHandler(BaseEventHandler):
    """Fails while a shared budget remains, then succeeds — a transient handler."""

    @handle(Registered)
    def handle_registered(self, event):
        global _fail_budget
        if _fail_budget > 0:
            _fail_budget -= 1
            raise RuntimeError("transient failure")


class AlwaysFailingHandler(BaseEventHandler):
    @handle(Registered)
    def handle_registered(self, event):
        raise RuntimeError("permanent failure")


class SucceedingHandler(BaseEventHandler):
    @handle(Registered)
    def handle_registered(self, event):
        pass


@pytest.fixture(autouse=True)
def _reset_budget():
    global _fail_budget
    _fail_budget = 0


@pytest.fixture
def register(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(BudgetedHandler, part_of=User)
    test_domain.register(AlwaysFailingHandler, part_of=User)
    test_domain.register(SucceedingHandler, part_of=User)
    test_domain.init(traverse=False)
    return test_domain


def _create_message(
    global_position: int = 1,
    stream_position: int = 0,
    idempotency_key: str | None = None,
) -> Message:
    user_id = str(uuid4())
    stream_name = f"test-{user_id}"
    user = User(id=user_id, email="test@example.com", name="Test")
    user.raise_(Registered(id=user_id, email="test@example.com", name="Test"))
    event = user._events[-1]
    message = Message.from_domain_object(event)
    metadata_dict = message.metadata.to_dict()
    metadata_dict["event_store"] = EventStoreMeta(
        position=stream_position, global_position=global_position
    )
    metadata_dict["domain"]["asynchronous"] = True
    if metadata_dict.get("headers"):
        metadata_dict["headers"]["stream"] = stream_name
    else:
        metadata_dict["headers"] = {"stream": stream_name}
    if idempotency_key is not None:
        metadata_dict["headers"]["idempotency_key"] = idempotency_key
    message.metadata = Metadata(**metadata_dict)
    return message


def _make_subscription(test_domain, handler_cls, **kwargs) -> EventStoreSubscription:
    engine = Engine(domain=test_domain, test_mode=False)
    defaults = {
        "messages_per_tick": 10,
        "position_update_interval": 100,
        "max_retries": 3,
        "enable_recovery": True,
        "recovery_interval_seconds": 0,
        "retry_delay_seconds": 0,
    }
    defaults.update(kwargs)
    return EventStoreSubscription(engine, "test", handler_cls, **defaults)


def _write_event(test_domain, msg: Message) -> None:
    test_domain.event_store.store._write(
        msg.metadata.headers.stream,
        msg.metadata.headers.type,
        msg.data,
        metadata=msg.metadata.to_dict(),
    )


@pytest.mark.asyncio
async def test_failure_emits_fail_record_advance_in_order(register):
    """A handler failure emits, in order, the fail, the durable record, and the
    cursor advance for that position — the spec's Fail, Record, Advance."""
    sub = _make_subscription(register, AlwaysFailingHandler)
    msg = _create_message(global_position=1)

    with recovery_trace.capture() as events:
        await sub.process_batch([msg])

    assert [e["action"] for e in events] == ["fail", "record", "advance"]
    assert all(e["position"] == 1 for e in events)


@pytest.mark.asyncio
async def test_recovery_pass_emits_recover_with_delivered_outcome(register):
    """A recovery pass that resolves a position emits a recover with delivered=True;
    one that exhausts emits delivered=False."""
    global _fail_budget

    # Transient: fails the first handle, succeeds on the recovery retry → resolved.
    _fail_budget = 1
    sub = _make_subscription(register, BudgetedHandler)
    msg = _create_message(global_position=1)
    _write_event(register, msg)
    with recovery_trace.capture() as events:
        await sub.process_batch([msg])
        await sub.run_recovery_pass()
    recovers = [e for e in events if e["action"] == "recover"]
    assert recovers == [{"action": "recover", "position": 1, "delivered": True}]

    # Permanent, max_retries=0: the first recovery pass exhausts → not delivered.
    sub2 = _make_subscription(register, AlwaysFailingHandler, max_retries=0)
    msg2 = _create_message(global_position=1)
    _write_event(register, msg2)
    with recovery_trace.capture() as events2:
        await sub2.process_batch([msg2])
        await sub2.run_recovery_pass()
    recovers2 = [e for e in events2 if e["action"] == "recover"]
    assert recovers2 == [{"action": "recover", "position": 1, "delivered": False}]


@pytest.mark.asyncio
async def test_crash_resume_redelivers_recorded_failed_position(register):
    """Dropping and rebuilding the subscription before the durable cursor flushes
    re-reads the recorded failed position: a second fail lands after the crash while
    the position is already recorded — the redelivery the coverage check witnesses."""
    global _fail_budget
    _fail_budget = 2  # fail the first read and the crash-resume re-read, then resolve

    msg = _create_message(global_position=1)
    _write_event(register, msg)

    with recovery_trace.capture() as events:
        sub = _make_subscription(register, BudgetedHandler)
        await sub.process_batch([msg])  # fail, record, advance (no durable flush)

        recovery_trace.record(action="crash", position=0)
        sub2 = _make_subscription(register, BudgetedHandler)
        await sub2._rebuild_retry_counts()
        await sub2.process_batch([msg])  # re-read: fails again (already recorded)
        await sub2.run_recovery_pass()  # retry succeeds → resolved

    actions = [e["action"] for e in events]
    assert actions == [
        "fail",
        "record",
        "advance",
        "crash",
        "fail",
        "record",
        "advance",
        "recover",
    ]
    # The second fail is the redelivery: it follows the crash and a durable record
    # of the same position.
    crash_at = actions.index("crash")
    assert "record" in actions[:crash_at]
    assert "fail" in actions[crash_at:]


@pytest.mark.asyncio
async def test_successful_batch_emits_only_handle_ok(register):
    """A fully successful batch emits only handle_ok entries — never a record or an
    advance-past-a-failure (the boundary-only contract, negative side)."""
    sub = _make_subscription(register, SucceedingHandler)
    messages = [_create_message(global_position=p) for p in (1, 2, 3)]

    with recovery_trace.capture() as events:
        await sub.process_batch(messages)

    assert [e["action"] for e in events] == ["handle_ok", "handle_ok", "handle_ok"]
    assert [e["position"] for e in events] == [1, 2, 3]
    assert not any(e["action"] in ("fail", "record", "advance") for e in events)


class _ActiveIdempotencyStore:
    """Idempotency store stub that reports every key as already processed."""

    @property
    def is_active(self) -> bool:
        return True

    def check(self, idempotency_key: str) -> dict:
        return {"status": "success"}

    def record_success(self, idempotency_key: str, value: bool) -> None:
        pass


@pytest.mark.asyncio
async def test_idempotent_skip_emits_handle_ok(register, monkeypatch):
    """A message skipped as already-processed (idempotent) is a non-failed advance:
    it emits handle_ok and never calls the handler, so no fail is emitted."""
    sub = _make_subscription(register, AlwaysFailingHandler)
    monkeypatch.setattr(
        sub.engine.domain, "_idempotency_store", _ActiveIdempotencyStore()
    )
    msg = _create_message(global_position=1, idempotency_key="idem-1")

    with recovery_trace.capture() as events:
        result = await sub.process_batch([msg])

    assert result == 1  # counted as a (skipped) success
    assert [e["action"] for e in events] == ["handle_ok"]
    assert events[0]["position"] == 1


@pytest.mark.asyncio
async def test_recovery_disabled_emits_advance_without_a_record(register):
    """With recovery disabled, a failed message is intentionally dropped: the log
    shows the fail and the advance but no durable record between them."""
    sub = _make_subscription(register, AlwaysFailingHandler, enable_recovery=False)
    msg = _create_message(global_position=1)

    with recovery_trace.capture() as events:
        await sub.process_batch([msg])

    assert [e["action"] for e in events] == ["fail", "advance"]
    assert not any(e["action"] == "record" for e in events)


# ──────────────────────────────────────────────────────────────────────
# Converter tests (specs/recovery_trace.py to-tla and its reject branches)
# ──────────────────────────────────────────────────────────────────────

_SPEC = Path(__file__).resolve().parents[2] / "specs" / "recovery_trace.py"
_module_spec = importlib.util.spec_from_file_location("specs_recovery_trace", _SPEC)
recovery_trace_script = importlib.util.module_from_spec(_module_spec)
_module_spec.loader.exec_module(recovery_trace_script)


def _write(path: Path, events: list[dict]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


@pytest.mark.no_test_domain
def test_valid_log_converts_to_a_runnable_module(tmp_path):
    log = _write(
        tmp_path / "log.jsonl",
        [
            {"action": "fail", "position": 2},
            {"action": "record", "position": 2},
            {"action": "crash", "position": 0},
            {"action": "fail", "position": 2},
            {"action": "advance", "position": 2},
            {"action": "recover", "position": 2, "delivered": True},
        ],
    )
    out = tmp_path / "RecoveryTrace_run.tla"

    assert recovery_trace_script._to_tla(log, out) == 0

    text = out.read_text(encoding="utf-8")
    assert "---- MODULE RecoveryTrace_run ----" in text
    assert "EXTENDS RecoveryTrace" in text
    assert 'action |-> "fail", pos |-> 2, delivered |-> FALSE' in text
    assert 'action |-> "recover", pos |-> 2, delivered |-> TRUE' in text
    assert "NDef == 2" in text  # highest message position
    assert "MaxCrashesDef == 1" in text  # one crash entry


@pytest.mark.no_test_domain
def test_empty_log_is_rejected(tmp_path):
    log = _write(tmp_path / "empty.jsonl", [])
    assert recovery_trace_script._to_tla(log, tmp_path / "o.tla") == 2


@pytest.mark.no_test_domain
def test_unknown_action_is_rejected(tmp_path):
    log = _write(tmp_path / "bad.jsonl", [{"action": "teleport", "position": 1}])
    assert recovery_trace_script._to_tla(log, tmp_path / "o.tla") == 2


@pytest.mark.no_test_domain
def test_missing_required_field_is_rejected(tmp_path):
    # Missing "position" must reject cleanly, not raise a KeyError.
    log = _write(tmp_path / "missing.jsonl", [{"action": "fail"}])
    assert recovery_trace_script._to_tla(log, tmp_path / "o.tla") == 2


@pytest.mark.no_test_domain
def test_negative_and_float_positions_are_rejected(tmp_path):
    for bad in (-1, 1.5):
        log = _write(tmp_path / "nat.jsonl", [{"action": "fail", "position": bad}])
        assert recovery_trace_script._to_tla(log, tmp_path / "o.tla") == 2, bad


@pytest.mark.no_test_domain
def test_recover_without_boolean_delivered_is_rejected(tmp_path):
    # The model reads delivered only on a recover, to pin the retry verdict, so a
    # recover without a boolean is malformed rather than a defaulted value.
    log = _write(tmp_path / "rec.jsonl", [{"action": "recover", "position": 1}])
    assert recovery_trace_script._to_tla(log, tmp_path / "o.tla") == 2


@pytest.mark.no_test_domain
def test_non_recover_delivered_defaults_to_false(tmp_path):
    # A non-recover action ignores delivered, so a missing value is fine and the
    # generated record carries FALSE.
    log = _write(tmp_path / "fail.jsonl", [{"action": "fail", "position": 1}])
    out = tmp_path / "o.tla"
    assert recovery_trace_script._to_tla(log, out) == 0
    assert 'action |-> "fail", pos |-> 1, delivered |-> FALSE' in out.read_text(
        encoding="utf-8"
    )


@pytest.mark.no_test_domain
def test_invalid_json_line_is_rejected(tmp_path):
    (tmp_path / "broken.jsonl").write_text('{"action": oops}\n', encoding="utf-8")
    assert (
        recovery_trace_script._to_tla(tmp_path / "broken.jsonl", tmp_path / "o.tla")
        == 2
    )


@pytest.mark.no_test_domain
def test_non_object_line_is_rejected(tmp_path):
    (tmp_path / "scalar.jsonl").write_text("42\n", encoding="utf-8")
    assert (
        recovery_trace_script._to_tla(tmp_path / "scalar.jsonl", tmp_path / "o.tla")
        == 2
    )


@pytest.mark.no_test_domain
def test_converter_reads_the_recorder_schema_fields():
    # Guard against drift: the converter reads these keys by name off each event, so
    # a rename in RecoveryEvent must be matched here or the script breaks at runtime.
    from protean.utils.recovery_trace import RecoveryEvent

    assert set(RecoveryEvent.__annotations__) == {"action", "position", "delivered"}
