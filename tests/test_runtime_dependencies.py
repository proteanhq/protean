"""Guards for the right-sized runtime dependency surface (ADR-0029).

The web/observatory stack, the interactive shell, and the project scaffolder live
behind install extras, not in the lean core. These tests pin that boundary so a
stray eager import or a dependency creeping back into ``[project].dependencies``
is caught. ``bleach`` and ``werkzeug`` intentionally stay in core.
"""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import protean

# Distribution name -> the extra that must provide it. None of these may be a
# core dependency.
OPTIONAL_DISTS = {
    "fastapi": "server",
    "uvicorn": "server",
    "jinja2": "server",
    "ipython": "shell",
    "copier": "scaffold",
}

# Top-level import name of each optional stack. `import protean` must pull none.
OPTIONAL_IMPORTS = ["fastapi", "uvicorn", "jinja2", "IPython", "copier"]

# Dependencies that must stay in the lean core.
CORE_MUST_KEEP = {"bleach", "werkzeug", "pydantic", "marshmallow", "typer"}


def _pyproject() -> dict:
    path = Path(protean.__file__).resolve().parents[2] / "pyproject.toml"
    if not path.exists():
        pytest.skip("pyproject.toml not available (installed, non-editable)")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _dist_name(spec: str) -> str:
    """Extract the distribution name from a requirement spec (`fastapi>=1` -> `fastapi`)."""
    match = re.match(r"[A-Za-z0-9._-]+", spec)
    assert match is not None, spec
    return match.group(0).lower()


def test_optional_distributions_are_not_core_dependencies():
    core = {_dist_name(spec) for spec in _pyproject()["project"]["dependencies"]}
    assert core, "core dependency list is empty"
    for dist, extra in OPTIONAL_DISTS.items():
        assert dist not in core, (
            f"{dist!r} must live behind protean[{extra}], not in [project].dependencies"
        )


def test_core_keeps_its_essential_dependencies():
    core = {_dist_name(spec) for spec in _pyproject()["project"]["dependencies"]}
    for dist in CORE_MUST_KEEP:
        assert dist in core, f"{dist!r} must stay a core dependency"


def test_each_optional_distribution_is_declared_in_its_extra():
    extras = _pyproject()["project"]["optional-dependencies"]
    for dist, extra in OPTIONAL_DISTS.items():
        names = {_dist_name(spec) for spec in extras[extra]}
        assert dist in names, f"protean[{extra}] must provide {dist!r}"


def test_convenience_extras_compose_the_feature_extras():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert extras["cli"] == ["protean[shell,scaffold]"]
    assert extras["all"] == ["protean[server,cli]"]


def test_import_protean_does_not_pull_optional_stacks():
    """A bare ``import protean`` must not import any optional feature stack.

    Runs in a subprocess so the check sees a clean module table, not one already
    populated by the test session (which installs every extra).
    """
    code = (
        "import sys, protean;"
        f"watched=set({OPTIONAL_IMPORTS!r});"
        "pulled=sorted(m for m in sys.modules if m.split('.')[0] in watched);"
        "print(','.join(pulled))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "", (
        f"import protean pulled optional stacks: {result.stdout.strip()}"
    )
