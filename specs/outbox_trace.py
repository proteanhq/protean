#!/usr/bin/env python3
"""Generate and convert outbox trace logs for spec conformance checking.

Two subcommands, both driven by ``specs/check.sh``:

- ``record`` drives the real ``OutboxProcessor`` against the in-memory broker and
  outbox repository through the crash-redelivery shape, with the tracer in
  ``protean.utils.outbox_trace`` active, and writes the observed log as JSON lines.
  One worker claims a pending row and publishes it to the broker, then drops it
  before the mark commits (the crash). The claim lock lapses (the frozen clock is
  advanced past it), a second worker reclaims the still-PROCESSING row, publishes it
  again (the at-least-once duplicate), and marks it published. No external services
  are needed, so this runs anywhere ``protean`` imports.

- ``to-tla`` reads a JSON-lines log (a recorded one, or a checked-in fixture under
  ``specs/traces/``) and writes a runnable TLA+ module that binds it to
  ``OutboxTrace.tla``'s ``Trace`` constant (and the ``Messages`` / ``Workers`` /
  ``MaxRetries`` / ``MaxCrashes`` bounds it needs). ``check.sh`` then runs TLC over
  that module with ``OutboxTrace_conform.cfg`` and ``OutboxTrace_cover.cfg``.

The log schema is one object per observed transition, in order::

    {"action": "claim"|"publish"|"mark"|"crash"|"lock_expire",
     "worker": "<id>", "message": "<id>", "outcome": <str|null>}

``outcome`` is meaningful for ``publish`` (``"ok"``/``"fail"``) and ``mark``
(``"published"``/``"failed"``/``"abandoned"``); the model ignores it for every other
action. ``worker`` and ``message`` are opaque identifiers: the converter maps each
distinct value to a small integer (1..N), since the spec treats the id sets
abstractly.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

VALID_ACTIONS = ("claim", "publish", "mark", "crash", "lock_expire")

PUBLISH_OUTCOMES = ("ok", "fail")
MARK_OUTCOMES = ("published", "failed", "abandoned")

# Upper bound on the number of distinct workers or messages a log may name. The
# replay is a single deterministic behaviour, so a large count does not blow up TLC
# the way an enumerated constant would, but a fat-fingered fixture with runaway ids
# is still malformed input; this turns it into a clean error rather than a giant
# generated module.
MAX_IDS = 1000


def _record(out_path: Path) -> int:
    """Drive the real OutboxProcessor through the crash-redelivery shape and log it."""
    # Silence the framework's debug logging so the run's only output is the trace.
    logging.disable(logging.CRITICAL)

    # Imported here, not at module top, so the `to-tla` subcommand (which only needs
    # the stdlib) runs under a bare python3 without `protean` installed.
    import asyncio  # noqa: PLC0415
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from protean import Domain  # noqa: PLC0415
    from protean.core.unit_of_work import UnitOfWork  # noqa: PLC0415
    from protean.server import Engine  # noqa: PLC0415
    from protean.server.outbox_processor import OutboxProcessor  # noqa: PLC0415
    from protean.utils import outbox_trace  # noqa: PLC0415
    from protean.utils.eventing import (  # noqa: PLC0415
        DomainMeta,
        MessageHeaders,
        Metadata,
    )
    from protean.utils.outbox import Outbox  # noqa: PLC0415

    class _FrozenClock:
        """A domain clock pinned to a fixed instant, advanceable to expire the lock."""

        def __init__(self, instant: datetime) -> None:
            self._instant = instant

        def now(self) -> datetime:
            return self._instant

        def advance(self, delta: timedelta) -> None:
            self._instant += delta

    domain = Domain(name="Outbox trace", config={"identity_type": "uuid"})
    domain.config["enable_outbox"] = True
    domain.config["server"]["default_subscription_type"] = "stream"
    domain.init(traverse=False)

    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    domain.clock = clock

    async def drive() -> list[dict[str, Any]]:
        with domain.domain_context():
            outbox_repo = domain._get_outbox_repo("default")

            # A single pending row, built the same way the framework's write path
            # does (headers + domain metadata), so the real publish can reconstruct
            # a Message from it.
            headers = MessageHeaders(
                id="outbox-trace-1", type="DummyEvent", stream="test-stream"
            )
            metadata = Metadata(
                headers=headers, domain=DomainMeta(stream_category="test-stream")
            )
            with UnitOfWork():
                outbox_repo.add(
                    Outbox.create_message(
                        message_id="outbox-trace-1",
                        stream_name="test-stream",
                        message_type="DummyEvent",
                        data={"value": 1},
                        metadata=metadata,
                    )
                )

            engine = Engine(domain=domain, test_mode=False)

            def make_processor(worker_id: str) -> OutboxProcessor:
                return OutboxProcessor(
                    engine=engine,
                    database_provider_name="default",
                    broker_provider_name="default",
                    worker_id=worker_id,
                )

            worker1 = make_processor("outbox-worker-1")
            worker2 = make_processor("outbox-worker-2")
            await worker1.initialize()
            await worker2.initialize()

            with outbox_trace.capture() as events:
                # First worker: claim the row and publish it to the broker, then
                # crash before the mark commits. The row stays PROCESSING under a
                # live lock; the broker has already received the message.
                batch = await worker1.get_next_batch_of_messages()  # emits claim
                if len(batch) != 1:
                    raise RuntimeError(f"expected 1 claimed row, got {len(batch)}")
                success, error = await worker1._publish_message(batch[0])  # emits pub
                if not success:
                    raise RuntimeError(f"first publish failed: {error!r}")

                # Crash: the worker drops the message mid-flight without marking it. A
                # crash is a process event, not a code branch, so the harness records
                # it (naming the worker and the row it held).
                row_id = str(batch[0].id)
                outbox_trace.record(
                    action="crash", worker="outbox-worker-1", message=row_id
                )

                # The claim lock lapses: advance the frozen clock past locked_until so
                # the PROCESSING row becomes reclaimable. Like the crash, a lock
                # expiry is a time event the harness records.
                clock.advance(timedelta(minutes=10))
                outbox_trace.record(
                    action="lock_expire", worker="outbox-worker-1", message=row_id
                )

                # Second worker: reclaim the expired row, publish it again (the
                # at-least-once duplicate the broker now receives twice), and mark it
                # published.
                batch2 = await worker2.get_next_batch_of_messages()  # emits claim
                if len(batch2) != 1:
                    raise RuntimeError(f"expected 1 reclaimed row, got {len(batch2)}")
                # emits publish (duplicate) and mark (published)
                if not await worker2._process_single_message(batch2[0]):
                    raise RuntimeError("second pass did not publish successfully")

                return [dict(event) for event in events]

    recorded = asyncio.run(drive())

    # A partial or misshapen recording would still often conform, so it must fail
    # loudly rather than pass an under-covered log off as a real run. The oracle
    # depends on: a terminal published mark happened (else a regressed mark emit
    # would sail through, since an unmarked row still conforms and still witnesses
    # the duplicate), a crash happened, and a message was published again after the
    # crash while already published (the redelivery the coverage check must witness).
    actions = [event["action"] for event in recorded]
    problems: list[str] = []
    if not any(
        event["action"] == "mark" and event.get("outcome") == "published"
        for event in recorded
    ):
        problems.append("no terminal published mark was recorded")
    if "crash" not in actions:
        problems.append("no crash was recorded")
    if not _witnesses_redelivery(recorded):
        problems.append(
            "no message was re-published after a crash while already published"
        )
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    _write_jsonl(out_path, recorded)
    print(f"recorded {len(recorded)} events to {out_path}")
    return 0


def _witnesses_redelivery(events: list[dict[str, Any]]) -> bool:
    """Whether the log re-publishes an already-published message after a crash.

    That is the exact window the protocol exists for and the coverage check must
    witness: a message is published to the broker, a crash happens, and the same
    message is published again (the at-least-once duplicate).
    """
    published: set[str] = set()
    crashed = False
    for event in events:
        action = event["action"]
        if action == "crash":
            crashed = True
        elif action == "publish" and event.get("outcome") == "ok":
            message = event["message"]
            if crashed and message in published:
                return True
            published.add(message)
    return False


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Parse a JSON-lines file, raising :class:`ValueError` on an invalid line.

    A syntactically-broken line is malformed input, so it is reported with its line
    number for the caller to reject cleanly, rather than crashing the converter.
    """
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"line {index}: invalid JSON: {exc}") from None
    return events


def _identity(value: object, name: str) -> str:
    """Return an opaque string identifier, or raise :class:`ValueError`.

    Workers and messages are mapped to small integers by identity. The recorder
    always emits them as strings (``str(row.id)`` / ``worker_id``), so the converter
    requires a string here: accepting an int as well would let ``1`` and ``"1"`` map
    to the same id, an ambiguity a string-only contract removes. A non-string is
    malformed input, rejected rather than coerced into a value that would surface
    later as a confusing TLC failure.
    """
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string id")
    return value


def _parse_event(event: object) -> tuple[str, str, str, str | None]:
    """Validate one recorded event and return ``(action, worker, message, outcome)``.

    Raises :class:`ValueError` with a readable message on any malformed input (not a
    JSON object, a missing field, an unknown action, a non-string id, or a publish /
    mark whose outcome is missing or out of range), so the caller can reject the
    whole log cleanly instead of crashing on a raw ``KeyError``/``ValueError``.
    """
    if not isinstance(event, dict):
        raise ValueError("event is not a JSON object")
    missing = {"action", "worker", "message"} - event.keys()
    if missing:
        raise ValueError(f"missing field(s) {sorted(missing)}")
    action = event["action"]
    if action not in VALID_ACTIONS:
        raise ValueError(f"bad action {action!r}")
    worker = _identity(event["worker"], "worker")
    message = _identity(event["message"], "message")
    outcome = event.get("outcome")
    # The model reads ``outcome`` only on publish (to pin the broker-receive branch)
    # and mark (to pin the terminal status), so those must carry a valid one. Every
    # other action ignores it, so a missing value there is fine.
    if action == "publish":
        if outcome not in PUBLISH_OUTCOMES:
            raise ValueError(f"publish event needs outcome in {PUBLISH_OUTCOMES}")
    elif action == "mark":
        if outcome not in MARK_OUTCOMES:
            raise ValueError(f"mark event needs outcome in {MARK_OUTCOMES}")
    else:
        outcome = None
    return action, worker, message, outcome


def _to_tla(in_path: Path, out_path: Path) -> int:
    """Convert a JSON-lines outbox log into a runnable OutboxTrace_* TLA+ module."""
    try:
        events = _read_jsonl(in_path)
    except ValueError as exc:
        print(f"error: {in_path} {exc}", file=sys.stderr)
        return 2
    if not events:
        print(f"error: {in_path} has no events", file=sys.stderr)
        return 2

    parsed: list[tuple[str, str, str, str | None]] = []
    workers: dict[str, int] = {}
    messages: dict[str, int] = {}
    fail_marks: dict[str, int] = {}
    crashes = 0
    for index, event in enumerate(events, start=1):
        try:
            action, worker, message, outcome = _parse_event(event)
        except ValueError as exc:
            print(f"error: {in_path} line {index}: {exc}", file=sys.stderr)
            return 2
        # First-seen order gives a stable 1..N mapping; the exact integers do not
        # matter since the spec uses the id sets abstractly.
        workers.setdefault(worker, len(workers) + 1)
        messages.setdefault(message, len(messages) + 1)
        if action == "crash":
            crashes += 1
        if action == "mark" and outcome in ("failed", "abandoned"):
            fail_marks[message] = fail_marks.get(message, 0) + 1
        parsed.append((action, worker, message, outcome))

    if len(workers) > MAX_IDS or len(messages) > MAX_IDS:
        print(
            f"error: {in_path} names too many ids "
            f"(workers={len(workers)}, messages={len(messages)}, cap={MAX_IDS})",
            file=sys.stderr,
        )
        return 2

    records = []
    for action, worker, message, outcome in parsed:
        # Every record carries an ``outcome`` field for a uniform shape; the replay
        # reads it only for publish and mark, so "none" is an inert placeholder.
        records.append(
            f'    [action |-> "{action}", worker |-> {workers[worker]}, '
            f"msg |-> {messages[message]}, "
            f'outcome |-> "{outcome if outcome is not None else "none"}"]'
        )

    # Outbox requires MaxRetries >= 1. A message reaches ABANDONED exactly when its
    # failing-mark count hits MaxRetries, so the bound must cover the deepest retry
    # ladder any message walked (floored at 1). The crash-redelivery scenario never
    # fails a publish, so retry stays 0 and this is 1.
    max_retries = max([1, *fail_marks.values()])

    module = out_path.stem
    trace_def = " <<\n" + ",\n".join(records) + "\n>>"

    body = (
        f"---- MODULE {module} ----\n"
        "\\* Generated by specs/outbox_trace.py from a recorded outbox log. Do not\n"
        "\\* edit; regenerate from the JSON-lines source instead.\n"
        "EXTENDS OutboxTrace\n\n"
        f"TraceDef =={trace_def}\n\n"
        f"MessagesDef == 1..{len(messages)}\n\n"
        f"WorkersDef == 1..{len(workers)}\n\n"
        f"MaxRetriesDef == {max_retries}\n\n"
        f"MaxCrashesDef == {crashes}\n"
        "====\n"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    print(f"wrote {out_path} ({len(records)} events)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="record a real outbox trace")
    record.add_argument("--out", type=Path, required=True, help="JSON-lines output")

    convert = subparsers.add_parser("to-tla", help="convert a log to a TLA+ module")
    convert.add_argument("--in", dest="in_path", type=Path, required=True)
    convert.add_argument("--out", type=Path, required=True, help="OutboxTrace_*.tla")

    args = parser.parse_args(argv)
    if args.command == "record":
        return _record(args.out)
    return _to_tla(args.in_path, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
