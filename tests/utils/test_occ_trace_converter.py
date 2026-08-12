"""The ``specs/occ_trace.py`` log-to-TLA+ converter and its reject branches (:issue:`#1382`).

``check.sh`` only exercises the happy conversion and the two valid fixtures, so the
converter's malformed-input guards would rot unnoticed. These lock them, and pin
that the recorder's ``OCCEvent`` schema and the field names the converter reads
stay in lockstep.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from protean.utils.occ_trace import OCCEvent

# Converter/schema unit tests: no domain is used, so skip the autouse fixture.
pytestmark = pytest.mark.no_test_domain

# Load specs/occ_trace.py by path: it is a standalone script (so `to-tla` can run
# under a bare python3 without protean), not an importable package.
_SPEC = Path(__file__).resolve().parents[2] / "specs" / "occ_trace.py"
_module_spec = importlib.util.spec_from_file_location("specs_occ_trace", _SPEC)
occ_trace_script = importlib.util.module_from_spec(_module_spec)
_module_spec.loader.exec_module(occ_trace_script)


def _write(path: Path, events: list[dict]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


def _committed(base, after, stream="counter:seed"):
    return {
        "stream": stream,
        "writer": "t",
        "base": base,
        "outcome": "committed",
        "version_after": after,
    }


def _conflicted(base, stream="counter:seed"):
    return {
        "stream": stream,
        "writer": "t",
        "base": base,
        "outcome": "conflicted",
        "version_after": base + 1,
    }


def test_valid_log_converts_to_a_runnable_module(tmp_path):
    log = _write(tmp_path / "log.jsonl", [_committed(0, 1), _conflicted(0)])
    out = tmp_path / "OCCTrace_run.tla"

    assert occ_trace_script._to_tla(log, out) == 0

    text = out.read_text(encoding="utf-8")
    assert "---- MODULE OCCTrace_run ----" in text
    assert 'TraceWriters == {"w1", "w2"}' in text  # writers assigned positionally
    assert 'outcome |-> "committed", after |-> 1' in text
    assert 'outcome |-> "conflicted"' in text


def test_empty_log_is_rejected(tmp_path):
    log = _write(tmp_path / "empty.jsonl", [])
    assert occ_trace_script._to_tla(log, tmp_path / "o.tla") == 2


def test_multiple_streams_are_rejected(tmp_path):
    # OCC is per aggregate: one version cell, one trace.
    log = _write(
        tmp_path / "multi.jsonl",
        [_committed(0, 1, stream="a:1"), _committed(0, 1, stream="b:2")],
    )
    assert occ_trace_script._to_tla(log, tmp_path / "o.tla") == 2


def test_bad_outcome_is_rejected(tmp_path):
    log = _write(
        tmp_path / "bad.jsonl",
        [{"stream": "counter:seed", "writer": "t", "base": 0, "outcome": "maybe"}],
    )
    assert occ_trace_script._to_tla(log, tmp_path / "o.tla") == 2


def test_committed_without_version_after_is_rejected(tmp_path):
    # The model reads ``after`` on a commit, so a missing value is malformed, not
    # a version that happens to equal the base.
    log = _write(
        tmp_path / "noafter.jsonl",
        [
            {
                "stream": "counter:seed",
                "writer": "t",
                "base": 0,
                "outcome": "committed",
                "version_after": None,
            }
        ],
    )
    assert occ_trace_script._to_tla(log, tmp_path / "o.tla") == 2


def test_conflict_without_version_after_falls_back_to_base(tmp_path):
    # A conflict leaves the version unchanged and the model never reads ``after``
    # for it, so a missing value falls back to the base rather than erroring.
    log = _write(
        tmp_path / "conf.jsonl",
        [
            _committed(0, 1),
            {
                "stream": "counter:seed",
                "writer": "t",
                "base": 0,
                "outcome": "conflicted",
                "version_after": None,
            },
        ],
    )
    out = tmp_path / "o.tla"
    assert occ_trace_script._to_tla(log, out) == 0
    assert 'outcome |-> "conflicted", after |-> 0' in out.read_text(encoding="utf-8")


def test_missing_required_field_is_rejected(tmp_path):
    # A line missing a required field must reject cleanly, not raise a KeyError.
    log = _write(
        tmp_path / "missing.jsonl",
        # Well-formed but for the missing "stream".
        [{"writer": "t", "base": 0, "outcome": "committed", "version_after": 1}],
    )
    assert occ_trace_script._to_tla(log, tmp_path / "o.tla") == 2


def test_non_integer_version_is_rejected(tmp_path):
    # A non-integer base/version must reject cleanly, not raise a ValueError.
    log = _write(
        tmp_path / "nonint.jsonl",
        [
            {
                "stream": "counter:seed",
                "writer": "t",
                "base": "x",
                "outcome": "conflicted",
            }
        ],
    )
    assert occ_trace_script._to_tla(log, tmp_path / "o.tla") == 2


def test_float_and_negative_versions_are_rejected(tmp_path):
    # Versions are natural numbers; a float (which int() would truncate) or a
    # negative must reject cleanly rather than reach TLC as a confusing value.
    for bad in (1.9, -1):
        log = _write(
            tmp_path / "nat.jsonl",
            [
                {
                    "stream": "counter:seed",
                    "writer": "t",
                    "base": bad,
                    "outcome": "conflicted",
                }
            ],
        )
        assert occ_trace_script._to_tla(log, tmp_path / "o.tla") == 2, bad


def test_non_object_line_is_rejected(tmp_path):
    (tmp_path / "scalar.jsonl").write_text("42\n", encoding="utf-8")
    assert occ_trace_script._to_tla(tmp_path / "scalar.jsonl", tmp_path / "o.tla") == 2


def test_invalid_json_line_is_rejected(tmp_path):
    # A syntactically-broken line rejects cleanly, not with a JSONDecodeError crash.
    (tmp_path / "broken.jsonl").write_text('{"stream": oops}\n', encoding="utf-8")
    assert occ_trace_script._to_tla(tmp_path / "broken.jsonl", tmp_path / "o.tla") == 2


def test_converter_reads_the_recorder_schema_fields():
    # Guard against drift: the converter reads these keys by name off each event,
    # so a rename in OCCEvent must be matched here or the script breaks at runtime.
    assert set(OCCEvent.__annotations__) == {
        "stream",
        "writer",
        "base",
        "outcome",
        "version_after",
    }
