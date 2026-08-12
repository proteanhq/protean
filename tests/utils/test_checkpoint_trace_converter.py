"""The ``specs/checkpoint_trace.py`` log-to-TLA+ converter and its reject branches
(:issue:`#1384`).

``check.sh`` only exercises the happy conversion and the two valid fixtures, so the
converter's malformed-input guards and its expansion logic (dedup, stutter-drop)
would rot unnoticed. These lock them, and pin that the recorder's
``CheckpointEvent`` schema and the field names the converter reads stay in lockstep.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from protean.utils.checkpoint_trace import CheckpointEvent

# Converter/schema unit tests: no domain is used, so skip the autouse fixture.
pytestmark = pytest.mark.no_test_domain

# Load specs/checkpoint_trace.py by path: it is a standalone script (so `to-tla` can
# run under a bare python3 without protean), not an importable package.
_SPEC = Path(__file__).resolve().parents[2] / "specs" / "checkpoint_trace.py"
_module_spec = importlib.util.spec_from_file_location("specs_checkpoint_trace", _SPEC)
checkpoint_trace_script = importlib.util.module_from_spec(_module_spec)
_module_spec.loader.exec_module(checkpoint_trace_script)


def _write(path: Path, events: list[dict]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


def _batch(cursor, present, safe, abandoned=None):
    return {
        "cursor": cursor,
        "present": present,
        "abandoned": abandoned or [],
        "safe": safe,
    }


def _reject(log, out, capsys, expected):
    """Assert the converter rejects ``log`` with exit 2, names the intended guard in
    its stderr, and writes no module — so a refactor that trips a *different* guard
    (still exit 2) does not slip through green."""
    assert checkpoint_trace_script._to_tla(log, out) == 2
    err = capsys.readouterr().err
    assert expected in err, f"expected {expected!r} in stderr, got: {err!r}"
    assert not out.exists()


def test_valid_log_converts_to_a_runnable_module(tmp_path):
    # The real-trace shape: a stranded gap that fills, plus an abandoned hole.
    log = _write(
        tmp_path / "log.jsonl",
        [_batch(0, [1, 3], 1), _batch(1, [3], 3, abandoned=[2])],
    )
    out = tmp_path / "CheckpointTrace_run.tla"

    assert checkpoint_trace_script._to_tla(log, out) == 0

    text = out.read_text(encoding="utf-8")
    assert "---- MODULE CheckpointTrace_run ----" in text
    assert "TraceN == 3" in text
    assert 'TraceFate == [p \\in 1..3 |-> IF p \\in {1, 3} THEN "C" ELSE "R"]' in text
    # commits (deduped: 3 appears in both batches but is committed once), then the
    # abandon, then the two real advances.
    assert text.count('kind |-> "commit"') == 2
    assert '[kind |-> "abandon", pos |-> 2]' in text
    assert text.count('kind |-> "advance"') == 2
    assert '[kind |-> "advance", safe |-> 3]' in text


def test_no_progress_tick_is_dropped(tmp_path):
    # A batch whose watermark did not pass the running cursor (a hold at a gap) maps
    # to no Tick, so the converter drops its advance as a stutter.
    log = _write(
        tmp_path / "hold.jsonl",
        [_batch(0, [1, 3], 1), _batch(1, [3], 1), _batch(1, [2, 3], 3)],
    )
    out = tmp_path / "o.tla"
    assert checkpoint_trace_script._to_tla(log, out) == 0
    text = out.read_text(encoding="utf-8")
    # Two real advances (safe 1 then 3); the middle hold (safe 1 == running cursor 1)
    # produced none.
    assert text.count('kind |-> "advance"') == 2
    assert '[kind |-> "advance", safe |-> 1]' in text
    assert '[kind |-> "advance", safe |-> 3]' in text


def test_empty_log_is_rejected(tmp_path, capsys):
    log = _write(tmp_path / "empty.jsonl", [])
    _reject(log, tmp_path / "o.tla", capsys, "has no events")


def test_log_without_a_commit_is_rejected(tmp_path, capsys):
    # A batch that saw nothing present records no committed position, so there is
    # nothing for the model to replay.
    log = _write(tmp_path / "nocommit.jsonl", [_batch(0, [], 0)])
    _reject(log, tmp_path / "o.tla", capsys, "records no committed position")


def test_log_without_an_advance_is_rejected(tmp_path, capsys):
    # A position committed but the cursor never advanced past it (safe == cursor):
    # no Tick to replay, so the log is degenerate.
    log = _write(tmp_path / "noadvance.jsonl", [_batch(0, [1], 0)])
    _reject(log, tmp_path / "o.tla", capsys, "records no cursor advance")


def test_position_committed_then_abandoned_is_rejected(tmp_path, capsys):
    # A position is either visible (committed) or a rolled-back hole (abandoned),
    # never both — a log claiming both is malformed.
    log = _write(
        tmp_path / "both.jsonl",
        [_batch(0, [1, 2], 2), _batch(2, [3], 3, abandoned=[2])],
    )
    _reject(log, tmp_path / "o.tla", capsys, "is both committed and abandoned")


def test_position_abandoned_then_committed_is_rejected(tmp_path, capsys):
    # The other direction of the same contradiction: a hole abandoned in one batch
    # cannot later be seen present. The guard is symmetric, so this rejects too.
    log = _write(
        tmp_path / "both2.jsonl",
        [_batch(0, [1], 1, abandoned=[2]), _batch(1, [2, 3], 3)],
    )
    _reject(log, tmp_path / "o.tla", capsys, "is both committed and abandoned")


def test_non_contiguous_cursor_is_rejected(tmp_path, capsys):
    # The replay reproduces one monotonic cursor from 0, so a batch that starts
    # where the previous one did not leave off (a spliced or crash-resume log) is
    # rejected rather than converted to a Trace the replay cannot reproduce.
    log = _write(
        tmp_path / "jump.jsonl",
        [_batch(0, [1], 1), _batch(5, [6], 6)],  # second batch should start at 1
    )
    _reject(log, tmp_path / "o.tla", capsys, "batch starts at cursor")


def test_watermark_above_highest_position_is_rejected(tmp_path, capsys):
    # ``global_position`` is 1-based, so the watermark can never settle above the
    # highest position anyone recorded. A log that advances past every known
    # position is corrupt; reject it here rather than aborting TLC on ``0..N``.
    log = _write(tmp_path / "over.jsonl", [_batch(0, [1], 100)])
    _reject(log, tmp_path / "o.tla", capsys, "above the highest recorded position")


def test_missing_field_is_rejected(tmp_path, capsys):
    log = _write(
        tmp_path / "missing.jsonl",
        [{"cursor": 0, "present": [1], "safe": 1}],  # no "abandoned"
    )
    _reject(log, tmp_path / "o.tla", capsys, "missing field(s)")


def test_non_integer_position_is_rejected(tmp_path, capsys):
    cases = [
        ({"cursor": "x", "present": [1], "abandoned": [], "safe": 1}, "cursor must be"),
        ({"cursor": 0, "present": [1], "abandoned": [], "safe": "y"}, "safe must be"),
    ]
    for i, (bad, expected) in enumerate(cases):
        log = _write(tmp_path / "nonint.jsonl", [bad])
        _reject(log, tmp_path / f"nonint_{i}.tla", capsys, expected)


def test_float_negative_and_zero_positions_are_rejected(tmp_path, capsys):
    # ``present`` holds 1-based positions, so a float, a negative, a boolean, and a
    # 0 (which would put TraceFate outside Checkpoint.tla's 1..N domain) all reject.
    for i, bad in enumerate((1.9, -1, True, 0)):
        log = _write(
            tmp_path / "nat.jsonl",
            [{"cursor": 0, "present": [bad], "abandoned": [], "safe": 1}],
        )
        _reject(log, tmp_path / f"nat_{i}.tla", capsys, "present entry must be")


def test_present_not_a_list_is_rejected(tmp_path, capsys):
    log = _write(
        tmp_path / "notlist.jsonl",
        [{"cursor": 0, "present": 1, "abandoned": [], "safe": 1}],
    )
    _reject(log, tmp_path / "o.tla", capsys, "present must be a list")


def test_non_object_line_is_rejected(tmp_path, capsys):
    (tmp_path / "scalar.jsonl").write_text("42\n", encoding="utf-8")
    _reject(tmp_path / "scalar.jsonl", tmp_path / "o.tla", capsys, "not a JSON object")


def test_invalid_json_line_is_rejected(tmp_path, capsys):
    # A syntactically-broken line rejects cleanly, not with a JSONDecodeError crash.
    (tmp_path / "broken.jsonl").write_text('{"cursor": oops}\n', encoding="utf-8")
    _reject(tmp_path / "broken.jsonl", tmp_path / "o.tla", capsys, "invalid JSON")


def test_converter_reads_the_recorder_schema_fields():
    # Guard against drift: the converter reads these keys by name off each event,
    # so a rename in CheckpointEvent must be matched here or the script breaks.
    assert set(CheckpointEvent.__annotations__) == {
        "cursor",
        "present",
        "abandoned",
        "safe",
    }
