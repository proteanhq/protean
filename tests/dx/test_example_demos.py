"""Run the ``__main__`` demo block of every DX-pack skill example.

``tests/dx/test_examples.py`` runs each asset's definitions under a private
``run_name``, so it skips the ``if __name__ == "__main__"`` demo block. This
harness runs each demo block as the reader would with ``python <asset>``: under
``run_name="__main__"``, in one child interpreter, with ``uvicorn.run`` replaced
by a recorder. A demo that ends by serving its FastAPI app then returns instead
of blocking, and the harness checks that it handed a FastAPI app to uvicorn.

A demo passes when it raises nothing and does not print ``Should have
failed!``, the line several demos print when an expected error does not come.
The child writes its report to a file, as the example runner does, so the
framework's start-up logging cannot corrupt it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from protean import dx

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
SKILLS_ROOT = PACK_ROOT / dx.SKILLS_DIR

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the demo runner executes assets by path",
        allow_module_level=True,
    )

DEMO_GUARD = 'if __name__ == "__main__":'


def _demo_block(path: Path) -> str | None:
    """The source from the asset's ``__main__`` guard to the end, or ``None``."""
    source = path.read_text(encoding="utf-8")
    start = source.find(f"\n{DEMO_GUARD}\n")
    return None if start == -1 else source[start:]


def _discover_demos() -> dict[str, bool]:
    """Map each asset with a demo block to whether the demo serves an app."""
    demos = {}
    for path in sorted(SKILLS_ROOT.glob("*/assets/*.py")):
        block = _demo_block(path)
        if block is not None:
            demos[str(path.relative_to(SKILLS_ROOT))] = "uvicorn.run(" in block
    return demos


DEMOS = _discover_demos()

# The recorder's entry for a demo that serves its app.
SERVED_BY_UVICORN = [
    {"is_fastapi": True, "options": {"host": "127.0.0.1", "port": 8000}}
]

_RUNNER = """
import contextlib
import io
import json
import pathlib
import runpy
import sys

import uvicorn
from fastapi import FastAPI

skills_root = pathlib.Path(sys.argv[1])
report_path = pathlib.Path(sys.argv[2])
demos = json.loads(sys.argv[3])

served = []
uvicorn.run = lambda app, **options: served.append((app, options))

results = {}
for relative in demos:
    before = len(served)
    stdout = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout):
            runpy.run_path(str(skills_root / relative), run_name="__main__")
        error = None
    except BaseException as exc:  # report the failure, then keep going
        error = "%s: %s" % (type(exc).__name__, exc)
    results[relative] = {
        "error": error,
        "should_have_failed": "Should have failed!" in stdout.getvalue(),
        "served": [
            {"is_fastapi": isinstance(app, FastAPI), "options": options}
            for app, options in served[before:]
        ],
    }
report_path.write_text(json.dumps(results))
"""


@pytest.fixture(scope="module")
def report(tmp_path_factory) -> dict[str, dict]:
    report_path = tmp_path_factory.mktemp("demos") / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            _RUNNER,
            str(SKILLS_ROOT),
            str(report_path),
            json.dumps(sorted(DEMOS)),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert report_path.is_file(), (
        f"the demo runner crashed before writing its report "
        f"(exit {result.returncode}):\n{result.stderr}"
    )
    return json.loads(report_path.read_text())


def test_demo_discovery_finds_plain_and_serving_demos():
    assert any(not serves for serves in DEMOS.values())
    assert any(DEMOS.values())


def test_every_asset_with_a_main_guard_is_discovered():
    # A guard line spelled differently (a trailing comment, say) would drop its
    # demo from the run without a failure.
    guarded = sorted(
        str(path.relative_to(SKILLS_ROOT))
        for path in SKILLS_ROOT.glob("*/assets/*.py")
        if '__name__ == "__main__"' in path.read_text(encoding="utf-8")
    )
    assert guarded == sorted(DEMOS)


def test_the_runner_reports_every_demo(report):
    assert sorted(report) == sorted(DEMOS)


@pytest.mark.parametrize("asset", sorted(DEMOS))
def test_demo_runs_to_completion(report, asset):
    outcome = report[asset]
    assert outcome["error"] is None, f"{asset}: {outcome['error']}"
    assert outcome["should_have_failed"] is False
    assert outcome["served"] == (SERVED_BY_UVICORN if DEMOS[asset] else [])
