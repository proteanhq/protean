"""Read a produced project's IR by shelling ``protean ir show`` into it.

The scorer compares a produced project's structure against the gold's, and the
structure it reads is the domain's Intermediate Representation. :func:`build_ir`
runs ``protean ir show --format json --canonical`` in a subprocess, the same
isolation :func:`tests.eval.tools.run_verify` uses: it keeps a produced
project's (possibly model-generated) import out of the test interpreter, strips
the same environment variables, and discovers the domain the same way, so the IR
read depends on the project's files and not the outer shell.

``--canonical`` drops the volatile ``generated_at`` timestamp. The scorer reads
only stable structural fields (class names, field names) regardless, so a probe
result never carries a value that differs run to run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.eval.discovery import discover_domain_arg, stripped_env

__all__ = ["build_ir"]

# A ceiling on the ir-show subprocess. It imports the produced domain, which for
# a model-generated project could hang on import; the cap keeps a hung read from
# stalling the scorer. ``ir show`` runs no test suite, so it spawns no child
# tree and a plain wait-with-timeout is enough.
_IR_TIMEOUT_SECONDS = 120


def build_ir(root: Path | str) -> dict[str, Any]:
    """Return the parsed IR of the project at *root*, or ``{}`` when it has none.

    An empty dict is the "no readable IR" result the scorer expects: a project
    with no discoverable ``domain.py``, a domain that will not import, a
    non-zero exit, a timeout, or output with no JSON object all come back as
    ``{}`` rather than raising, so the scorer reports zero recovered elements
    instead of crashing.

    ``ir show`` requires a domain path, so a root ``domain.py`` (which verify's
    default discovery would find without one) is addressed explicitly as
    ``domain.py`` here.
    """
    root_path = Path(root)
    domain_arg = discover_domain_arg(root_path)
    if domain_arg is None:
        if (root_path / "domain.py").is_file():
            domain_arg = "domain.py"
        else:
            return {}

    # `-P` keeps the produced project off this interpreter's module search, so a
    # generated `protean.py` at the root cannot shadow the framework CLI on
    # `-m protean`, matching run_verify.
    args = [
        sys.executable,
        "-P",
        "-m",
        "protean",
        "ir",
        "show",
        "-d",
        domain_arg,
        "--format",
        "json",
        "--canonical",
    ]
    try:
        process = subprocess.run(
            args,
            cwd=root_path,
            capture_output=True,
            text=True,
            errors="replace",
            env=stripped_env(),
            timeout=_IR_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {}
    if process.returncode != 0:
        return {}
    return _decode_ir(process.stdout)


def _decode_ir(stdout: str) -> dict[str, Any]:
    """Decode the IR JSON object from *stdout*, tolerating stray output before it.

    ``ir show`` prints the IR as a single top-level JSON object; a produced
    domain may still print to stdout during import. This returns the last
    top-level JSON object in the output, so a stray earlier print does not win
    over the real IR, and ``{}`` when there is no JSON object at all.
    """
    decoder = json.JSONDecoder()
    last: dict[str, Any] = {}
    index = stdout.find("{")
    while index != -1:
        try:
            # Scanning only from "{", so a successful decode is always an object.
            candidate, end = decoder.raw_decode(stdout, index)
        except json.JSONDecodeError:
            index = stdout.find("{", index + 1)
            continue
        last = candidate
        index = stdout.find("{", max(end, index + 1))
    return last
