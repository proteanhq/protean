#!/usr/bin/env python3
"""Generate and convert recovery trace logs for spec conformance checking.

Two subcommands, both driven by ``specs/check.sh``:

- ``record`` drives the real ``EventStoreSubscription`` against the Memory event
  store through the record-before-advance shape, with the tracer in
  ``protean.utils.recovery_trace`` active, and writes the observed log as JSON
  lines. A handler fails on a message, the failure is recorded durably, the cursor
  advances (but is not durably flushed — ``position_update_interval`` is kept high),
  the subscription is dropped and rebuilt against the same store (the crash-resume),
  the message is re-read and fails again (the redelivery), and a recovery pass then
  resolves it. No external services are needed, so this runs anywhere ``protean``
  imports.

- ``to-tla`` reads a JSON-lines log (a recorded one, or a checked-in fixture under
  ``specs/traces/``) and writes a runnable TLA+ module that binds it to
  ``RecoveryTrace.tla``'s ``Trace`` constant (and the ``N`` / ``MaxCrashes`` bounds
  it needs). ``check.sh`` then runs TLC over that module with
  ``RecoveryTrace_conform.cfg`` and ``RecoveryTrace_cover.cfg``.

The log schema is one object per observed transition, in order::

    {"action": "handle_ok"|"fail"|"record"|"advance"|"flush"|"recover"|"crash",
     "position": <int>, "delivered": <bool|null>}

``delivered`` is meaningful only for ``recover`` (``true`` = resolved, ``false`` =
exhausted); the model ignores it for every other action. ``position`` is the global
position the transition concerns (the durable cursor for ``flush``/``crash``, which
the model ignores there).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

VALID_ACTIONS = (
    "handle_ok",
    "fail",
    "record",
    "advance",
    "flush",
    "recover",
    "crash",
)

# Actions that name a real message position (1..N). flush/crash carry the durable
# cursor, which the model ignores, so they do not raise N.
POSITIONAL_ACTIONS = ("handle_ok", "fail", "record", "advance", "recover")


def _record(out_path: Path) -> int:
    """Drive the real EventStoreSubscription through the recovery shape and log it."""
    # Silence the framework's debug logging so the run's only output is the trace.
    logging.disable(logging.CRITICAL)

    # Imported here, not at module top, so the `to-tla` subcommand (which only needs
    # the stdlib) runs under a bare python3 without `protean` installed.
    from protean import Domain, apply  # noqa: PLC0415
    from protean.core.aggregate import BaseAggregate  # noqa: PLC0415
    from protean.core.event import BaseEvent  # noqa: PLC0415
    from protean.core.event_handler import BaseEventHandler  # noqa: PLC0415
    from protean.fields import Identifier, String  # noqa: PLC0415
    from protean.server import Engine  # noqa: PLC0415
    from protean.utils import recovery_trace  # noqa: PLC0415
    from protean.utils.eventing import (  # noqa: PLC0415
        EventStoreMeta,
        Message,
        Metadata,
    )
    from protean.utils.mixins import handle  # noqa: PLC0415

    class Registered(BaseEvent):
        id = Identifier()
        email = String()
        name = String()

    # ``@apply`` resolves its event annotation via ``get_type_hints`` against the
    # module globals, not this function's locals, so publish the nested event class
    # there (the module-level definition the aggregate suite relies on, done inline).
    globals()["Registered"] = Registered

    class User(BaseAggregate):
        email = String()
        name = String()

        @apply
        def on_registered(self, event: Registered) -> None:
            self.email = event.email
            self.name = event.name

    class RecoveringHandler(BaseEventHandler):
        # Fail on the first read and again on the crash-resume re-read (the
        # redelivery), then succeed on the recovery-pass retry. Two failures then a
        # success is the minimal shape that lands a crash between record and advance.
        remaining_failures = 2

        @handle(Registered)
        def handle_registered(self, event: Registered) -> None:
            if RecoveringHandler.remaining_failures > 0:
                RecoveringHandler.remaining_failures -= 1
                raise RuntimeError("transient handler failure")

    domain = Domain(name="Recovery trace", config={"identity_type": "uuid"})
    domain.register(User, event_sourced=True)
    domain.register(Registered, part_of=User)
    domain.register(RecoveringHandler, part_of=User)
    domain.init(traverse=False)

    user_id = "recovery-trace-user"
    stream_name = f"test-{user_id}"

    def build_message() -> Message:
        user = User(id=user_id, email="test@example.com", name="Test")
        user.raise_(Registered(id=user_id, email="test@example.com", name="Test"))
        event = user._events[-1]
        message = Message.from_domain_object(event)
        metadata_dict = message.metadata.to_dict()
        metadata_dict["event_store"] = EventStoreMeta(position=0, global_position=1)
        metadata_dict["domain"]["asynchronous"] = True
        if metadata_dict.get("headers"):
            metadata_dict["headers"]["stream"] = stream_name
        else:
            metadata_dict["headers"] = {"stream": stream_name}
        message.metadata = Metadata(**metadata_dict)
        return message

    def make_subscription() -> Any:
        from protean.server.subscription.event_store_subscription import (  # noqa: PLC0415
            EventStoreSubscription,
        )

        engine = Engine(domain=domain, test_mode=False)
        return EventStoreSubscription(
            engine,
            "test",
            RecoveringHandler,
            messages_per_tick=10,
            # High enough that the durable cursor never flushes before the crash,
            # which is what lands the crash between record and advance.
            position_update_interval=100,
            max_retries=3,
            enable_recovery=True,
            recovery_interval_seconds=0,
            retry_delay_seconds=0,
        )

    async def drive() -> list[dict[str, Any]]:
        with domain.domain_context():
            store = domain.event_store.store
            msg = build_message()
            # Persist the event so the crash-resume re-read and the recovery pass can
            # read it back from the store.
            store._write(
                stream_name,
                msg.metadata.headers.type,
                msg.data,
                metadata=msg.metadata.to_dict(),
            )

            with recovery_trace.capture() as events:
                # First pass: the handler fails, the failure is recorded durably, and
                # the cursor advances (no durable flush — interval is high).
                sub = make_subscription()
                await sub.process_batch([msg])

                # Crash: drop the subscription and rebuild it against the same store.
                # The durable cursor never flushed, so the rebuilt cursor is behind
                # the failed position. A crash is a process event, not a code branch,
                # so the harness records it.
                recovery_trace.record(action="crash", position=0)
                sub2 = make_subscription()
                await sub2._rebuild_retry_counts()

                # Re-read: the message is re-read and fails again (the at-least-once
                # redelivery of an already-recorded failed position).
                await sub2.process_batch([msg])

                # Recovery pass: the retry succeeds and the position is resolved.
                await sub2.run_recovery_pass()

                return [dict(event) for event in events]

    RecoveringHandler.remaining_failures = 2
    recorded = asyncio.run(drive())

    # A partial or misshapen recording would still often conform, so it must fail
    # loudly rather than pass an under-covered log off as a real run. The three
    # things the oracle depends on: a crash happened, the recovery pass resolved the
    # position, and a failed position was re-read *after* the crash while it was
    # already recorded (the redelivery the coverage check must witness).
    actions = [event["action"] for event in recorded]
    problems: list[str] = []
    if "crash" not in actions:
        problems.append("no crash was recorded")
    if not any(
        event["action"] == "recover" and event.get("delivered") is True
        for event in recorded
    ):
        problems.append("no resolved recovery-pass outcome was recorded")
    if not _witnesses_redelivery(recorded):
        problems.append(
            "no failed position was re-read after a crash while already recorded"
        )
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    _write_jsonl(out_path, recorded)
    print(f"recorded {len(recorded)} events to {out_path}")
    return 0


def _witnesses_redelivery(events: list[dict[str, Any]]) -> bool:
    """Whether the log re-reads a recorded failed position after a crash.

    That is the exact window the protocol exists for and the coverage check must
    witness: a position is recorded, a crash happens, and the position fails again
    (a re-read) with its durable record already in place.
    """
    recorded: set[int] = set()
    crashed = False
    for event in events:
        action = event["action"]
        position = event["position"]
        if action == "record":
            recorded.add(position)
        elif action == "crash":
            crashed = True
        elif action == "fail" and crashed and position in recorded:
            return True
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


def _natural(value: object, name: str) -> int:
    """Return ``value`` as a non-negative integer, or raise :class:`ValueError`.

    JSON numbers parse to ``int`` or ``float``, so this rejects floats, negatives,
    and booleans rather than coercing them into a value that would surface later as a
    confusing TLC failure.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _parse_event(event: object) -> tuple[str, int, bool]:
    """Validate one recorded event and return ``(action, position, delivered)``.

    Raises :class:`ValueError` with a readable message on any malformed input (not a
    JSON object, a missing field, an unknown action, a non-integer position, or a
    ``recover`` without a boolean ``delivered``), so the caller can reject the whole
    log cleanly instead of crashing on a raw ``KeyError``/``ValueError``.
    """
    if not isinstance(event, dict):
        raise ValueError("event is not a JSON object")
    missing = {"action", "position"} - event.keys()
    if missing:
        raise ValueError(f"missing field(s) {sorted(missing)}")
    action = event["action"]
    if action not in VALID_ACTIONS:
        raise ValueError(f"bad action {action!r}")
    position = _natural(event["position"], "position")
    delivered = event.get("delivered")
    # The model reads ``delivered`` only on a recover, where it pins the retry
    # verdict, so a recover without a boolean is malformed. Every other action
    # ignores it, so a missing value there is fine and defaults to FALSE.
    if action == "recover":
        if not isinstance(delivered, bool):
            raise ValueError("recover event without a boolean delivered")
    else:
        delivered = False
    return action, position, delivered


def _to_tla(in_path: Path, out_path: Path) -> int:
    """Convert a JSON-lines recovery log into a runnable RecoveryTrace_* module."""
    try:
        events = _read_jsonl(in_path)
    except ValueError as exc:
        print(f"error: {in_path} {exc}", file=sys.stderr)
        return 2
    if not events:
        print(f"error: {in_path} has no events", file=sys.stderr)
        return 2

    records = []
    max_position = 0
    crashes = 0
    for index, event in enumerate(events, start=1):
        try:
            action, position, delivered = _parse_event(event)
        except ValueError as exc:
            print(f"error: {in_path} line {index}: {exc}", file=sys.stderr)
            return 2
        if action in POSITIONAL_ACTIONS:
            max_position = max(max_position, position)
        if action == "crash":
            crashes += 1
        records.append(
            f'    [action |-> "{action}", pos |-> {position}, '
            f"delivered |-> {'TRUE' if delivered else 'FALSE'}]"
        )

    # Recovery requires N >= 1, so floor the highest position at 1 for a log that
    # only ever touched position 1 (or, defensively, none).
    n = max(max_position, 1)

    module = out_path.stem
    trace_def = " <<\n" + ",\n".join(records) + "\n>>"

    body = (
        f"---- MODULE {module} ----\n"
        "\\* Generated by specs/recovery_trace.py from a recorded recovery log. Do\n"
        "\\* not edit; regenerate from the JSON-lines source instead.\n"
        "EXTENDS RecoveryTrace\n\n"
        f"TraceDef =={trace_def}\n\n"
        f"NDef == {n}\n\n"
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

    record = subparsers.add_parser("record", help="record a real recovery trace")
    record.add_argument("--out", type=Path, required=True, help="JSON-lines output")

    convert = subparsers.add_parser("to-tla", help="convert a log to a TLA+ module")
    convert.add_argument("--in", dest="in_path", type=Path, required=True)
    convert.add_argument("--out", type=Path, required=True, help="RecoveryTrace_*.tla")

    args = parser.parse_args(argv)
    if args.command == "record":
        return _record(args.out)
    return _to_tla(args.in_path, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
