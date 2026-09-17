"""Tests for ``protean new --from-model`` — build a verify-green project from a
text event model.

``--from-model`` composes the callable cores: parse the model, create the project
with the example slice off, promote the model to a slice, apply it, then run
``verify`` in-process. Parse runs first, so an invalid model aborts before any
directory is created.

The end-to-end case runs as a real subprocess (like
``test_new_generates_a_working_project.py``): the real verify imports the generated
domain in-process, so running it as a subprocess keeps that registration out of the
test interpreter. The other cases run fast in-process with ``CliRunner``: the
pipeline case stubs ``run_verify`` (so nothing imports the generated domain), and
the failure cases abort before verify runs.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest
from typer.testing import CliRunner

from protean.cli import app
from tests.shared import module_unavailable

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
    aggregate_base = project / "src/modelapp/item/aggregate_base.py"
    assert aggregate_base.is_file()
    assert (project / "src/modelapp/item/projectors.py").is_file()
    assert not (project / "src/modelapp/example").exists(), (
        "the example slice must be off, so apply's create-only writes do not "
        "collide with it"
    )
    # The generated aggregate carries the model's own fields, so the pipeline
    # really rendered this model and not just any green slice: ``name`` keeps its
    # ``max_length=100`` string bound and ``quantity`` renders as a plain int.
    aggregate_source = aggregate_base.read_text(encoding="utf-8")
    assert "name: Annotated[str, Field(max_length=100)]" in aggregate_source, (
        aggregate_source
    )
    assert "quantity: int" in aggregate_source, aggregate_source
    # The verdict is reported to the user.
    assert "PASS" in completed.stdout, completed.stdout


@pytest.mark.parametrize(
    "exit_code, verdict",
    [(0, "PASS"), (5, "FAIL")],
    ids=["verify-passes", "verify-fails"],
)
def test_from_model_runs_the_pipeline_and_maps_the_verify_code(
    tmp_path, monkeypatch, exit_code, verdict
):
    """In-process: ``--from-model`` really parses, creates (example off), generates
    and applies the slice, then maps the verify core's code to its own exit.

    ``run_verify`` is stubbed so the generated domain is not imported into this
    interpreter (the E2E subprocess test exercises the real verify). The stub also
    proves the command hands verify the right in-project domain and path, and that
    its exit code is passed straight through — 0 reported as PASS, a failure code
    reported as FAIL.
    """
    from protean.cli.verify import VerifyResult

    # ``protean.cli.verify`` the attribute is the re-exported command function, so
    # reach the real submodule through ``sys.modules`` to patch ``run_verify`` on it.
    verify_module = sys.modules["protean.cli.verify"]

    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    model_file = tmp_path / "model.txt"
    model_file.write_text(_VALID_MODEL, encoding="utf-8")

    calls: list[tuple[str, str]] = []

    def fake_run_verify(domain: str, path: str) -> VerifyResult:
        calls.append((domain, path))
        status = "pass" if exit_code == 0 else "fail"
        return VerifyResult(
            stages={
                "init": {"status": "pass"},
                "check": {"status": "pass"},
                "tests": {"status": status},
            },
            exit_code=exit_code,
            status=status,
        )

    # ``_run_from_model`` reads it fresh via ``from protean.cli.verify import
    # run_verify`` at call time, so patching the module attribute takes effect.
    monkeypatch.setattr(verify_module, "run_verify", fake_run_verify)

    result = runner.invoke(
        app,
        ["new", "modelapp", "-o", str(out), "--from-model", str(model_file)],
    )

    project = out / "modelapp"
    # The real create/generate/apply pipeline ran: the base project's domain.py
    # was written, the model's slice landed, and the example is off.
    assert (project / "src/modelapp/domain.py").is_file()
    assert (project / "src/modelapp/item/aggregate_base.py").is_file()
    assert (project / "src/modelapp/item/projectors.py").is_file()
    assert not (project / "src/modelapp/example").exists()
    # verify was handed the in-project domain and the project path.
    assert len(calls) == 1
    domain_arg, path_arg = calls[0]
    assert domain_arg.startswith(str(project / "src" / "modelapp" / "domain.py") + ":")
    assert path_arg == str(project)
    # The verify core's code is passed straight through, and the verdict is printed.
    assert result.exit_code == exit_code
    assert verdict in result.output


# A model that parses but whose aggregate slug ("shared") collides with the base
# project's own ``src/<pkg>/shared/`` folder. ``apply_plan`` is create-only, so the
# collision surfaces as an ``ApplyError`` after the project directory exists.
_COLLIDING_MODEL = textwrap.dedent(
    """\
    aggregate Shared:
        field name: string(max_length=100)
        field quantity: integer

    command CreateShared:
        field name: string(max_length=100)
        field quantity: integer

    event SharedCreated:
        field shared_id: string
        field name: string(max_length=100)
        field quantity: integer

    projection SharedSummary:
        field shared_id: identifier(key)
        field name: string(max_length=100)

    projector SharedProjector:
        for SharedSummary
        consumes SharedCreated
    """
)


def test_parse_ok_but_slice_fails_reports_cleanly_and_leaves_the_dir(tmp_path):
    """A model that parses but cannot be applied (its slug collides with the base
    project's ``shared/`` folder) reports a one-line error, not a traceback, exits
    non-zero, and says the project directory was left in place.

    Create runs before generate/apply, so the directory exists by the time the
    collision is hit. The plan does not add rollback, so it is left behind on
    purpose and the message says so.
    """
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    model_file = tmp_path / "model.txt"
    model_file.write_text(_COLLIDING_MODEL, encoding="utf-8")

    result = runner.invoke(
        app,
        ["new", "collideapp", "-o", str(out), "--from-model", str(model_file)],
    )

    project = out / "collideapp"
    assert result.exit_code == 1, result.output
    assert "could not build the slice from the model" in result.output
    assert "Traceback" not in result.output
    # The directory was created before the collision and is left in place.
    assert project.is_dir()
    assert "was left in place" in result.output


def test_from_model_prints_the_failure_detail_on_a_failed_verify(tmp_path, monkeypatch):
    """When verify fails, the command prints the check diagnostics and the pytest
    tail, the same detail ``protean verify`` shows, so a failed build is actionable
    and not just a bare "FAIL".

    ``run_verify`` is stubbed to return a failing result carrying a check error and
    a pytest tail, so this asserts the reporting without running a real failing
    project.
    """
    from protean.cli.verify import VerifyResult

    verify_module = sys.modules["protean.cli.verify"]

    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    model_file = tmp_path / "model.txt"
    model_file.write_text(_VALID_MODEL, encoding="utf-8")

    def fake_run_verify(domain: str, path: str) -> VerifyResult:
        return VerifyResult(
            stages={
                "init": {"status": "pass"},
                "check": {
                    "status": "fail",
                    "errors": [{"code": "X", "message": "a check error here"}],
                    "diagnostics": [],
                },
                "tests": {"status": "fail"},
            },
            exit_code=5,
            status="fail",
            tests_output="collected 1 item\nE   assert 1 == 2\n1 failed in 0.1s",
        )

    monkeypatch.setattr(verify_module, "run_verify", fake_run_verify)

    result = runner.invoke(
        app,
        ["new", "modelapp", "-o", str(out), "--from-model", str(model_file)],
    )

    assert result.exit_code == 5, result.output
    assert "FAIL" in result.output
    # The check error and the pytest tail are surfaced.
    assert "a check error here" in result.output
    assert "1 failed in 0.1s" in result.output


def test_from_model_without_scaffold_extra_reports_actionable_error(tmp_path):
    """A valid model but no copier: create fails with the install hint for
    ``protean new --from-model``, not a traceback. Parse runs first, so the model
    must be valid to reach the create step where the guard fires."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    model_file = tmp_path / "model.txt"
    model_file.write_text(_VALID_MODEL, encoding="utf-8")

    with module_unavailable("copier"):
        result = runner.invoke(
            app,
            ["new", "modelapp", "-o", str(out), "--from-model", str(model_file)],
        )

    assert result.exit_code == 1
    assert 'pip install "protean[scaffold]"' in result.output
    assert not (out / "modelapp").exists()


def test_existing_target_without_force_reports_cleanly(tmp_path):
    """A valid model but a non-empty target without ``--force``: ``create_project``
    raises ``FileExistsError``, which this path catches and reports as a one-line
    usage error (exit 2), not a traceback. The pre-existing file is left untouched.
    """
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    # A non-empty target already sits where the project would be created.
    existing = out / "modelapp"
    existing.mkdir()
    (existing / "keep.txt").write_text("keep", encoding="utf-8")
    model_file = tmp_path / "model.txt"
    model_file.write_text(_VALID_MODEL, encoding="utf-8")

    result = runner.invoke(
        app,
        ["new", "modelapp", "-o", str(out), "--from-model", str(model_file)],
    )

    assert result.exit_code == 2, result.output
    assert "not empty" in result.output
    assert "Traceback" not in result.output
    # The existing content was not cleared (no --force).
    assert (existing / "keep.txt").read_text(encoding="utf-8") == "keep"


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


def test_non_utf8_model_file_aborts_cleanly(tmp_path):
    """A ``--from-model`` file that is not UTF-8 is a clean usage error, not a
    traceback, and creates no directory. ``read_text(encoding='utf-8')`` raises
    ``UnicodeDecodeError`` (a ``ValueError``, not an ``OSError``), so the read
    guard has to catch it too."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    model_file = tmp_path / "model.txt"
    # Bytes that are not valid UTF-8 (a lone UTF-16 BOM plus high bytes).
    model_file.write_bytes(b"\xff\xfe\x00\x01\x80\x81")

    result = runner.invoke(
        app,
        ["new", "modelapp", "-o", str(out), "--from-model", str(model_file)],
    )

    assert result.exit_code != 0
    assert "could not read model file" in result.output
    assert "Traceback" not in result.output
    assert not (out / "modelapp").exists()
