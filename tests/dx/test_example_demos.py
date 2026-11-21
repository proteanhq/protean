"""Run the ``__main__`` demo block of every DX-pack skill example.

``tests/dx/test_examples.py`` runs each asset's definitions under a private
``run_name``, so it skips the ``if __name__ == "__main__"`` demo block. This
harness runs each demo block as the reader would with ``python <asset>``: as
module ``__main__``, in one child interpreter, with ``uvicorn.run`` replaced by
a recorder. A demo that ends by serving its FastAPI app then returns instead of
blocking, and the harness checks that it handed a FastAPI app to uvicorn.

Most demos show a rejection inside ``try``/``except`` and print only in the
handler, so a demo whose expected error stopped coming would still finish. The
runner adds a marker to each handler and to each ``else`` of the ``try``
statements in the demo block, and the test requires every such ``try`` to
raise on each pass. A ``try`` whose handler prints ``Unexpected error`` shows
an accepted value instead, so it must never raise. The child writes its report
to a file, as the example runner does, so the framework's start-up logging
cannot corrupt it.
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
import ast
import json
import pathlib
import sys
import types

import uvicorn
from fastapi import FastAPI

skills_root = pathlib.Path(sys.argv[1])
report_path = pathlib.Path(sys.argv[2])
demos = json.loads(sys.argv[3])

served = []
uvicorn.run = lambda app, **options: served.append((app, options))


def instrument(tree):
    # Mark each try statement in the demo block so the run records whether a
    # handler ran and whether the body finished without raising.
    tries = {}
    for node in tree.body:
        if not (
            isinstance(node, ast.If)
            and ast.unparse(node.test) == "__name__ == '__main__'"
        ):
            continue
        for found in ast.walk(node):
            if not (isinstance(found, ast.Try) and found.handlers):
                continue
            line = found.lineno
            handlers = "".join(ast.unparse(handler) for handler in found.handlers)
            tries[line] = "Unexpected error" not in handlers
            for handler in found.handlers:
                handler.body[:0] = ast.parse("__demo_raised__.add(%d)" % line).body
            found.orelse[:0] = ast.parse("__demo_finished__.add(%d)" % line).body
    return ast.fix_missing_locations(tree), tries


results = {}
for relative in demos:
    path = skills_root / relative
    tree, tries = instrument(ast.parse(path.read_text(encoding="utf-8")))
    module = types.ModuleType("__main__")
    module.__file__ = str(path)
    raised, finished = set(), set()
    module.__dict__.update(__demo_raised__=raised, __demo_finished__=finished)
    before = len(served)
    # The demo runs as the __main__ module, as it does under runpy.
    saved_main = sys.modules["__main__"]
    sys.modules["__main__"] = module
    try:
        exec(compile(tree, str(path), "exec"), module.__dict__)
        error = None
    except BaseException as exc:  # report the failure, then keep going
        error = "%s: %s" % (type(exc).__name__, exc)
    finally:
        sys.modules["__main__"] = saved_main
    results[relative] = {
        "error": error,
        "tries": {
            str(line): {
                "expects_error": expects_error,
                "raised": line in raised,
                "finished": line in finished,
            }
            for line, expects_error in tries.items()
        },
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


def test_demo_tries_include_expected_errors_and_accepted_values(report):
    kinds = {
        outcome["expects_error"]
        for demo in report.values()
        for outcome in demo["tries"].values()
    }
    assert kinds == {True, False}


@pytest.mark.parametrize("asset", sorted(DEMOS))
def test_demo_runs_to_completion(report, asset):
    outcome = report[asset]
    assert outcome["error"] is None, f"{asset}: {outcome['error']}"
    assert outcome["served"] == (SERVED_BY_UVICORN if DEMOS[asset] else [])


@pytest.mark.parametrize("asset", sorted(DEMOS))
def test_each_demo_try_raises_only_where_it_expects_an_error(report, asset):
    wrong = {
        f"line {line}": outcome
        for line, outcome in report[asset]["tries"].items()
        if (outcome["raised"], outcome["finished"])
        != (outcome["expects_error"], not outcome["expects_error"])
    }
    assert wrong == {}, asset
