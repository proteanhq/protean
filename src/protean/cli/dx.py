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
    protean dx refresh     # re-render what is installed, to that version
    protean dx diff        # show what install would change; write nothing
    protean dx check       # exit non-zero when a target has drifted; write nothing
    protean dx build-plugin  # render the packaged skills into the plugin tree

Both writing verbs are the same idempotent apply, and both leave the user's own
edits alone; they differ in scope. ``install`` writes every target, so it is the
verb that opts a project into ``.mcp.json`` and the per-editor files. ``refresh``
writes the required baseline plus the optional targets already installed, so
re-rendering after an upgrade never adds a file the user did not choose. ``check``
is the CI gate and verifies the same scope ``refresh`` writes. ``diff`` is the
read-only preview of every target. ``build-plugin`` renders the committed Claude
Code plugin tree from the packaged skills; its ``--check`` is the drift guard for
that tree (:mod:`protean.dx.plugin`).
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
    from protean.dx import ApplyResult, ApplyStatus, ManagedFile

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

    ``install`` writes every target, so it is the verb that opts a project into
    the optional files. ``refresh`` re-renders only what the project already has.
    """
    _apply(path)


@app.command()
def refresh(path: Annotated[str, _PATH_OPTION] = ".") -> None:
    """Re-render the managed blocks to the installed framework version.

    Run it after upgrading Protean to bring a project's managed regions up to the
    new version. The same idempotent apply as ``install``, scoped to what the
    project already has: the required baseline (AGENTS.md and the CLAUDE.md
    bridge) plus every optional target present on disk or recorded in
    ``.protean/dx-state.json``. So refreshing a project scaffolded by ``protean
    new``, which carries only the baseline, does not create ``.mcp.json`` or the
    per-editor files; ``install`` is the verb that adds those.
    """
    _apply(path, only_installed_optional=True)


@app.command()
def diff(path: Annotated[str, _PATH_OPTION] = ".") -> None:
    """Show what install would change, and write nothing."""
    _diff(path)


@app.command()
def check(path: Annotated[str, _PATH_OPTION] = ".") -> None:
    """Exit non-zero when a target has drifted from the installed version.

    Writes nothing. Verifies the same scope ``refresh`` writes: the required
    baseline (AGENTS.md and the CLAUDE.md bridge) plus every optional target
    already installed (``.mcp.json`` and the per-editor files, each verified only
    once it is present on disk or recorded in ``.protean/dx-state.json``). A
    verified target is drifted when it is missing, its managed region is stale, or
    the user edited inside it (a conflict). An optional file the user never chose
    is not counted. Wire this into CI to fail
    when a project's agent files fall out of step with the framework.
    """
    _check(path)


@app.command(name="build-plugin")
def build_plugin(
    output: Annotated[
        str,
        typer.Option(
            "--output",
            "-o",
            help="Directory to write the plugin tree into. Defaults to the current directory.",
        ),
    ] = ".",
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help=(
                "Compare the committed plugin tree against a fresh render, "
                "write nothing, and exit non-zero on drift."
            ),
        ),
    ] = False,
) -> None:
    """Render the packaged skills into the Claude Code plugin tree.

    Writes ``.claude-plugin/marketplace.json`` and the ``plugins/protean/`` tree
    from the packaged pack, stamped to the installed framework version. ``--check``
    is the drift guard: it re-renders in memory, compares byte-exact against the
    committed tree, writes nothing, and exits ``1`` on any drift. The bare verb
    (re)writes the tree so it matches the render exactly, pruning any file a
    removed skill left behind.
    """
    if check:
        _check_plugin(output)
    else:
        _write_plugin_tree(output)


def _plugin_version() -> str:
    """Return the framework version the plugin tree is stamped to, or exit ``2``.

    Reading the pack version fails only when the pack is stripped or unreadable
    (a zip-imported wheel with the data removed). Surface that as the same clean
    environment error (exit ``2``) the other verbs give, not a raw traceback.
    """
    from protean.dx.pack import PACK_VERSION  # noqa: PLC0415

    return PACK_VERSION


def _write_plugin_tree(output: str) -> None:
    """Write the plugin tree under *output*; exit ``2`` when the target is unusable."""
    from protean.dx.plugin import write_plugin  # noqa: PLC0415

    root = _project_root(output)
    try:
        write_plugin(root, _plugin_version())
    except OSError as exc:
        print(f"[red]error[/red] could not write the plugin tree — {escape(str(exc))}")
        raise typer.Exit(code=EXIT_USAGE) from exc
    print(f"[green]Wrote the Claude Code plugin tree under {escape(str(root))}[/green]")


def _check_plugin(output: str) -> None:
    """Report drift between the committed plugin tree and a fresh render.

    Writes nothing. Exits ``2`` when *output* is not a directory, ``1`` when the
    committed tree drifts from the render (a file missing, stale, or orphaned),
    ``0`` when it matches byte for byte.
    """
    from protean.dx.plugin import plugin_drift  # noqa: PLC0415

    root = _project_root(output)
    drift = plugin_drift(root, _plugin_version())
    if drift:
        for line in drift:
            print(f"[yellow]drift[/yellow] {escape(line)}")
        print(
            "[yellow]Drift detected.[/yellow] Run `protean dx build-plugin` to "
            "regenerate the tree."
        )
        raise typer.Exit(code=EXIT_FAILURE)
    print("[green]Plugin tree is up to date.[/green]")
    raise typer.Exit(code=EXIT_OK)


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


def _recorded_targets(root: Path) -> frozenset[str] | None:
    """Return the targets ``.protean/dx-state.json`` records, or ``None`` on error.

    The scope both ``refresh`` and ``check`` work out reads the state file. A
    corrupt or unreadable one is the same environment error (exit ``2``) the
    per-file paths raise via their own ``load_state``. Report it once here and let
    the caller stop. If it were swallowed, every optional target would read as
    not-installed and be skipped without warning. ``load_state`` keeps a
    ``ValueError`` contract for a corrupt or unreadable file and raises
    ``ManagedFileError`` for a symlinked state path.
    """
    from protean.dx import ManagedFileError, load_state  # noqa: PLC0415

    try:
        return frozenset(load_state(root).entries)
    except (ValueError, ManagedFileError) as exc:
        print(_error_line(".protean/dx-state.json", exc))
        return None


def _in_scope(target: str, status: ApplyStatus, recorded: frozenset[str]) -> bool:
    """Say whether *target* is in the installed scope ``refresh`` and ``check`` use.

    In scope: the required baseline
    (:data:`~protean.dx.renderers.REQUIRED_TARGETS`), and any optional target
    already installed, meaning present on disk (*status* is anything but
    ``CREATE``) or recorded in ``.protean/dx-state.json``. Out of scope: an
    optional target the user never chose, so ``check`` does not count it as drift
    and ``refresh`` does not write it. ``install`` is the verb that opts in.
    """
    from protean.dx import ApplyStatus  # noqa: PLC0415
    from protean.dx.renderers import REQUIRED_TARGETS  # noqa: PLC0415

    if target in REQUIRED_TARGETS or target in recorded:
        return True
    return status is not ApplyStatus.CREATE


def _apply(path: str, *, only_installed_optional: bool = False) -> None:
    """Apply every managed file under *path*, reporting each target's outcome.

    A conflict on one file is reported and the remaining files are still applied,
    so a partial install completes what it safely can. Exits ``2`` when a target
    is refused (unreadable or malformed, a refused symlink or out-of-root path,
    or a corrupt state file) or the pack cannot render, ``1`` when any block
    conflicts, ``0`` otherwise.

    With *only_installed_optional*, write the required baseline plus only those
    optional targets already installed, the same scope ``check`` verifies (see
    :func:`_in_scope`). This is what ``refresh`` passes, so re-rendering a
    baseline-only project to a new version does not opt it into ``.mcp.json`` and
    every editor file. ``install`` leaves the flag off and writes every target.
    """
    from protean.dx import (  # noqa: PLC0415
        ManagedFileConflict,
        ManagedFileError,
        apply_managed_file,
        diff_managed_file,
    )

    root = _project_root(path)
    had_conflict = False
    had_error = False

    recorded: frozenset[str] = frozenset()
    if only_installed_optional:
        scoped = _recorded_targets(root)
        if scoped is None:
            raise typer.Exit(code=EXIT_USAGE)
        recorded = scoped

    for managed_file in _render_managed_files():
        if only_installed_optional:
            # Decide scope from the same reader ``check`` uses, so ``refresh``
            # writes exactly the set ``check`` verifies. ``diff_managed_file``
            # runs the path checks and reports ``CREATE`` only for a target that
            # is genuinely absent; a refused target is reported here instead of
            # being skipped as uninstalled.
            try:
                pending = diff_managed_file(root, managed_file)
            except ManagedFileError as exc:
                had_error = True
                print(_error_line(managed_file.target, exc))
                continue
            if not _in_scope(managed_file.target, pending.status, recorded):
                continue
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

    With *only_installed_optional*, report the installed scope (see
    :func:`_in_scope`): the required baseline plus only those optional targets
    already installed. This is what ``check`` passes so a freshly scaffolded
    project, which ships only the baseline, reports clean while an optional editor
    file the user never chose is not counted as drift. Every target is still
    diffed: an optional one drops out only when the diff comes back ``CREATE`` and
    the state file has no entry for it, so a refused target is reported either
    way. ``diff`` leaves the flag off and previews every target.
    """
    from protean.dx import (  # noqa: PLC0415
        ApplyStatus,
        ManagedFileError,
        diff_managed_file,
    )

    root = _project_root(path)
    had_error = False
    drifted = False
    had_conflict = False

    recorded: frozenset[str] = frozenset()
    if only_installed_optional:
        scoped = _recorded_targets(root)
        if scoped is None:
            return True, False, False
        recorded = scoped

    for managed_file in _render_managed_files():
        # Diff first, scope after. ``diff_managed_file`` is the one reader of the
        # target: it runs the path checks (outside the root, a symlink anywhere on
        # the way) and reports ``CREATE`` only for a target that is genuinely
        # absent. Deciding scope from its result instead of a separate presence
        # probe keeps ``check`` from stepping around those checks, and keeps the
        # filesystem errors inside this one boundary.
        try:
            result = diff_managed_file(root, managed_file)
        except ManagedFileError as exc:
            had_error = True
            print(_error_line(managed_file.target, exc))
            continue
        if only_installed_optional and not _in_scope(
            managed_file.target, result.status, recorded
        ):
            # An optional target the user never chose: absent on disk and not
            # recorded in the state file. Not drift, so leave it out of the report.
            continue
        if result.status is not ApplyStatus.NO_CHANGE:
            drifted = True
        if result.status is ApplyStatus.CONFLICT:
            had_conflict = True
        print(_pending_line(result, managed_file))
        if show_diff:
            body = _unified_diff(root, result)
            if body:
                # Print the diff plain: it is content, not a status line, and a
                # stray bracket in it must not be read as rich markup.
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
        # ``refresh`` is the fix: it writes exactly the scope ``check`` verifies,
        # so it never adds an optional file the project does not have. A conflict
        # is not fixed by re-applying at all: the writer refuses a hand-edited
        # block. Point the user at resolving it first, so the next step is
        # actionable for every drift type.
        if had_conflict:
            print(
                "[yellow]Drift detected.[/yellow] Resolve the conflicts above, then "
                "run `protean dx refresh`."
            )
        else:
            print(
                "[yellow]Drift detected.[/yellow] Run `protean dx refresh` to update."
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
