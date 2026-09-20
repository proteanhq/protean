"""Build every DX-pack skill example and require it to initialize.

Each ``skills/*/assets/*.py`` is a runnable teaching example that declares a
Protean domain. This harness runs every one of them and, for each, collects the
``Domain`` objects it defines, calls ``domain.init(traverse=False)``, and
requires the domain to have registered at least one element. That is the
structural contract the pack must keep: every bundled example is a well-formed
domain that registers real elements and initializes against the installed
framework, so an agent that copies the example gets working code.

The examples run in one child interpreter, each under its own ``run_name`` so
their element registrations land in separate namespaces and cannot collide. The
``run_name`` is never ``"__main__"``, so the runner executes each example's
definitions and skips its ``if __name__ == "__main__"`` demo block. A demo block
is a usage walk-through, and several end by launching a live uvicorn server that
never returns; initializing the domain checks the example without blocking on a
server or depending on a demo's runtime data.

The child interpreter keeps the example domains and their registrations out of
this test process. The harness reads package data and shells out; it never
touches a Domain here, so it skips the autouse ``test_domain`` fixture. It runs
in the core lane (no ``slow`` marker), so ``protean test`` gates it: one
framework import validates the whole example corpus in a couple of seconds.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from protean import dx

pytestmark = pytest.mark.no_test_domain

# The pack ships as package data; on a filesystem install its root is a real
# directory, which is what the runner needs to execute an example by path. The
# clean-venv wheel check in CI proves the same files survive the build.
PACK_ROOT = Path(str(dx.pack_files()))
SKILLS_ROOT = PACK_ROOT / dx.SKILLS_DIR

# The runner executes assets by path, so it needs the pack unpacked on disk. The
# accessor does not promise a filesystem root (a zip install would not have one);
# CI installs unzipped, so this skips cleanly only in the zip case.
if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the example runner needs a real "
        "directory to execute assets by path",
        allow_module_level=True,
    )


def _discover_assets() -> list[Path]:
    """Return every example asset under the pack, sorted, excluding package
    ``__init__.py`` markers (which define no example)."""
    return sorted(
        path for path in SKILLS_ROOT.glob("*/assets/*.py") if path.name != "__init__.py"
    )


def _independent_asset_count() -> int:
    """Count example assets by walking the tree with ``iterdir``.

    This walks the directories directly rather than reusing the glob in
    :func:`_discover_assets`, so a broken glob (one that silently matches nothing
    or too much) shows up as a count mismatch instead of a quietly empty run.
    """
    total = 0
    for skill_dir in SKILLS_ROOT.iterdir():
        assets_dir = skill_dir / "assets"
        if not (skill_dir.is_dir() and assets_dir.is_dir()):
            continue
        total += sum(
            1
            for path in assets_dir.iterdir()
            if path.suffix == ".py" and path.name != "__init__.py"
        )
    return total


ASSETS = _discover_assets()

# The child-interpreter runner. It discovers the same assets, runs each one's
# definitions under its own run_name (so registrations do not collide and the
# demo block is skipped), initializes every domain the example declares, and
# writes a JSON report (the count it processed and a line per failure) to the
# path in argv[2]. It writes to a file, not a stream, so the framework's own
# start-up logging on stderr cannot corrupt the report. It collects every
# failure: it runs all examples, then exits non-zero if any failed, so one run
# names every broken example instead of stopping at the first.
_RUNNER = """
import json
import pathlib
import runpy
import sys

from protean.domain import Domain

skills_root = pathlib.Path(sys.argv[1])
report_path = pathlib.Path(sys.argv[2])
assets = sorted(
    p for p in skills_root.glob("*/assets/*.py") if p.name != "__init__.py"
)
failures = []
for index, path in enumerate(assets):
    try:
        namespace = runpy.run_path(str(path), run_name="_dx_example_%d_" % index)
        domains = [v for v in namespace.values() if isinstance(v, Domain)]
        if not domains:
            raise RuntimeError("example defines no Domain")
        for domain in domains:
            domain.init(traverse=False)
            if not domain.registry.elements:
                raise RuntimeError("example domain registers no elements")
    except Exception as exc:  # report the failure, then keep going
        failures.append(
            "%s: %s: %s" % (path.relative_to(skills_root), type(exc).__name__, exc)
        )
report_path.write_text(json.dumps({"count": len(assets), "failures": failures}))
sys.exit(1 if failures else 0)
"""


def test_example_discovery_is_not_vacuous():
    # Guard against a run that validates nothing: if the glob matched no assets,
    # the harness would pass while building zero examples. Pin the count to an
    # independent walk so a broken glob fails, and to a floor near the real
    # corpus size (135 today) so a mass deletion cannot slip under it. The floor
    # leaves room for a small prune; a larger loss trips it.
    assert ASSETS, "discovered no example assets under the DX pack"
    assert len(ASSETS) == _independent_asset_count()
    assert len(ASSETS) >= 130


def test_every_example_builds_and_initializes(tmp_path):
    report_path = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, "-c", _RUNNER, str(SKILLS_ROOT), str(report_path)],
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert report_path.is_file(), (
        f"the example runner crashed before writing its report "
        f"(exit {result.returncode}):\n{result.stderr}"
    )
    report = json.loads(report_path.read_text())

    # The child ran the same set this process discovered, so a silent glob skew
    # (the child validating fewer examples than are on disk) fails here too.
    assert report["count"] == len(ASSETS)
    assert report["failures"] == [], (
        "examples failed to build and initialize:\n" + "\n".join(report["failures"])
    )
    assert result.returncode == 0
