"""CLI commands for Protean's developer-experience (``dx``) integration.

``protean dx`` writes the agent-facing files that make a coding agent correct
and productive with the installed framework version. The canonical set:
``AGENTS.md`` (the canonical, cross-agent instructions), a one-line ``CLAUDE.md``
bridge, and a ``.mcp.json`` registration that points a client at Protean's MCP
server. The per-editor set: Cursor's ``.cursor/rules/protean.mdc`` rule file,
Copilot's ``.github/copilot-instructions.md``, and opencode's ``opencode.json``
config. Writes go through the idempotent managed-file writer
(:mod:`protean.dx.managed_files`), so the framework owns a marked block (for
``.mcp.json`` and ``opencode.json``, its own key-path; for the Cursor rule file,
the whole file) and the user owns everything around it.

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

import difflib
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
    """Write the canonical files and the per-editor files.

    The canonical set (AGENTS.md, the CLAUDE.md bridge, the .mcp.json
    registration) and the per-editor set (the Cursor rule file, the Copilot
    instructions, the opencode config). Creates a missing file and refreshes the
    framework's managed region in an existing one, idempotently. An existing
    ``.mcp.json`` or ``opencode.json`` keeps the user's other servers. A region
    the user edited by hand is reported as a conflict and left untouched; the
    command then exits non-zero.
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

    Writes nothing. Verifies the required baseline (AGENTS.md and the CLAUDE.md
    bridge) plus every optional target already installed (``.mcp.json`` and the
    per-editor files, each verified only once it is present on disk or recorded in
    ``.protean/dx-state.json``). A verified target is drifted when it is missing,
    its managed region is stale, or the user edited inside it (a conflict). An
    optional file the user never chose is not counted. Wire this into CI to fail
    when a project's agent files fall out of step with the framework.
    """
    _check(path)


def _project_root(path: str) -> Path:
    """Return *path* as the project root, or exit ``2`` unless it is a directory.

    Anything that is not an existing directory (a regular file, or a missing or
    mistyped path) would otherwise make every target read as absent, so the verbs
    would disagree (``diff`` exits ``0``, ``check`` ``1``, ``install`` ``2`` when
    ``apply_plan`` later fails). Reject it up front so all verbs answer the same
    environment error, and a typo never silently writes into the wrong place.
    """
    root = Path(path)
    if not root.is_dir():
        print(f"[red]error[/red] {escape(path)} — not a directory")
        raise typer.Exit(code=EXIT_USAGE)
    return root


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

    root = _project_root(path)
    had_conflict = False
    had_error = False
    for managed_file in _render_managed_files():
        try:
            result = apply_managed_file(root, managed_file)
        except ManagedFileConflict as exc:
            had_conflict = True
            print(
                f"[red]conflict[/red] {escape(exc.target)} — "
                f"{escape(_conflict_hint(managed_file))}"
            )
        except ManagedFileError as exc:
            had_error = True
            print(_error_line(managed_file.target, exc))
        else:
            print(_applied_line(result, managed_file))

    if had_error:
        raise typer.Exit(code=EXIT_USAGE)
    if had_conflict:
        raise typer.Exit(code=EXIT_FAILURE)


def _is_present(target_path: Path) -> bool:
    """Return whether something occupies *target_path*, symlinks included.

    ``Path.exists`` follows a symlink, so a dangling one reads as absent.
    ``is_symlink`` covers that case, so a link counts as present whether or not
    it resolves: ``dx`` refuses to write through any symlinked target, and a
    refusal a user can see beats a silent skip.
    """
    return target_path.exists() or target_path.is_symlink()


def _scan(
    path: str, *, show_diff: bool = False, only_installed_optional: bool = False
) -> tuple[bool, bool, bool]:
    """Diff every managed file under *path* and print each target's pending line.

    Mutates nothing; shared by ``diff`` and ``check``. With *show_diff*, also print
    a unified diff of the pending change under each target's line, which is what
    ``diff`` adds over ``check``. Returns ``(had_error, drifted, had_conflict)``:
    ``had_error`` is set when a target is refused or the pack cannot render,
    ``drifted`` when any target is not ``NO_CHANGE`` (missing, stale, or a
    hand-edited conflict), and ``had_conflict`` when any target's managed block
    was edited by hand, which needs resolving before a re-install can update it.

    With *only_installed_optional*, scan the required baseline
    (:data:`~protean.dx.renderers.REQUIRED_TARGETS`) plus only those optional
    targets that are already installed, one being present on disk or recorded in
    ``.protean/dx-state.json``. This is what ``check`` passes so a freshly
    scaffolded project, which ships only the baseline, reports clean while an
    optional editor file the user never chose is not counted as drift. ``diff``
    leaves it off and previews every target.
    """
    from protean.dx import (  # noqa: PLC0415
        ApplyStatus,
        ManagedFileError,
        diff_managed_file,
        load_state,
    )
    from protean.dx.renderers import REQUIRED_TARGETS  # noqa: PLC0415

    root = _project_root(path)
    had_error = False
    drifted = False
    had_conflict = False

    recorded: frozenset[str] = frozenset()
    if only_installed_optional:
        # The scope decision reads the state file. A corrupt or unreadable one is
        # the same environment error (exit 2) the per-file diff path raises via
        # its own ``load_state``. Surface it once here and stop the scan. If it
        # were swallowed, every optional target would read as not-installed and be
        # skipped without warning. ``load_state`` keeps a ``ValueError`` contract
        # for a corrupt file and raises ``ManagedFileError`` for a symlinked state
        # path.
        try:
            recorded = frozenset(load_state(root).entries)
        except (ValueError, ManagedFileError) as exc:
            print(_error_line(".protean/dx-state.json", exc))
            return True, False, False

    for managed_file in _render_managed_files():
        if (
            only_installed_optional
            and managed_file.target not in REQUIRED_TARGETS
            and managed_file.target not in recorded
            # A symlink at the target counts as present, whether or not it
            # resolves. ``exists`` follows the link and reads a dangling one as
            # absent, which would skip it silently; scoping it in instead lets
            # ``diff_managed_file`` below refuse it as the symlinked target it is.
            and not _is_present(root / managed_file.target)
        ):
            continue
        try:
            result = diff_managed_file(root, managed_file)
        except ManagedFileError as exc:
            had_error = True
            print(_error_line(managed_file.target, exc))
        else:
            if result.status is not ApplyStatus.NO_CHANGE:
                drifted = True
            if result.status is ApplyStatus.CONFLICT:
                had_conflict = True
            print(_pending_line(result, managed_file))
            if show_diff:
                body = _unified_diff(root, result)
                if body:
                    # Print the diff plain: it is content, not a status line, and
                    # a stray bracket in it must not be read as rich markup.
                    typer.echo(body)
    return had_error, drifted, had_conflict


def _unified_diff(root: Path, result: ApplyResult) -> str:
    """Return a unified diff of what applying *result* would change, or ``""``.

    Compares the target's current bytes against the content the writer would
    write. Empty for ``NO_CHANGE`` and ``CONFLICT`` (``result.content`` is
    ``None``) and when the target cannot be read.
    """
    if result.content is None:
        return ""
    target_path = root / result.target
    try:
        current = (
            target_path.read_text(encoding="utf-8") if target_path.exists() else ""
        )
    except OSError:  # pragma: no cover - TOCTOU: the scan already read this target
        return ""
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            result.content.splitlines(keepends=True),
            fromfile=f"{result.target} (current)",
            tofile=f"{result.target} (managed)",
        )
    )


def _diff(path: str) -> None:
    """Print what applying each managed file would do, with a unified diff of the
    pending change; mutate nothing.

    Exits ``2`` when a target is refused or the pack cannot render, ``0``
    otherwise, including when there are pending changes: ``diff`` is a read-only
    preview, so pending changes are the report, not a failure.
    """
    had_error, _, _ = _scan(path, show_diff=True)
    if had_error:
        raise typer.Exit(code=EXIT_USAGE)


def _check(path: str) -> None:
    """Report drift for each verified managed file and exit non-zero on any drift.

    Verifies the required baseline plus every optional target already installed
    (see :func:`check`). Writes nothing. Exits ``2`` when a target is refused or
    the pack cannot render, ``1`` when any verified target is missing, stale, or
    conflicted, ``0`` when every verified target is up to date.
    """
    had_error, drifted, had_conflict = _scan(path, only_installed_optional=True)
    if had_error:
        raise typer.Exit(code=EXIT_USAGE)
    if drifted:
        # A conflict is not fixed by re-installing: install refuses a hand-edited
        # block. Point the user at resolving it first, so the next step is
        # actionable for every drift type.
        if had_conflict:
            print(
                "[yellow]Drift detected.[/yellow] Resolve the conflicts above, then "
                "run `protean dx install`."
            )
        else:
            print(
                "[yellow]Drift detected.[/yellow] Run `protean dx install` to update."
            )
        raise typer.Exit(code=EXIT_FAILURE)
    print("[green]Up to date.[/green]")
    raise typer.Exit(code=EXIT_OK)


def _error_line(target: str, exc: Exception) -> str:
    """Render one target's line for a filesystem error on apply/diff/check."""
    return f"[red]error[/red] {escape(target)} — {escape(str(exc))}"


def _managed_region(managed_file: ManagedFile) -> str:
    """Name the region *managed_file*'s merge mode owns, for a diagnostic line.

    A managed-block target owns a marked block, named by its block id. A
    whole-file target owns the whole file. A managed-JSON-keys target has no block
    at all: it owns a key-path, so name the full path (``mcpServers.protean``)
    instead of pointing the user at a Markdown region that does not exist in the
    file.
    """
    from protean.dx import ManagedBlock, ManagedWholeFile  # noqa: PLC0415

    if isinstance(managed_file, ManagedBlock):
        return f"the managed block {managed_file.block_id!r}"
    if isinstance(managed_file, ManagedWholeFile):
        return "the whole file"
    keys = ", ".join(
        repr(".".join((*managed_file.path, key))) for key in managed_file.managed_keys
    )
    plural = "keys" if len(managed_file.managed_keys) > 1 else "key"
    return f"the managed {plural} {keys}"


def _outside_region(managed_file: ManagedFile) -> str:
    """Name where an edit outside the managed region sits, per merge mode.

    A whole-file target has no region outside itself, so it never reports outside
    drift and this never names one for it.
    """
    from protean.dx import ManagedBlock, ManagedWholeFile  # noqa: PLC0415

    if isinstance(managed_file, ManagedBlock):
        return "around the block"
    if isinstance(
        managed_file, ManagedWholeFile
    ):  # pragma: no cover - a whole-file target has no outside region
        return "outside the file"
    return "outside the managed keys"


def _applied_line(result: ApplyResult, managed_file: ManagedFile) -> str:
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
        line += f" (your edits {_outside_region(managed_file)} were kept)"
    return line


def _pending_line(result: ApplyResult, managed_file: ManagedFile) -> str:
    """Render one target's status for ``diff``/``check``, describing the change."""
    from protean.dx import ApplyStatus  # noqa: PLC0415

    target = escape(result.target)
    messages = {
        ApplyStatus.CREATE: f"[cyan]create[/cyan] {target} — not installed yet",
        ApplyStatus.UPDATE: (
            f"[yellow]update[/yellow] {target} — {_managed_region(managed_file)} "
            "is stale"
        ),
        ApplyStatus.NO_CHANGE: f"[green]ok[/green] {target} — up to date",
        ApplyStatus.CONFLICT: (
            f"[red]conflict[/red] {target} — "
            f"{_managed_region(managed_file)} was edited by hand"
        ),
    }
    line = messages[result.status]
    if result.outside_modified and result.status is ApplyStatus.NO_CHANGE:
        line += f" (edited {_outside_region(managed_file)})"
    return line


def _conflict_hint(managed_file: ManagedFile) -> str:
    """Explain a conflict on apply: the region was edited and the write was refused.

    Names the region the target's merge mode owns, so a ``.mcp.json`` conflict
    points at its key-path rather than at a managed block it does not have.
    """
    return (
        f"{_managed_region(managed_file)} was edited by hand; "
        "resolve the edit and re-run"
    )
