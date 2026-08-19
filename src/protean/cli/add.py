"""CLI command for ``protean add`` — preview a new element slice.

``add`` computes a :class:`~protean.scaffold.ChangePlan` for one element slice and
prints it. It writes nothing: this stage is a read-only preview. Applying the plan
(actually creating the files) is a later command.

Usage::

    # Preview the aggregate slice for `Order` in the current project
    protean add aggregate Order

    # Point at a project directory other than the current one
    protean add aggregate Order --path ./my-project

Only ``aggregate`` is supported for now; it emits one write-side vertical slice
(the aggregate, its create command, its created event, and the command handler).
An unsupported element type, an invalid name, or a project the planner cannot
resolve exits ``2`` (a usage error) with a clear message.
"""

from typing import Annotated

import typer

from protean.scaffold import AddPlanError, plan_add_slice, render_preview

# A usage error: a bad argument or a project that could not be resolved. Matches
# the CLI-wide convention (and Click's own default) that 2 means "usage".
_EXIT_USAGE = 2


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
) -> None:
    """Preview the ChangePlan for a new element slice, without writing anything."""
    try:
        plan = plan_add_slice(path, element_type, name)
    except AddPlanError as exc:
        # Every planning failure is a usage error: the arguments or the project
        # layout are wrong. Print the message and exit 2. Use typer.echo, not
        # rich's print: the preview and some messages carry bracketed tokens
        # (e.g. `Annotated[str, Field(...)]`) that rich would parse as markup.
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=_EXIT_USAGE) from exc

    typer.echo(render_preview(plan))
