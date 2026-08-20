"""CLI command for ``protean add`` — scaffold a new element slice.

``add`` computes a :class:`~protean.scaffold.ChangePlan` for one element slice
and, by default, writes it to disk. Pass ``--dry-run`` to preview the plan
without touching the filesystem.

Usage::

    # Write the aggregate slice for `Order` into the current project
    protean add aggregate Order

    # Preview the plan without writing anything
    protean add aggregate Order --dry-run

    # Point at a project directory other than the current one
    protean add aggregate Order --path ./my-project

Only ``aggregate`` is supported for now; it emits one write-side vertical slice
(the aggregate, its create command, its created event, and the command handler).

Apply is create-only and all-or-nothing: if any target file already exists, or a
write fails partway, the command changes nothing and exits ``1``. An unsupported
element type, an invalid name, a project the planner cannot resolve, or the
contradictory ``--dry-run --apply`` combination exits ``2`` (a usage error).
"""

from typing import Annotated

import typer

from protean.scaffold import (
    AddPlanError,
    ApplyError,
    apply_plan,
    plan_add_slice,
    render_preview,
)

# A usage error: a bad argument, a project that could not be resolved, or a
# contradictory flag combination. Matches the CLI-wide convention (and Click's
# own default) that 2 means "usage".
_EXIT_USAGE = 2

# An apply failure: a target already exists, or a write failed partway. A
# different class from a usage error, so it exits 1, not 2.
_EXIT_FAILURE = 1


def add(
    element_type: Annotated[
        str,
        typer.Argument(help="The element type to add. Only 'aggregate' for now."),
    ],
    name: Annotated[
        str,
        typer.Argument(help="The aggregate name, e.g. 'Order'."),
    ],
    path: Annotated[
        str,
        typer.Option(
            "--path",
            "-p",
            help="Project directory to plan against (default: current directory).",
        ),
    ] = ".",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Preview the plan without writing anything.",
        ),
    ] = False,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Write the plan to disk (the default). Cannot be used with --dry-run.",
        ),
    ] = False,
) -> None:
    """Scaffold a new element slice, or preview the plan with ``--dry-run``."""
    # --dry-run and --apply are contradictory: one previews, the other writes.
    # Reject the combination as a usage error rather than silently favouring one.
    if dry_run and apply:
        typer.echo("Error: --dry-run and --apply cannot be used together.")
        raise typer.Exit(code=_EXIT_USAGE)

    try:
        plan = plan_add_slice(path, element_type, name)
    except AddPlanError as exc:
        # Every planning failure is a usage error: the arguments or the project
        # layout are wrong. Print the message and exit 2. Use typer.echo, not
        # rich's print: the preview and some messages carry bracketed tokens
        # (e.g. `Annotated[str, Field(...)]`) that rich would parse as markup.
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=_EXIT_USAGE) from exc

    if dry_run:
        typer.echo(render_preview(plan))
        return

    try:
        written = apply_plan(path, plan)
    except ApplyError as exc:
        # An apply failure (a conflict or an I/O error) is a different class from
        # a usage error, so it exits 1. On a mid-write failure the applier has
        # already rolled the tree back to its pre-apply state.
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=_EXIT_FAILURE) from exc

    typer.echo(_format_applied(written))


def _format_applied(written: tuple[str, ...]) -> str:
    """Render the confirmation naming the files ``add`` wrote, in plan order."""
    count = len(written)
    noun = "file" if count == 1 else "files"
    lines = [f"Wrote {count} {noun}:"]
    lines.extend(f"  {path}" for path in written)
    return "\n".join(lines)
