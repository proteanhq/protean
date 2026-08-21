"""Create a new Protean project — the callable core behind ``protean new``.

This is the file-producing half of ``protean new``, lifted out of the Typer
command so the CLI, the MCP server, tests, or any programmatic caller can run it
directly. The core owns exactly the scaffolding: the lazy ``copier`` import
guard, project-name validation, target-directory resolution, the ``--force``
clear, the copier render, and writing the derived manifest
(:mod:`protean.scaffold.manifest`) and the ``AGENTS.md`` root file. It leaves the
post-generation setup (``uv sync``, ``git init``, pre-commit, console tips) in
the CLI, because that is console and subprocess work, not scaffolding.

:func:`create_project` returns the sorted list of project-relative POSIX paths it
created (apply) or would create (dry-run). Under ``dry_run`` it touches nothing
at the target: it renders into a system temp directory, walks that to enumerate
the exact files apply would produce, and lets the temp directory auto-remove. The
returned dry-run list is byte-for-byte the same set apply produces from the same
inputs.

``copier`` is the optional ``[scaffold]`` extra, so it is imported inside the
function (its first statement), never at module top: this keeps
``import protean.scaffold`` side-effect free on a base install, and the guard
fires before any directory is cleared.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

import protean
from protean.ir.generators.agents import generate_agents_md
from protean.scaffold.manifest import write_manifest

__all__ = ["create_project"]

# Characters a project name may not contain, so the name is a safe directory
# name across Mac, Linux, and Windows. Whitespace (``\s``) is included, which
# also rejects spaces, tabs, and newlines.
_FORBIDDEN_NAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\s]')


def _is_valid_project_name(project_name: object) -> bool:
    """Return whether *project_name* is a portable, single-segment directory name.

    The parameter is typed ``object`` because the runtime contract is wider than
    the public :func:`create_project` signature: a programmatic caller (the MCP
    ``scaffold`` tool) can hand over whatever JSON decoded to, so a non-string
    has to be rejected here rather than blowing up further down.

    Rejects a non-string, the empty string, the ``.`` and ``..`` path segments,
    and any name carrying a forbidden character (see
    :data:`_FORBIDDEN_NAME_CHARACTERS`). The forbidden set already includes the
    path separators, so an accepted name is always a single directory segment
    that resolves under *output_folder* and never at or above it. This matters
    for the ``force`` clear: a programmatic caller (the MCP ``scaffold`` tool)
    passing ``"."`` or ``".."`` must not end up clearing the output folder or its
    parent.
    """
    if not isinstance(project_name, str):
        return False
    if not project_name or project_name in {".", ".."}:
        return False
    return not _FORBIDDEN_NAME_CHARACTERS.search(project_name)


def _clear_directory_contents(dir_path: str) -> None:
    """Remove everything inside *dir_path* without removing the directory itself.

    Files and symlinks are unlinked; subdirectories are removed recursively.
    """
    for item in os.listdir(dir_path):
        item_path = os.path.join(dir_path, item)
        if os.path.isfile(item_path) or os.path.islink(item_path):
            os.unlink(item_path)
        elif os.path.isdir(item_path):
            shutil.rmtree(item_path)


def _relative_file_paths(root: str) -> list[str]:
    """Return every file under *root* as a sorted list of relative POSIX paths.

    Walks the whole tree, hidden files (``.protean/project.json``, ``.gitignore``)
    included, and returns paths relative to *root* so the list is stable across
    operating systems and independent of where *root* lives.
    """
    root_path = Path(root)
    return sorted(
        path.relative_to(root_path).as_posix()
        for path in root_path.rglob("*")
        if path.is_file()
    )


def create_project(
    project_name: str,
    output_folder: str = ".",
    data: dict[str, str] | None = None,
    *,
    dry_run: bool = False,
    force: bool = False,
    defaults: bool = False,
) -> list[str]:
    """Scaffold a new Protean project and return the paths it created.

    Renders the bundled project template into ``<output_folder>/<project_name>``,
    then writes the derived manifest (``.protean/project.json``) and the
    ``AGENTS.md`` root file. Returns the sorted list of project-relative POSIX
    paths that were created.

    Args:
        project_name: The new project's name. Used as the target directory name
            and injected into the template answers, so it must be a portable
            single-segment directory name: a non-empty string, not ``.`` or
            ``..``, with no ``<>:"/\\|?*`` or whitespace.
        output_folder: Existing directory the project directory is created in.
            Defaults to the current directory.
        data: Template answers (for example ``author_name``, ``author_email``).
            ``project_name`` is injected automatically, so it need not be passed.
        dry_run: When true, touch nothing at the target. The project is rendered
            into a temp directory only to enumerate the files apply would create,
            and the returned list is the same set apply produces.
        force: When the target directory already exists and is not empty, clear
            its contents first. Without this a non-empty target raises
            :exc:`FileExistsError`.
        defaults: Pass copier's ``defaults`` through, so unanswered questions take
            their template default instead of prompting.

    Returns:
        The sorted project-relative POSIX paths created (apply) or that would be
        created (dry-run).

    Raises:
        ImportError: The optional ``copier`` dependency (the ``[scaffold]``
            extra) is not installed. Raised before any directory is cleared.
        ValueError: *project_name* is not a string, is empty, is ``.`` or
            ``..``, or carries a forbidden character.
        FileNotFoundError: *output_folder* does not exist.
        FileExistsError: The target directory is not empty and *force* is false.
    """
    # ``copier`` is the optional ``[scaffold]`` extra. Import it first, before
    # any validation or clearing, so a lean install fails with the ImportError
    # the CLI translates into an install hint rather than after the target
    # directory has already been cleared.
    from copier import run_copy  # noqa: PLC0415

    if not _is_valid_project_name(project_name):
        raise ValueError("Invalid project name")

    if not os.path.isdir(output_folder):
        raise FileNotFoundError(f'Output folder "{output_folder}" does not exist')

    project_directory = os.path.join(output_folder, project_name)

    # The core injects the project name into the template answers, so callers
    # that already carry answers do not have to remember to add it.
    data_dict = dict(data or {})
    data_dict["project_name"] = project_name

    def render_into(destination: str, quiet: bool = False) -> list[str]:
        """Render the template plus manifest and AGENTS.md into *destination*.

        *quiet* silences copier's own ``create <path>`` log. A dry run renders
        into a temp directory the caller never sees, so that log would announce
        writes at a path that means nothing to them; the returned list is the
        answer instead.
        """
        run_copy(
            f"{protean.__path__[0]}/template",
            destination or ".",
            data=data_dict,
            unsafe=True,  # Trust our own template implicitly.
            defaults=defaults,
            pretend=False,
            quiet=quiet,
        )
        # The manifest is the first thing to create ``.protean/``. AGENTS.md is
        # generated from the diagnostics registry and the installed version (not
        # a static template file), so it stays byte-identical to
        # ``protean docs generate --type=agents``.
        write_manifest(destination or ".")
        (Path(destination or ".") / "AGENTS.md").write_text(
            generate_agents_md(version=protean.__version__), encoding="utf-8"
        )
        return _relative_file_paths(destination or ".")

    if dry_run:
        # Render into an auto-removed system temp dir so the target location is
        # untouched, while the returned list stays byte-accurate to apply. The
        # existing-target handling below is deliberately skipped: a preview must
        # neither clear the target nor raise on a non-empty one.
        with tempfile.TemporaryDirectory() as temp_dir:
            return render_into(temp_dir, quiet=True)

    # Apply only: a non-empty target is cleared with force, or refused without
    # it. This runs after the dry_run branch so a preview touches nothing.
    if os.path.isdir(project_directory) and os.listdir(project_directory):
        if not force:
            raise FileExistsError(
                f'Folder "{project_name}" is not empty. Use --force to overwrite.'
            )
        _clear_directory_contents(project_directory)

    return render_into(project_directory)
