"""CLI commands for Protean's developer-experience (``dx``) integration.

``protean dx`` writes the agent-facing files that make a coding agent correct
and productive with the installed framework version: ``AGENTS.md`` (the
canonical, cross-agent instructions) and a one-line ``CLAUDE.md`` bridge. Writes
go through the idempotent managed-file writer (:mod:`protean.dx.managed_files`),
so the framework owns a marked block in each file and the user owns everything
around it.

Verbs::

    protean dx install     # write the files (create or refresh the block)
    protean dx refresh     # re-render the block to the installed version
    protean dx diff        # show what install would change; write nothing
    protean dx check       # exit non-zero when a target has drifted; write nothing

``install`` and ``refresh`` are the same idempotent apply: both create a missing
file and refresh a stale block, and both leave the user's own edits alone.
``check`` is the CI gate. ``diff`` is the read-only preview.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich import print
from rich.markup import escape

from protean.cli.result import EXIT_FAILURE, EXIT_OK, EXIT_USAGE

if TYPE_CHECKING:
    from protean.dx import ApplyResult, ManagedFile

app = typer.Typer(no_args_is_help=True)

_PATH_OPTION = typer.Option(
    "--path",
    "-p",
    help="Project directory to write into or check. Defaults to the current directory.",
)


@app.callback()
def callback() -> None:
    """Install and maintain Protean's agent-facing files in a project."""


@app.command()
def install(path: Annotated[str, _PATH_OPTION] = ".") -> None:
    """Write AGENTS.md and the CLAUDE.md bridge into a project.

    Creates a missing file and refreshes the framework's managed block in an
    existing one, idempotently. A block the user edited by hand is reported as a
    conflict and left untouched; the command then exits non-zero.
    """
    _apply(path)


@app.command()
def refresh(path: Annotated[str, _PATH_OPTION] = ".") -> None:
    """Re-render the managed blocks to the installed framework version.

    The same idempotent apply as ``install``: run it after upgrading Protean to
    bring a project's AGENTS.md block up to the new version.
    """
    _apply(path)


@app.command()
def diff(path: Annotated[str, _PATH_OPTION] = ".") -> None:
    """Show what install would change, and write nothing."""
    _diff(path)


@app.command()
def check(path: Annotated[str, _PATH_OPTION] = ".") -> None:
    """Exit non-zero when a target has drifted from the installed version.

    Writes nothing. A target is drifted when it is missing, its managed block is
    stale, or the user edited inside the block (a conflict). Wire this into CI to
    fail when a project's agent files fall out of step with the framework.
    """
    _check(path)


def _render_managed_files() -> tuple[ManagedFile, ...]:
    """Build the managed files for the installed version, or exit ``2`` on failure.

    Rendering reads the packaged pack and the diagnostics registry. A stripped or
    unreadable pack (a zip-imported wheel with the data removed) fails here,
    before any target is touched. Surface it as the same environment error
    (exit ``2``, a clean line) a bad target gets, so a broken pack never escapes
    as a raw traceback misclassified as exit ``1``.
    """
    # Lazy imports keep `protean --help` from pulling in the dx substrate and the
    # diagnostics registry on every CLI invocation.
    from protean.dx.pack import PACK_VERSION  # noqa: PLC0415
    from protean.dx.renderers import managed_files  # noqa: PLC0415

    # Any render failure (an unreadable pack, a registry error, a body that fails
    # ManagedBlock validation) is an environment error, so catch broadly and
    # surface one clean line and exit 2 rather than a raw traceback.
    try:
        return managed_files(PACK_VERSION)
    except Exception as exc:
        print(f"[red]error[/red] could not render the dx files — {escape(str(exc))}")
        raise typer.Exit(code=EXIT_USAGE) from exc


def _apply(path: str) -> None:
    """Apply every managed file under *path*, reporting each target's outcome.

    A conflict on one file is reported and the remaining files are still applied,
    so a partial install completes what it safely can. Exits ``2`` when a target
    is refused (unreadable or malformed, a refused symlink or out-of-root path,
    or a corrupt state file) or the pack cannot render, ``1`` when any block
    conflicts, ``0`` otherwise.
    """
    from protean.dx import (  # noqa: PLC0415
        ManagedFileConflict,
        ManagedFileError,
        apply_managed_file,
    )

    root = Path(path)
    had_conflict = False
    had_error = False
    for managed_file in _render_managed_files():
        try:
            result = apply_managed_file(root, managed_file)
        except ManagedFileConflict as exc:
            had_conflict = True
            print(
                f"[red]conflict[/red] {escape(exc.target)} — "
                f"{escape(_conflict_hint(exc.managed))}"
            )
        except ManagedFileError as exc:
            had_error = True
            print(_error_line(managed_file.target, exc))
        else:
            print(_applied_line(result))

    if had_error:
        raise typer.Exit(code=EXIT_USAGE)
    if had_conflict:
        raise typer.Exit(code=EXIT_FAILURE)


def _scan(path: str) -> tuple[bool, bool]:
    """Diff every managed file under *path* and print each target's pending line.

    Mutates nothing; shared by ``diff`` and ``check``. Returns ``(had_error,
    drifted)``: ``had_error`` is set when a target is refused or the pack cannot
    render, ``drifted`` when any target is not ``NO_CHANGE`` (missing, stale, or a
    hand-edited conflict).
    """
    from protean.dx import (  # noqa: PLC0415
        ApplyStatus,
        ManagedFileError,
        diff_managed_file,
    )

    root = Path(path)
    had_error = False
    drifted = False
    for managed_file in _render_managed_files():
        try:
            result = diff_managed_file(root, managed_file)
        except ManagedFileError as exc:
            had_error = True
            print(_error_line(managed_file.target, exc))
        else:
            if result.status is not ApplyStatus.NO_CHANGE:
                drifted = True
            print(_pending_line(result))
    return had_error, drifted


def _diff(path: str) -> None:
    """Print what applying each managed file would do; mutate nothing.

    Exits ``2`` when a target is refused or the pack cannot render, ``0``
    otherwise, including when there are pending changes: ``diff`` is a read-only
    preview, so pending changes are the report, not a failure.
    """
    had_error, _ = _scan(path)
    if had_error:
        raise typer.Exit(code=EXIT_USAGE)


def _check(path: str) -> None:
    """Report drift for each managed file and exit non-zero when any has drifted.

    Writes nothing. Exits ``2`` when a target is refused or the pack cannot
    render, ``1`` when any target is missing, stale, or conflicted, ``0`` when
    every target is up to date.
    """
    had_error, drifted = _scan(path)
    if had_error:
        raise typer.Exit(code=EXIT_USAGE)
    if drifted:
        print("[yellow]Drift detected.[/yellow] Run `protean dx install` to update.")
        raise typer.Exit(code=EXIT_FAILURE)
    print("[green]Up to date.[/green]")
    raise typer.Exit(code=EXIT_OK)


def _error_line(target: str, exc: Exception) -> str:
    """Render one target's line for a filesystem error on apply/diff/check."""
    return f"[red]error[/red] {escape(target)} — {escape(str(exc))}"


def _applied_line(result: ApplyResult) -> str:
    """Render one target's outcome after an apply, in the past tense."""
    from protean.dx import ApplyStatus  # noqa: PLC0415

    messages = {
        ApplyStatus.CREATE: f"[green]created[/green] {escape(result.target)}",
        ApplyStatus.UPDATE: f"[green]updated[/green] {escape(result.target)}",
        ApplyStatus.NO_CHANGE: (
            f"[green]ok[/green] {escape(result.target)} — already up to date"
        ),
    }
    line = messages[result.status]
    if result.outside_modified:
        line += " (your edits around the block were kept)"
    return line


def _pending_line(result: ApplyResult) -> str:
    """Render one target's status for ``diff``/``check``, describing the change."""
    from protean.dx import ApplyStatus  # noqa: PLC0415

    target = escape(result.target)
    messages = {
        ApplyStatus.CREATE: f"[cyan]create[/cyan] {target} — not installed yet",
        ApplyStatus.UPDATE: f"[yellow]update[/yellow] {target} — block is stale",
        ApplyStatus.NO_CHANGE: f"[green]ok[/green] {target} — up to date",
        ApplyStatus.CONFLICT: (
            f"[red]conflict[/red] {target} — the managed block was edited by hand"
        ),
    }
    line = messages[result.status]
    if result.outside_modified and result.status is ApplyStatus.NO_CHANGE:
        line += " (edited around the block)"
    return line


def _conflict_hint(managed: str) -> str:
    """Explain a conflict on apply: the block was edited and the write was refused."""
    return (
        f"the managed block {managed!r} was edited by hand; resolve the edit and re-run"
    )
