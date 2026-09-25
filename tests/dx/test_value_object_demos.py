"""The value-object skill's examples run as their ``Usage:`` line says.

Each asset's docstring tells the reader to run it with ``python <file>``. The
example runner in ``tests/dx/test_examples.py`` skips the ``__main__`` demo
block, so these tests run each file as a script in a child interpreter and
check the demo finishes. Some demos print ``Should have failed!`` when an
expected error does not come, so the output must not contain that line. The
check guards only the demos that print it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from protean import dx

# These tests shell out and read package data; they never touch a Domain here.
pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
SKILLS_ROOT = PACK_ROOT / dx.SKILLS_DIR
VALUE_OBJECT_ASSETS = SKILLS_ROOT / "value-object" / "assets"

DEMOS = [
    "value_object_in_aggregate.py",
    "value_object_in_entity.py",
    "value_object_nested.py",
    "value_object_simple.py",
    "value_object_with_invariants.py",
    "value_object_with_methods.py",
    "value_object_with_validation.py",
]

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; running an asset as a script needs a "
        "real directory",
        allow_module_level=True,
    )


def test_demo_list_matches_the_assets_on_disk():
    on_disk = sorted(p.name for p in VALUE_OBJECT_ASSETS.glob("value_object_*.py"))
    assert on_disk == DEMOS


@pytest.mark.parametrize("name", DEMOS)
def test_usage_line_runs_the_file_as_a_script(name):
    source = (VALUE_OBJECT_ASSETS / name).read_text(encoding="utf-8")
    assert f"Usage:\n    python {name}\n" in source


@pytest.mark.parametrize("name", DEMOS)
def test_demo_runs_to_completion(name):
    result = subprocess.run(
        [sys.executable, name],
        cwd=VALUE_OBJECT_ASSETS,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"{name} exited {result.returncode}:\n{result.stderr}"
    )
    assert result.stdout.strip(), f"{name} printed nothing"
    assert "Should have failed!" not in result.stdout, result.stdout


def test_no_pack_file_mentions_protean_skills():
    # ``protean_skills`` was never a real package, so a Usage line naming it
    # cannot be followed.
    offenders = [
        str(path.relative_to(PACK_ROOT))
        for path in sorted(PACK_ROOT.rglob("*"))
        if path.is_file()
        and path.suffix in {".py", ".md"}
        and re.search(r"\bprotean_skills\b", path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
