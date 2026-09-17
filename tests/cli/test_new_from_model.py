"""Tests for ``protean new --from-model`` — build a verify-green project from a
text event model.

``--from-model`` composes the callable cores: parse the model, create the project
with the example slice off, promote the model to a slice, apply it, then run
``verify`` in-process. Parse runs first, so an invalid model aborts before any
directory is created.

The end-to-end case runs as a real subprocess (like
``test_new_generates_a_working_project.py``): the command imports the generated
domain in-process, so running it as a subprocess keeps that registration out of
the test interpreter. The negative case fails at parse — before ``create_project``
— so it runs fast in-process with ``CliRunner``.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest
from typer.testing import CliRunner

from protean.cli import app

# These generate their own projects; the autouse Test domain fixture would build
# an unrelated Domain per test for nothing.
pytestmark = pytest.mark.no_test_domain

runner = CliRunner()

# A one-slice model whose generated slice verifies green (the Item slice, the same
# shape ``tests/scaffold/test_slice_generator.py`` proves end-to-end).
_VALID_MODEL = textwrap.dedent(
    """\
    aggregate Item:
        field name: string(max_length=100)
        field quantity: integer

    command CreateItem:
        field name: string(max_length=100)
        field quantity: integer

    event ItemCreated:
        field item_id: string
        field name: string(max_length=100)
        field quantity: integer

    projection ItemSummary:
        field item_id: identifier(key)
        field name: string(max_length=100)

    projector ItemProjector:
        for ItemSummary
        consumes ItemCreated
    """
)


def test_from_model_builds_and_verifies_a_project(tmp_path):
    """A one-slice model produces a project whose slice reflects the model, and the
    run verifies green and exits 0.

    Run as a subprocess: ``--from-model`` imports the generated domain in-process,
    so keeping it out of this interpreter avoids cross-test registration bleed.
    """
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    model_file = tmp_path / "model.txt"
    model_file.write_text(_VALID_MODEL, encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "protean",
            "new",
            "modelapp",
            "-o",
            str(out),
            "--from-model",
            str(model_file),
        ],
        capture_output=True,
        text=True,
        errors="replace",
    )

    project = out / "modelapp"
    assert completed.returncode == 0, (
        "`protean new --from-model` must build and verify a project from a valid "
        f"model:\n{completed.stdout}\n{completed.stderr}"
    )
    # The model's slice landed (not the example): a green verdict reflects the
    # generated slice, not just the base project.
    assert (project / "src/modelapp/item/aggregate_base.py").is_file()
    assert (project / "src/modelapp/item/projectors.py").is_file()
    assert not (project / "src/modelapp/example").exists(), (
        "the example slice must be off, so apply's create-only writes do not "
        "collide with it"
    )
    # The verdict is reported to the user.
    assert "PASS" in completed.stdout, completed.stdout


def test_invalid_model_aborts_before_creating_a_directory(tmp_path):
    """An invalid model exits non-zero, prints the parser's error (with its line
    number), and leaves no project directory behind — parse runs before create."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    model_file = tmp_path / "bad.txt"
    # A non-indented line that is not a valid block header: the parser rejects it
    # at line 1 with a "malformed block header" message.
    model_file.write_text("this is not a block header\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["new", "modelapp", "-o", str(out), "--from-model", str(model_file)],
    )

    assert result.exit_code != 0
    assert "line 1" in result.output
    assert "malformed block header" in result.output
    # No directory was created: parse failed before create_project ran.
    assert not (out / "modelapp").exists(), (
        "an invalid model must not leave a project directory behind"
    )


def test_missing_model_file_aborts_cleanly(tmp_path):
    """A ``--from-model`` file that does not exist is a clean usage error, not a
    traceback, and creates no directory."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    missing = tmp_path / "nope.txt"

    result = runner.invoke(
        app,
        ["new", "modelapp", "-o", str(out), "--from-model", str(missing)],
    )

    assert result.exit_code != 0
    assert "could not read model file" in result.output
    assert "Traceback" not in result.output
    assert not (out / "modelapp").exists()
