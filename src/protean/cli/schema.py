"""CLI commands for JSON Schema generation.

Usage::

    # Generate all schemas from a live domain
    protean schema generate --domain=my_app

    # Generate from an IR JSON file
    protean schema generate --ir=domain-ir.json

    # Override output directory
    protean schema generate --domain=my_app --output=build/schemas

    # Show schema for a specific element
    protean schema show OrderPlaced --domain=my_app

    # Show schema as raw JSON (for piping)
    protean schema show OrderPlaced --domain=my_app --raw
"""

from __future__ import annotations

import json
from typing import Any

import typer
from rich import print
from rich.console import Console
from rich.syntax import Syntax
from typing_extensions import Annotated

from protean.cli._ir_utils import load_domain_ir, load_ir_file
from protean.ir.generators.base import short_name

app = typer.Typer(no_args_is_help=True)

_CONSOLE = Console()


@app.callback()
def callback():
    """Generate and inspect JSON Schemas for domain elements."""


# ---------------------------------------------------------------------------
# ``protean schema generate``
# ---------------------------------------------------------------------------


@app.command()
def generate(
    domain: Annotated[
        str,
        typer.Option(
            "--domain",
            "-d",
            help="Path to the domain module (e.g. 'my_app.domain')",
        ),
    ] = "",
    ir: Annotated[
        str,
        typer.Option(
            "--ir",
            help="Path to an IR JSON file",
        ),
    ] = "",
    output: Annotated[
        str,
        typer.Option(
            "--output",
            "-o",
            help="Output directory (default: .protean)",
        ),
    ] = ".protean",
) -> None:
    """Generate JSON Schema files for all data-carrying domain elements."""
    if not domain and not ir:
        print("[red]Error:[/red] provide either --domain or --ir")
        raise typer.Abort()

    if domain and ir:
        print("[red]Error:[/red] --domain and --ir are mutually exclusive")
        raise typer.Abort()

    # Load IR
    if domain:
        ir_data = load_domain_ir(domain)
    else:
        ir_data = load_ir_file(ir)

    # Write schemas and IR
    from protean.ir.generators.schema_writer import write_ir, write_schemas

    written = write_schemas(ir_data, output)
    write_ir(ir_data, output)

    # Summary
    print(f"[green]Wrote {len(written)} schema files to {output}/schemas/[/green]")
    for path in written:
        print(f"  {path}")


# ---------------------------------------------------------------------------
# ``protean schema show``
# ---------------------------------------------------------------------------


@app.command()
def show(
    element: Annotated[
        str,
        typer.Argument(help="Element name or FQN to show schema for"),
    ],
    domain: Annotated[
        str,
        typer.Option(
            "--domain",
            "-d",
            help="Path to the domain module (e.g. 'my_app.domain')",
        ),
    ] = "",
    ir: Annotated[
        str,
        typer.Option(
            "--ir",
            help="Path to an IR JSON file",
        ),
    ] = "",
    raw: Annotated[
        bool,
        typer.Option(
            "--raw",
            help="Output plain JSON without syntax highlighting",
        ),
    ] = False,
) -> None:
    """Show JSON Schema for a specific domain element."""
    if not domain and not ir:
        print("[red]Error:[/red] provide either --domain or --ir")
        raise typer.Abort()

    if domain and ir:
        print("[red]Error:[/red] --domain and --ir are mutually exclusive")
        raise typer.Abort()

    # Load IR
    if domain:
        ir_data = load_domain_ir(domain)
    else:
        ir_data = load_ir_file(ir)

    # Generate all schemas
    from protean.ir.generators.schema import generate_schemas

    schemas = generate_schemas(ir_data)

    # Look up element by exact FQN or short name
    schema = _resolve_element(element, schemas)

    # Output
    json_str = json.dumps(schema, indent=2, sort_keys=True)
    if raw:
        typer.echo(json_str)
    else:
        syntax = Syntax(json_str, "json", theme="monokai", word_wrap=True)
        _CONSOLE.print(syntax)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_element(
    name: str, schemas: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Resolve an element by exact FQN or short name.

    If the name matches exactly as a key, return that schema.
    Otherwise, search by short name.  If multiple matches are found,
    print disambiguation options and abort.
    """
    # Exact FQN match
    if name in schemas:
        return schemas[name]

    # Short name match
    matches: list[tuple[str, dict[str, Any]]] = []
    for fqn, schema in schemas.items():
        if short_name(fqn) == name:
            matches.append((fqn, schema))

    if len(matches) == 1:
        return matches[0][1]

    if len(matches) > 1:
        print(f"[yellow]Multiple elements match '{name}':[/yellow]")
        for fqn, _ in matches:
            print(f"  {fqn}")
        print("\n[dim]Use the full FQN to disambiguate.[/dim]")
        raise typer.Abort()

    print(f"[red]Error:[/red] element '{name}' not found")
    print("\n[dim]Available elements:[/dim]")
    for fqn in sorted(schemas.keys()):
        print(f"  {fqn}")
    raise typer.Abort()
