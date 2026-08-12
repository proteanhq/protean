#!/usr/bin/env python3
"""Generate and convert ``$all`` gap-safe checkpoint trace logs for spec checking.

Two subcommands, both driven by ``specs/check.sh``:

- ``record`` drives the real ``EventStoreSubscription._gap_safe_batch`` through an
  out-of-order commit interleaving (the same checkpoint execution model as the
  ``#1251`` no-skip property suite, via ``tests/verification/strategies.py``) with
  the tracer in ``protean.utils.checkpoint_trace`` active, and writes the observed
  log as JSON lines. The memory store cannot produce a real cross-category gap, so
  the gap is simulated by controlling the batch the subscription reads, exactly as
  ``tests/subscription/test_all_gap_safety.py`` documents. No external services are
  needed, so this runs anywhere ``protean`` imports.

- ``to-tla`` reads a JSON-lines log (a recorded one, or a checked-in fixture under
  ``specs/traces/``) and writes a runnable TLA+ module binding it to
  ``CheckpointTrace.tla``'s ``Trace`` and ``Fate`` constants and ``Checkpoint.tla``'s
  ``N``. ``check.sh`` then runs TLC over that module with the two cfgs.

The log schema is one object per ``_gap_safe_batch`` call, in call order::

    {"cursor": <int>, "present": [<int>...], "abandoned": [<int>...], "safe": <int>}

``cursor`` is the watermark the batch started from; ``present`` is the positions it
saw; ``abandoned`` is the holes it stepped over; ``safe`` is the watermark it
settled on. ``to-tla`` expands each batch into the atomic transitions the model
replays: a ``commit`` the first time a position is seen present, an ``abandon`` the
first time a hole is stepped over, and an ``advance`` for each real cursor move
(no-progress ticks, where ``safe`` did not pass the running cursor, are dropped).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any


def _record(out_path: Path) -> int:
    """Drive the real ``_gap_safe_batch`` through a gap interleaving and log it."""
    # Silence the framework's debug logging so the run's only output is the trace.
    logging.disable(logging.CRITICAL)

    # The #1251 checkpoint model lives under ``tests/``, which is not an installed
    # package, so put the repo root on the path before importing it. Run as a
    # script, ``sys.path[0]`` is ``specs/``, not the repo root.
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Imported here, not at module top, so the `to-tla` subcommand (which only
    # needs the stdlib) runs under a bare python3 without `protean` installed.
    from protean.utils import checkpoint_trace  # noqa: PLC0415
    from tests.verification.strategies import (  # noqa: PLC0415
        build_all_subscription,
        message_at,
        verification_domain,
    )

    with verification_domain.domain_context():
        sub = build_all_subscription()

    sub.current_position = 0
    sub._gap_first_seen = {}
    sub._gap_watermark = -1
    sub.gap_timeout_seconds = 5

    def drive(visible: list[int]) -> None:
        """One subscription read: feed the visible positions above the cursor to
        ``_gap_safe_batch`` and advance the cursor exactly as ``tick`` does."""
        returned = sub._gap_safe_batch([message_at(p) for p in visible])
        for message in returned:
            sub.current_position = message.metadata.event_store.global_position
        if sub._gap_watermark > sub.current_position:
            sub.current_position = sub._gap_watermark

    with checkpoint_trace.capture() as events:
        # Tick A: positions 1 and 3 have committed, 2 is still an open gap. The
        # subscription holds at 2 and delivers 1 — 3 is stranded above the
        # watermark (the out-of-order gap the coverage probe must witness).
        drive([1, 3])
        # Position 2 was a rolled-back append that will never commit; age its gap
        # timer past the timeout so the next batch abandons it (as
        # test_all_gap_safety.py simulates a permanent hole).
        sub._gap_first_seen = {2: time.monotonic() - 10 * sub.gap_timeout_seconds}
        # Tick B: 2 is abandoned, and 3 is delivered past it — the cursor resumes.
        drive([3])
        recorded = [dict(event) for event in events]

    # A recording that never stranded a position or never abandoned a hole would
    # still often conform, so it must fail loudly rather than pass a trace that does
    # not exercise the gap logic the check exists to validate.
    problems: list[str] = []
    if not recorded:
        problems.append("recorded no events")
    if not any(e["present"] and max(e["present"]) > e["safe"] for e in recorded):
        problems.append("no batch stranded a visible position above its watermark")
    if not any(e["abandoned"] for e in recorded):
        problems.append("no batch abandoned a hole")
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    _write_jsonl(out_path, recorded)
    print(f"recorded {len(recorded)} batch event(s) to {out_path}")
    return 0


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
    """Return ``value`` as a position number, or raise :class:`ValueError`.

    A position is a non-negative integer. JSON numbers parse to ``int`` or ``float``,
    so this rejects floats (``1.9``), negatives, and booleans rather than coercing
    them into a value that would surface later as a confusing TLC failure.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _naturals(value: object, name: str) -> list[int]:
    """Return ``value`` as a list of position numbers, or raise :class:`ValueError`."""
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return [_natural(item, f"{name} entry") for item in value]


def _parse_batch(event: object) -> tuple[int, list[int], list[int], int]:
    """Validate one recorded batch and return ``(cursor, present, abandoned, safe)``.

    Raises :class:`ValueError` with a readable message on any malformed input (not
    a JSON object, a missing field, or a non-integer / negative position), so the
    caller can reject the whole log cleanly instead of crashing on a raw
    ``KeyError``/``ValueError``.
    """
    if not isinstance(event, dict):
        raise ValueError("event is not a JSON object")
    missing = {"cursor", "present", "abandoned", "safe"} - event.keys()
    if missing:
        raise ValueError(f"missing field(s) {sorted(missing)}")
    cursor = _natural(event["cursor"], "cursor")
    present = _naturals(event["present"], "present")
    abandoned = _naturals(event["abandoned"], "abandoned")
    safe = _natural(event["safe"], "safe")
    return cursor, present, abandoned, safe


def _to_tla(in_path: Path, out_path: Path) -> int:
    """Convert a JSON-lines checkpoint log into a runnable CheckpointTrace_* module."""
    try:
        events = _read_jsonl(in_path)
    except ValueError as exc:
        print(f"error: {in_path} {exc}", file=sys.stderr)
        return 2
    if not events:
        print(f"error: {in_path} has no events", file=sys.stderr)
        return 2

    # Expand the raw batches into the atomic transitions the model replays. A
    # position is committed the first time it is seen present and abandoned the
    # first time it is stepped over; an advance is emitted only when the watermark
    # passes the running cursor (a no-progress hold maps to no Tick, so it is
    # dropped). Commits and abandons are emitted before the advance in each batch,
    # so the stranded-position state a gap produces is actually reached.
    transitions: list[str] = []
    committed_seen: set[int] = set()
    abandoned_seen: set[int] = set()
    cursor = 0
    for index, event in enumerate(events, start=1):
        try:
            entry_cursor, present, holes, safe = _parse_batch(event)
        except ValueError as exc:
            print(f"error: {in_path} line {index}: {exc}", file=sys.stderr)
            return 2
        # The replay reproduces a single monotonic cursor from 0, so each batch must
        # start where the previous one left off. A mismatch means a non-contiguous
        # log (e.g. two runs spliced, or a crash-resume this converter does not
        # model), which would expand to a Trace the replay cannot reproduce.
        if entry_cursor != cursor:
            print(
                f"error: {in_path} line {index}: batch starts at cursor "
                f"{entry_cursor} but the replay is at {cursor}",
                file=sys.stderr,
            )
            return 2
        for position in sorted(present):
            if position not in committed_seen:
                committed_seen.add(position)
                transitions.append(f'    [kind |-> "commit", pos |-> {position}]')
        for position in sorted(holes):
            if position in committed_seen:
                print(
                    f"error: {in_path} line {index}: position {position} is both "
                    f"committed and abandoned",
                    file=sys.stderr,
                )
                return 2
            if position not in abandoned_seen:
                abandoned_seen.add(position)
                transitions.append(f'    [kind |-> "abandon", pos |-> {position}]')
        if safe > cursor:
            transitions.append(f'    [kind |-> "advance", safe |-> {safe}]')
            cursor = safe

    if not committed_seen:
        print(f"error: {in_path} records no committed position", file=sys.stderr)
        return 2
    if not any('"advance"' in t for t in transitions):
        print(f"error: {in_path} records no cursor advance", file=sys.stderr)
        return 2

    all_positions = committed_seen | abandoned_seen
    highest = max(all_positions)
    commit_set = "{" + ", ".join(str(p) for p in sorted(committed_seen)) + "}"

    module = out_path.stem
    trace_def = " <<\n" + ",\n".join(transitions) + "\n>>"

    body = (
        f"---- MODULE {module} ----\n"
        "\\* Generated by specs/checkpoint_trace.py from a recorded checkpoint log.\n"
        "\\* Do not edit; regenerate from the JSON-lines source instead.\n"
        "EXTENDS CheckpointTrace\n\n"
        f"TraceN == {highest}\n\n"
        f'\\* A recorded commit fixes the position\'s fate to "C", anything else to "R".\n'
        f'TraceFate == [p \\in 1..{highest} |-> IF p \\in {commit_set} THEN "C" ELSE "R"]\n\n'
        f"TraceDef =={trace_def}\n"
        "====\n"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    print(f"wrote {out_path} ({len(transitions)} transitions)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="record a real checkpoint trace")
    record.add_argument("--out", type=Path, required=True, help="JSON-lines output")

    convert = subparsers.add_parser("to-tla", help="convert a log to a TLA+ module")
    convert.add_argument("--in", dest="in_path", type=Path, required=True)
    convert.add_argument(
        "--out", type=Path, required=True, help="CheckpointTrace_*.tla"
    )

    args = parser.parse_args(argv)
    if args.command == "record":
        return _record(args.out)
    return _to_tla(args.in_path, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
