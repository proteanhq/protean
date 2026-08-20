"""CLI commands for documentation generation.

Usage::

    # Generate all docs from a live domain
    protean docs generate --domain=my_app

    # Generate from an IR JSON file
    protean docs generate --ir=domain-ir.json

    # Generate only cluster diagrams
    protean docs generate --domain=my_app --type=clusters

    # Generate raw Mermaid (no Markdown fences)
    protean docs generate --domain=my_app --type=events --format=mermaid

    # Generate the EventModeling slice timeline
    protean docs generate --domain=my_app --type=event-model

    # Generate the versioned llms.txt context pack (framework layer only)
    protean docs generate --type=llms

    # ...with the project overlay from a domain or IR file
    protean docs generate --domain=my_app --type=llms

    # Write output to a file
    protean docs generate --domain=my_app --output=docs/architecture.md

    # Filter to a specific cluster
    protean docs generate --domain=my_app --type=clusters --cluster=app.Order

    # Run the mkdocs live preview server
    protean docs preview
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Annotated, Any

import typer
from rich import print

import protean
from protean.cli._ir_utils import load_domain_ir, load_ir_file
from protean.ir.generators.base import mermaid_fence

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback() -> None:
    """Generate and preview architecture documentation."""


@app.command()
def preview() -> None:
    """Run a live preview server"""
    with contextlib.suppress(KeyboardInterrupt):
        subprocess.call(
            [
                sys.executable,
                "-m",
                "mkdocs",
                "serve",
                "--livereload",
                "--dev-addr=0.0.0.0:8000",
            ]
        )


# ---------------------------------------------------------------------------
# ``protean docs generate``
# ---------------------------------------------------------------------------

_VALID_TYPES = (
    "clusters",
    "events",
    "handlers",
    "catalog",
    "event-model",
    "llms",
    "all",
)


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
    type: Annotated[
        str,
        typer.Option(
            "--type",
            "-t",
            help=(
                "Generator type: clusters, events, handlers, catalog, "
                "event-model, llms, or all (default)"
            ),
        ),
    ] = "all",
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: 'markdown' (fenced code blocks) or 'mermaid' (raw diagrams)",
        ),
    ] = "markdown",
    output: Annotated[
        str,
        typer.Option(
            "--output",
            "-o",
            help="Write output to file instead of stdout",
        ),
    ] = "",
    cluster: Annotated[
        str,
        typer.Option(
            "--cluster",
            help="Filter to a specific cluster FQN (for --type=clusters or --type=all)",
        ),
    ] = "",
    annotations: Annotated[
        str,
        typer.Option(
            "--annotations",
            help=(
                "Path to an annotations TOML file (for --type=event-model). "
                "Defaults to .protean/annotations.toml when present."
            ),
        ),
    ] = "",
) -> None:
    """Generate architecture documentation from a Protean domain or IR file."""
    # --- Validate inputs --------------------------------------------------
    # --type=llms is the one type that runs with no source: it emits the
    # framework layer alone. Every other type still requires --domain or --ir.
    if not domain and not ir and type != "llms":
        print("[red]Error:[/red] provide either --domain or --ir")
        raise typer.Abort()

    if domain and ir:
        print("[red]Error:[/red] --domain and --ir are mutually exclusive")
        raise typer.Abort()

    if type not in _VALID_TYPES:
        print(
            f"[red]Error:[/red] invalid --type: {type!r}. "
            f"Choose from: {', '.join(_VALID_TYPES)}"
        )
        raise typer.Abort()

    if format not in ("markdown", "mermaid"):
        print(
            f"[red]Error:[/red] invalid --format: {format!r}. "
            "Choose 'markdown' or 'mermaid'"
        )
        raise typer.Abort()

    if cluster and type not in ("clusters", "all"):
        print(
            "[red]Error:[/red] --cluster can only be used with --type=clusters or --type=all"
        )
        raise typer.Abort()

    if annotations and type != "event-model":
        print(
            "[red]Error:[/red] --annotations can only be used with --type=event-model"
        )
        raise typer.Abort()

    if format == "mermaid" and type == "catalog":
        print(
            "[red]Error:[/red] --format=mermaid is not supported for --type=catalog "
            "(catalog outputs Markdown tables, not Mermaid diagrams)"
        )
        raise typer.Abort()

    # --- Load IR ----------------------------------------------------------
    # --type=llms with no source skips IR loading and emits the framework
    # layer alone; with a source it loads the IR and adds the project overlay.
    ir_data: dict[str, Any] | None
    if not domain and not ir:
        ir_data = None
    else:
        ir_data = load_domain_ir(domain) if domain else load_ir_file(ir)

    # --- Load annotations (event-model only) ------------------------------
    # Loaded and validated here, before any generation or file write, so a
    # malformed file aborts the command without leaving partial output.
    annotations_map = _resolve_annotations(type, annotations)

    # --- Generate output --------------------------------------------------
    content = _generate_output(
        ir_data,
        doc_type=type,
        output_format=format,
        cluster_fqn=cluster,
        annotations=annotations_map,
    )

    # --- Emit output ------------------------------------------------------
    if output:
        _write_output(output, content)
        print(f"[green]Documentation written to {output}[/green]")
    else:
        typer.echo(content)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_ANNOTATIONS_FILENAME = "annotations.toml"
_DEFAULT_ANNOTATIONS_PATH = Path(".protean") / _ANNOTATIONS_FILENAME


def _resolve_annotations(doc_type: str, annotations_option: str) -> dict[str, Any]:
    """Load the annotations file that applies to this run.

    Only ``--type=event-model`` reads annotations. An explicit
    ``--annotations`` path must exist (a missing explicit path is a user
    error). Without the option, the default ``.protean/annotations.toml`` is
    read when it exists and silently skipped when it does not.

    Aborts the command with a message naming the file on a missing explicit
    path, a parse error, or an invalid entry shape.
    """
    if doc_type != "event-model":
        return {}

    if annotations_option:
        path = Path(annotations_option)
        if not path.exists():
            print(f"[red]Error:[/red] annotations file not found: {annotations_option}")
            raise typer.Abort()
    else:
        path = _DEFAULT_ANNOTATIONS_PATH
        if not path.exists():
            return {}

    try:
        return _load_annotations(path)
    except ValueError as exc:
        print(f"[red]Error:[/red] {exc}")
        raise typer.Abort() from exc


def _load_annotations(path: Path) -> dict[str, Any]:
    """Parse and validate an annotations TOML file.

    Returns a mapping of element FQN to its entry (``{"note": str}`` with an
    optional ``"owner": str``). Raises :exc:`ValueError`, naming *path*, when
    the file is unreadable, not valid UTF-8, not valid TOML, or holds an entry
    that is not a table with a non-empty string ``note`` (and, when present, a
    string ``owner``).
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Could not read {path}: {exc}") from exc

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path} is not valid UTF-8: {exc}") from exc

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {path}: {exc}") from exc

    raw_annotations = data.get("annotations", {})
    if not isinstance(raw_annotations, dict):
        raise ValueError(f"'annotations' in {path} must be a table")

    result: dict[str, Any] = {}
    for fqn, entry in raw_annotations.items():
        if not isinstance(entry, dict):
            raise ValueError(
                f"Annotation for {fqn!r} in {path} must be a table with a string 'note'"
            )
        note = entry.get("note")
        if not isinstance(note, str) or not note.strip():
            raise ValueError(
                f"Annotation for {fqn!r} in {path} must have a non-empty string 'note'"
            )
        validated: dict[str, Any] = {"note": note}
        if "owner" in entry:
            owner = entry["owner"]
            if not isinstance(owner, str):
                raise ValueError(f"'owner' for {fqn!r} in {path} must be a string")
            validated["owner"] = owner
        result[fqn] = validated

    return result


def _generate_output(
    ir_data: dict[str, Any] | None,
    *,
    doc_type: str,
    output_format: str,
    cluster_fqn: str,
    annotations: dict[str, Any] | None = None,
) -> str:
    """Dispatch to the appropriate generator(s) and assemble the result.

    ``ir_data`` is ``None`` only for ``--type=llms`` run with no source, which
    emits the framework layer alone. Every other type requires a source, so
    ``ir_data`` is a dict on their paths.
    """
    sections: list[str] = []

    # llms is deliberately not part of the "all" bundle: it is a distinct
    # context-pack view (and the only type that runs with no IR at all).
    if doc_type == "llms":
        return _generate_llms(ir_data)

    # From here every type requires an IR; the guard above and the source
    # validation in ``generate`` guarantee ir_data is a dict on these paths.
    assert ir_data is not None

    if doc_type in ("clusters", "all"):
        sections.append(_generate_clusters(ir_data, output_format, cluster_fqn))

    if doc_type in ("events", "all"):
        sections.append(_generate_events(ir_data, output_format))

    if doc_type in ("handlers", "all"):
        sections.append(_generate_handlers(ir_data, output_format))

    if doc_type in ("catalog", "all"):
        sections.append(_generate_catalog(ir_data))

    # event-model is deliberately not part of the "all" bundle: it is a
    # distinct slice-timeline view, not one more section of the combined docs.
    if doc_type == "event-model":
        sections.append(
            _generate_event_model(ir_data, output_format, annotations or {})
        )

    return "\n\n".join(sections)


def _generate_clusters(
    ir_data: dict[str, Any],
    output_format: str,
    cluster_fqn: str,
) -> str:
    """Generate cluster diagrams."""
    from protean.ir.generators.clusters import generate_cluster_diagram  # noqa: PLC0415

    if cluster_fqn:
        raw = generate_cluster_diagram(ir_data, cluster_fqn=cluster_fqn)
        if output_format == "mermaid":
            return raw
        return mermaid_fence(raw, title="Aggregate Cluster")

    # For --type=all or --type=clusters without --cluster filter.
    clusters = ir_data.get("clusters", {})

    if output_format == "mermaid":
        # Raw Mermaid: emit a single combined classDiagram (multiple
        # top-level classDiagram declarations are invalid Mermaid).
        return generate_cluster_diagram(ir_data)

    # Markdown: one fenced diagram per cluster for readability.
    if not clusters:
        raw = generate_cluster_diagram(ir_data)
        return mermaid_fence(raw, title="Aggregate Clusters")

    parts: list[str] = []
    for cfqn in sorted(clusters):
        raw = generate_cluster_diagram(ir_data, cluster_fqn=cfqn)
        cluster_name = cfqn.rsplit(".", 1)[-1] if "." in cfqn else cfqn
        parts.append(mermaid_fence(raw, title=f"Cluster: {cluster_name}"))

    return "\n\n".join(parts)


def _generate_events(ir_data: dict[str, Any], output_format: str) -> str:
    """Generate event flow diagram(s).

    In Markdown mode, splits into one diagram per cluster (linear flow)
    plus a separate downstream consumers diagram.  In Mermaid mode,
    emits a single combined diagram for backward compatibility.
    """
    from protean.ir.generators.events import (  # noqa: PLC0415
        generate_cluster_event_flow,
        generate_downstream_consumers_diagram,
        generate_event_flow_diagram,
    )

    if output_format == "mermaid":
        return generate_event_flow_diagram(ir_data)

    clusters = ir_data.get("clusters", {})
    parts: list[str] = []

    for cfqn in sorted(clusters):
        raw = generate_cluster_event_flow(ir_data, cfqn)
        if raw != "flowchart TD":
            name = cfqn.rsplit(".", 1)[-1] if "." in cfqn else cfqn
            parts.append(mermaid_fence(raw, title=f"Event Flow: {name}"))

    downstream = generate_downstream_consumers_diagram(ir_data)
    if downstream != "flowchart LR":
        parts.append(mermaid_fence(downstream, title="Downstream Consumers"))

    return "\n\n".join(parts) or mermaid_fence("flowchart LR", title="Event Flows")


def _generate_handlers(ir_data: dict[str, Any], output_format: str) -> str:
    """Generate handler wiring diagram(s).

    In Markdown mode, splits into one diagram per handler category.
    In Mermaid mode, emits a single combined diagram for backward
    compatibility.
    """
    from protean.ir.generators.handlers import (  # noqa: PLC0415
        generate_cluster_command_handler_diagram,
        generate_event_handler_diagram,
        generate_handler_wiring_diagram,
        generate_process_manager_diagram,
        generate_single_projector_diagram,
        generate_subscriber_diagram,
    )

    if output_format == "mermaid":
        return generate_handler_wiring_diagram(ir_data)

    sections: list[str] = []

    # Command handlers — one diagram per aggregate cluster
    clusters = ir_data.get("clusters", {})
    for cfqn in sorted(clusters):
        raw = generate_cluster_command_handler_diagram(ir_data, cfqn)
        if raw != "flowchart LR":
            name = cfqn.rsplit(".", 1)[-1] if "." in cfqn else cfqn
            sections.append(mermaid_fence(raw, title=f"Command Handlers: {name}"))

    # Event handlers, process managers, subscribers — one diagram each
    for title, gen in [
        ("Event Handlers", generate_event_handler_diagram),
        ("Process Managers", generate_process_manager_diagram),
        ("Subscribers", generate_subscriber_diagram),
    ]:
        raw = gen(ir_data)
        if raw != "flowchart TD":
            sections.append(mermaid_fence(raw, title=title))

    # Projectors — one diagram per projection
    projections = ir_data.get("projections", {})
    for pfqn in sorted(projections):
        raw = generate_single_projector_diagram(ir_data, pfqn)
        if raw != "flowchart LR":
            name = pfqn.rsplit(".", 1)[-1] if "." in pfqn else pfqn
            sections.append(mermaid_fence(raw, title=f"Projector: {name}"))

    return "\n\n".join(sections) or mermaid_fence(
        "flowchart TD", title="Handler Wiring"
    )


def _generate_event_model(
    ir_data: dict[str, Any],
    output_format: str,
    annotations: dict[str, Any],
) -> str:
    """Generate the EventModeling slice timeline.

    In Markdown mode, each aggregate slice becomes a ``## Event Model:
    <Aggregate>`` section that leads with the slice's structural
    Given-When-Then, then shows any human notes keyed to the slice's
    elements, then the diagram.  In Mermaid mode, emits a single combined
    ``flowchart LR`` timeline of all slices, with no GWT or note prose (it
    cannot go inside a raw flowchart).

    In both modes, annotations whose FQN matches no drawn element are appended
    as an "Unmatched annotations" report. An empty *annotations* mapping adds
    nothing, so the render stays byte-identical to the pre-annotation output.
    """
    from protean.ir.generators.event_model import (  # noqa: PLC0415
        generate_event_model_sections,
        generate_event_model_timeline,
        render_unmatched_annotations,
        unmatched_annotations,
    )

    unmatched = render_unmatched_annotations(
        unmatched_annotations(ir_data, annotations)
    )

    if output_format == "mermaid":
        diagram = generate_event_model_timeline(ir_data)
        return f"{diagram}\n\n{unmatched}" if unmatched else diagram

    parts: list[str] = []

    # One pass over the IR: the section renderer builds the consumer indexes
    # once for the whole model instead of once per slice.
    for section in generate_event_model_sections(ir_data, annotations):
        cfqn = section.cluster_fqn
        name = cfqn.rsplit(".", 1)[-1] if "." in cfqn else cfqn
        # The GWT is always a non-empty block for a cluster that exists, and
        # a section is only produced for an existing cluster, so no empty-GWT
        # guard is needed here.
        block = [f"## Event Model: {name}", section.gwt]
        if section.notes:
            block.append(section.notes)
        block.append(mermaid_fence(section.diagram))
        parts.append("\n\n".join(block))

    body = "\n\n".join(parts) or mermaid_fence("flowchart LR", title="Event Model")
    return f"{body}\n\n{unmatched}" if unmatched else body


def _generate_catalog(ir_data: dict[str, Any]) -> str:
    """Generate event/command catalog (always Markdown)."""
    from protean.ir.generators.catalog import generate_catalog  # noqa: PLC0415

    return generate_catalog(ir_data)


def _generate_llms(ir_data: dict[str, Any] | None) -> str:
    """Generate the versioned ``llms.txt`` context pack.

    The framework layer is stamped with the installed Protean version. When an
    IR was loaded (``--domain``/``--ir``), the project overlay is appended;
    with no source, ``ir_data`` is ``None`` and only the framework layer is
    emitted.
    """
    from protean.ir.generators.llms import generate_llms_txt  # noqa: PLC0415

    return generate_llms_txt(ir_data, version=protean.__version__)


def _write_output(path: str, content: str) -> None:
    """Write content to a file, creating parent directories as needed."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
