"""Direct, no-Typer tests of the ``create_project`` scaffold core.

These call :func:`protean.scaffold.create_project` straight, without the CLI, so
they pin the callable contract the MCP server and other programmatic callers will
use: the returned path list, dry-run touching nothing at the target, and the same
exceptions the command raises.
"""

import os
import tempfile

import pytest

from protean.scaffold import create_project
from tests.shared import isolated_filesystem, module_unavailable

pytestmark = pytest.mark.no_test_domain

PROJECT_NAME = "foobar"
ANSWERS = {"author_name": "John Doe", "author_email": "john@doe.com"}


def test_apply_creates_a_project_and_returns_its_paths():
    """Apply writes the project and returns its files as relative POSIX paths."""
    with isolated_filesystem() as output_folder:
        created = create_project(PROJECT_NAME, output_folder, ANSWERS, defaults=True)

        project_dir = os.path.join(output_folder, PROJECT_NAME)
        assert os.path.isfile(os.path.join(project_dir, "README.md"))
        assert os.path.isfile(
            os.path.join(project_dir, "src", PROJECT_NAME, "domain.py")
        )
        assert os.path.isfile(os.path.join(project_dir, ".protean", "project.json"))
        assert os.path.isfile(os.path.join(project_dir, "AGENTS.md"))

        assert created == sorted(created), "returned paths must be sorted"
        for expected in (
            "README.md",
            f"src/{PROJECT_NAME}/domain.py",
            ".protean/project.json",
            "AGENTS.md",
        ):
            assert expected in created


def test_dry_run_writes_nothing_and_returns_the_same_plan_as_apply():
    """Dry-run leaves the target empty and returns exactly what apply produces."""
    with isolated_filesystem() as output_folder:
        planned = create_project(
            PROJECT_NAME, output_folder, ANSWERS, dry_run=True, defaults=True
        )

        assert planned, "dry-run must return the planned files"
        assert planned == sorted(planned)
        for expected in ("README.md", ".protean/project.json", "AGENTS.md"):
            assert expected in planned
        # Nothing was written to the target output folder.
        assert os.listdir(output_folder) == []

    # The plan matches what apply actually creates for the same inputs.
    with isolated_filesystem() as output_folder:
        applied = create_project(PROJECT_NAME, output_folder, ANSWERS, defaults=True)
        assert planned == applied


def test_dry_run_on_nonempty_target_previews_without_touching_it():
    """Dry-run leaves an existing non-empty target intact, with or without force.

    A preview must never clear the target and never refuse on a non-empty one:
    both the ``force=True`` (would clear on apply) and the default (would raise on
    apply) paths must return the plan and leave the pre-existing file in place.
    """
    for force in (False, True):
        with isolated_filesystem() as output_folder:
            project_dir = os.path.join(output_folder, PROJECT_NAME)
            os.makedirs(project_dir)
            sentinel = os.path.join(project_dir, "keep.txt")
            with open(sentinel, "w", encoding="utf-8") as handle:
                handle.write("precious")

            planned = create_project(
                PROJECT_NAME,
                output_folder,
                ANSWERS,
                dry_run=True,
                force=force,
                defaults=True,
            )

            assert "README.md" in planned, "preview must still return the plan"
            assert os.path.isfile(sentinel), "preview must not clear the target"
            with open(sentinel, encoding="utf-8") as handle:
                assert handle.read() == "precious"
            # No project files were written at the target: only the sentinel is
            # there.
            assert os.listdir(project_dir) == ["keep.txt"]


def test_dot_segment_names_are_rejected():
    """``.`` and ``..`` are refused so force never clears the folder or its parent."""
    for bad_name in (".", ".."):
        with isolated_filesystem() as output_folder:
            sentinel = os.path.join(output_folder, "keep.txt")
            with open(sentinel, "w", encoding="utf-8") as handle:
                handle.write("precious")

            with pytest.raises(ValueError, match="Invalid project name"):
                create_project(bad_name, output_folder, ANSWERS, force=True)
            assert os.path.isfile(sentinel), "a rejected name must clear nothing"


def test_non_string_name_raises_value_error():
    """A non-string name raises the documented ValueError, not a bare TypeError."""
    with isolated_filesystem() as output_folder:
        with pytest.raises(ValueError, match="Invalid project name"):
            create_project(None, output_folder, ANSWERS)  # type: ignore[arg-type]


def test_invalid_name_raises_value_error_and_writes_nothing():
    """A forbidden character in the name is rejected before anything is written."""
    with isolated_filesystem() as output_folder:
        with pytest.raises(ValueError, match="Invalid project name"):
            create_project("bad/name", output_folder, ANSWERS, defaults=True)
        assert os.listdir(output_folder) == []


def test_missing_output_folder_raises_file_not_found():
    """A non-existent output folder raises FileNotFoundError."""
    with isolated_filesystem() as output_folder:
        missing = os.path.join(output_folder, "does-not-exist")
        with pytest.raises(FileNotFoundError, match="does not exist"):
            create_project(PROJECT_NAME, missing, ANSWERS, defaults=True)


def test_nonempty_target_needs_force():
    """A non-empty target raises without force; with force it clears and succeeds."""
    with isolated_filesystem() as output_folder:
        project_dir = os.path.join(output_folder, PROJECT_NAME)
        os.makedirs(project_dir)
        sentinel = os.path.join(project_dir, "keep.txt")
        with open(sentinel, "w", encoding="utf-8") as handle:
            handle.write("precious")
        # A pre-existing subdirectory, so force exercises the recursive removal
        # branch, not just top-level file unlinking.
        stale_subdir = os.path.join(project_dir, "stale")
        os.makedirs(stale_subdir)
        with open(os.path.join(stale_subdir, "old.py"), "w", encoding="utf-8") as h:
            h.write("stale")

        with pytest.raises(FileExistsError, match="is not empty"):
            create_project(PROJECT_NAME, output_folder, ANSWERS, defaults=True)
        assert os.path.isfile(sentinel), "target must be untouched without force"

        create_project(PROJECT_NAME, output_folder, ANSWERS, force=True, defaults=True)
        assert not os.path.exists(sentinel), "force must clear the pre-existing file"
        assert not os.path.exists(stale_subdir), "force must clear pre-existing subdirs"
        assert os.path.isfile(os.path.join(project_dir, "README.md"))


def test_symlinked_target_outside_the_output_folder_is_refused():
    """A target symlinked out of the output folder is refused before any clear.

    ``os.path``, ``shutil``, and copier follow symlinks, so without this check
    ``force`` would delete, and the render would write, wherever the link points.
    Both apply and dry-run must refuse and leave the linked-to directory intact.
    """
    with isolated_filesystem() as workspace:
        output_folder = os.path.join(workspace, "out")
        outside = os.path.join(workspace, "outside")
        os.makedirs(output_folder)
        os.makedirs(outside)
        sentinel = os.path.join(outside, "keep.txt")
        with open(sentinel, "w", encoding="utf-8") as handle:
            handle.write("precious")
        os.symlink(outside, os.path.join(output_folder, PROJECT_NAME))

        for dry_run in (False, True):
            with pytest.raises(ValueError, match="resolves outside output folder"):
                create_project(
                    PROJECT_NAME,
                    output_folder,
                    ANSWERS,
                    dry_run=dry_run,
                    force=True,
                    defaults=True,
                )

        assert os.path.isfile(sentinel), "the linked-to directory must be untouched"
        with open(sentinel, encoding="utf-8") as handle:
            assert handle.read() == "precious"


def test_copier_absent_raises_import_error_before_clearing():
    """With copier absent the core raises ImportError before it clears the target.

    Point at a non-empty target with force set: the import guard must fire first,
    so the sentinel survives and nothing is cleared.
    """
    with isolated_filesystem() as output_folder:
        project_dir = os.path.join(output_folder, PROJECT_NAME)
        os.makedirs(project_dir)
        sentinel = os.path.join(project_dir, "keep.txt")
        with open(sentinel, "w", encoding="utf-8") as handle:
            handle.write("precious")

        with module_unavailable("copier"):
            with pytest.raises(ImportError):
                create_project(
                    PROJECT_NAME, output_folder, ANSWERS, force=True, defaults=True
                )

        assert os.path.isfile(sentinel), "guard must fire before clearing the target"
        with open(sentinel, encoding="utf-8") as handle:
            assert handle.read() == "precious"


def test_dry_run_does_not_log_the_temp_render(capsys):
    """A dry run stays silent about the temp directory it rendered into.

    Copier logs a ``create <path>`` line per file. Under dry-run those writes
    happen in a temp directory the caller never sees, so the log would name
    paths that do not exist by the time the call returns. The returned list is
    the answer; copier's log is silenced.
    """
    with isolated_filesystem() as output_folder:
        create_project(
            PROJECT_NAME, output_folder, ANSWERS, dry_run=True, defaults=True
        )

    captured = capsys.readouterr()
    assert "create" not in captured.out + captured.err
    assert tempfile.gettempdir() not in captured.out + captured.err
