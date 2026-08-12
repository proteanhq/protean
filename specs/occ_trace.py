#!/usr/bin/env python3
"""Generate and convert OCC trace logs for spec conformance checking.

Two subcommands, both driven by ``specs/check.sh``:

- ``record`` runs the real Memory-adapter compare-and-set under contention (the
  same shape as the ``#1251`` concurrent-writer suite: N writers load one
  aggregate at the same version, then all commit) with the tracer in
  ``protean.utils.occ_trace`` active, and writes the observed log as JSON lines.
  One writer wins and advances the version; the rest raise
  ``ExpectedVersionError`` and are recorded as conflicts. No external services are
  needed, so this runs anywhere ``protean`` imports.

- ``to-tla`` reads a JSON-lines log (a recorded one, or a checked-in fixture under
  ``specs/traces/``) and writes a runnable TLA+ module that binds it to
  ``OCCTrace.tla``'s ``Trace`` and ``Writers`` constants. ``check.sh`` then runs
  TLC over that module with ``OCCTrace_conform.cfg`` and ``OCCTrace_cover.cfg``.

The log schema is one object per unit of work, in commit order::

    {"stream": "<schema>:<id>", "writer": "<id>", "base": <int>,
     "outcome": "committed" | "conflicted", "version_after": <int>}

Only ``base``, ``outcome`` and (on a commit) ``version_after`` reach the model;
``writer`` is reassigned positionally so every unit of work is a distinct TLA+
writer, and ``stream`` groups a single aggregate's contention into one trace.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any


def _record(out_path: Path, writers: int) -> int:
    """Run ``writers`` concurrent Memory-adapter writers and log the OCC trace."""
    # Silence the framework's debug logging so the run's only output is the trace.
    logging.disable(logging.CRITICAL)

    # Imported here, not at module top, so the `to-tla` subcommand (which only
    # needs the stdlib) runs under a bare python3 without `protean` installed.
    from protean import Domain  # noqa: PLC0415
    from protean.core.aggregate import BaseAggregate  # noqa: PLC0415
    from protean.core.unit_of_work import UnitOfWork  # noqa: PLC0415
    from protean.exceptions import ExpectedVersionError  # noqa: PLC0415
    from protean.fields import Integer  # noqa: PLC0415
    from protean.utils import occ_trace  # noqa: PLC0415

    domain = Domain(name="OCC trace", config={"identity_type": "uuid"})

    class OCCCounter(BaseAggregate):
        value = Integer(default=0)

    domain.register(OCCCounter)
    domain.init(traverse=False)

    with domain.domain_context():
        with UnitOfWork():
            seed = OCCCounter(value=0)
            domain.repository_for(OCCCounter).add(seed)
        counter_id = seed.id

        # Every writer loads the same version before any commits, forcing a race.
        load_barrier = threading.Barrier(writers, timeout=30)

        errors: list[str] = []

        def worker(worker_no: int) -> None:
            try:
                with domain.domain_context(), UnitOfWork():
                    repo = domain.repository_for(OCCCounter)
                    counter = repo.get(counter_id)
                    counter.value = worker_no + 1
                    load_barrier.wait()
                    repo.add(counter)
            except ExpectedVersionError:
                pass  # a losing writer; the tracer already recorded the conflict
            except Exception as exc:  # a broken barrier, a store error, etc.
                errors.append(f"worker {worker_no}: {type(exc).__name__}: {exc}")

        with occ_trace.capture() as events:
            threads = [
                threading.Thread(target=worker, args=(i,)) for i in range(writers)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)
            recorded = list(events)

    # A partial recording (a crashed or hung worker) would still often conform and
    # contain a conflict, so it must fail loudly rather than pass a truncated log
    # off as a real run.
    committed = sum(1 for e in recorded if e["outcome"] == "committed")
    conflicted = sum(1 for e in recorded if e["outcome"] == "conflicted")
    problems = list(errors)
    if any(thread.is_alive() for thread in threads):
        problems.append("a worker thread did not finish within the join timeout")
    if len(recorded) != writers:
        problems.append(f"recorded {len(recorded)} events for {writers} writers")
    if committed != 1:
        problems.append(f"expected exactly one committed event, got {committed}")
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    _write_jsonl(out_path, recorded)
    print(
        f"recorded {len(recorded)} events "
        f"({committed} committed, {conflicted} conflicted) to {out_path}"
    )
    return 0


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def _to_tla(in_path: Path, out_path: Path) -> int:
    """Convert a JSON-lines OCC log into a runnable OCCTrace_* TLA+ module."""
    events = _read_jsonl(in_path)
    if not events:
        print(f"error: {in_path} has no events", file=sys.stderr)
        return 2

    streams = {event["stream"] for event in events}
    if len(streams) != 1:
        # OCC is per aggregate: one version cell, one trace. A multi-stream log
        # would interleave independent cells, which this model cannot represent.
        print(
            f"error: expected exactly one stream, found {sorted(streams)}",
            file=sys.stderr,
        )
        return 2

    records = []
    writer_names = []
    for index, event in enumerate(events, start=1):
        writer = f"w{index}"  # positional, so every unit of work is a distinct writer
        writer_names.append(writer)
        base = int(event["base"])
        outcome = event["outcome"]
        if outcome not in ("committed", "conflicted"):
            print(f"error: bad outcome {outcome!r} in {in_path}", file=sys.stderr)
            return 2
        version_after = event.get("version_after")
        if outcome == "committed":
            # The model reads ``after`` on a commit (``version' = after``), so a
            # committed event without it is malformed, not a version that happens
            # to equal the base.
            if version_after is None:
                print(
                    f"error: committed event without version_after in {in_path}",
                    file=sys.stderr,
                )
                return 2
            after = int(version_after)
        else:
            # A conflict leaves the version unchanged and the model never reads
            # ``after`` for it, so a missing value falls back to the base.
            after = int(version_after) if version_after is not None else base
        records.append(
            f'    [w |-> "{writer}", base |-> {base}, '
            f'outcome |-> "{outcome}", after |-> {after}]'
        )

    module = out_path.stem
    trace_def = " <<\n" + ",\n".join(records) + "\n>>"
    writers_set = "{" + ", ".join(f'"{w}"' for w in writer_names) + "}"

    body = (
        f"---- MODULE {module} ----\n"
        "\\* Generated by specs/occ_trace.py from a recorded OCC log. Do not edit;\n"
        "\\* regenerate from the JSON-lines source instead.\n"
        "EXTENDS OCCTrace\n\n"
        f"TraceDef =={trace_def}\n\n"
        f"TraceWriters == {writers_set}\n"
        "====\n"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    print(f"wrote {out_path} ({len(records)} events)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="record a real Memory OCC trace")
    record.add_argument("--out", type=Path, required=True, help="JSON-lines output")
    record.add_argument("--writers", type=int, default=4, help="concurrent writers")

    convert = subparsers.add_parser("to-tla", help="convert a log to a TLA+ module")
    convert.add_argument("--in", dest="in_path", type=Path, required=True)
    convert.add_argument("--out", type=Path, required=True, help="OCCTrace_*.tla")

    args = parser.parse_args(argv)
    if args.command == "record":
        if args.writers < 2:
            parser.error("--writers must be at least 2 to force a conflict")
        return _record(args.out, args.writers)
    return _to_tla(args.in_path, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
