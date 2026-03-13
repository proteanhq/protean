"""Schema file writer — materializes generated schemas to disk.

Writes JSON Schema files produced by :mod:`protean.ir.generators.schema`
to a ``.protean/schemas/`` directory tree, grouped by aggregate cluster.

Usage::

    from protean.ir.generators.schema_writer import write_schemas, write_ir

    written = write_schemas(ir, output_dir)   # list of written paths
    write_ir(ir, output_dir)                  # writes ir.json

Directory layout::

    <output_dir>/
    ├── ir.json
    └── schemas/
        ├── <aggregate_short_name>/
        │   ├── aggregates/
        │   │   └── Order.v1.json
        │   ├── commands/
        │   │   └── PlaceOrder.v1.json
        │   ├── entities/
        │   │   └── LineItem.v1.json
        │   ├── events/
        │   │   └── OrderPlaced.v2.json
        │   └── value_objects/
        │       └── Money.v1.json
        └── projections/
            └── OrderDashboard.v1.json
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from protean.ir.generators.base import short_name
from protean.ir.generators.schema import generate_schemas


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Maps element_type values to the subdirectory name within a cluster.
_ELEMENT_TYPE_TO_DIR: dict[str, str] = {
    "AGGREGATE": "aggregates",
    "ENTITY": "entities",
    "VALUE_OBJECT": "value_objects",
    "COMMAND": "commands",
    "EVENT": "events",
}


def _element_version(schema: dict[str, Any]) -> int:
    """Return the version number for a schema filename.

    Events and commands carry ``x-protean-version``; all other element
    types default to ``1``.
    """
    return int(schema.get("x-protean-version", 1))


def _cluster_for_fqn(
    fqn: str, ir: dict[str, Any]
) -> str | None:
    """Return the aggregate short name that owns *fqn*, or ``None``.

    Walks the IR clusters and checks whether *fqn* appears as the
    aggregate FQN or within any of the cluster sections.
    """
    for cluster_fqn, cluster in ir.get("clusters", {}).items():
        # Check aggregate
        agg = cluster.get("aggregate", {})
        if agg.get("fqn") == fqn:
            return short_name(cluster_fqn)

        # Check entity, VO, command, event sections
        for section in ("entities", "value_objects", "commands", "events"):
            if fqn in cluster.get(section, {}):
                return short_name(cluster_fqn)

    return None


def _serialize_schema(schema: dict[str, Any]) -> str:
    """Serialize a schema dict to deterministic JSON with trailing newline."""
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_schemas(
    ir: dict[str, Any],
    output_dir: str | Path,
) -> list[Path]:
    """Generate all JSON Schemas from *ir* and write them to *output_dir*.

    The ``schemas/`` subdirectory is cleared before writing so that stale
    files from a previous run are removed.

    Args:
        ir: The full IR dict (from ``IRBuilder.build()``).
        output_dir: Root output directory (e.g. ``.protean``).

    Returns:
        A sorted list of absolute ``Path`` objects for every file written.
    """
    output = Path(output_dir)
    schemas_dir = output / "schemas"

    # Clean re-generation: remove existing schemas directory
    if schemas_dir.exists():
        shutil.rmtree(schemas_dir)

    schemas = generate_schemas(ir)
    written: list[Path] = []

    for fqn, schema in schemas.items():
        element_type = schema.get("x-protean-element-type", "").upper()
        name = schema.get("title", short_name(fqn))
        version = _element_version(schema)
        filename = f"{name}.v{version}.json"

        if element_type == "PROJECTION":
            # Projections go under top-level projections/ directory
            file_dir = schemas_dir / "projections"
        else:
            # Cluster-aware placement
            cluster_name = _cluster_for_fqn(fqn, ir)
            if cluster_name is None:
                # Fallback: use short name from FQN
                cluster_name = short_name(fqn)
            subdir = _ELEMENT_TYPE_TO_DIR.get(element_type, "other")
            file_dir = schemas_dir / cluster_name / subdir

        file_dir.mkdir(parents=True, exist_ok=True)
        file_path = file_dir / filename
        file_path.write_text(_serialize_schema(schema))
        written.append(file_path.resolve())

    return sorted(written)


def write_ir(
    ir: dict[str, Any],
    output_dir: str | Path,
) -> Path:
    """Write the full IR dict to ``ir.json`` inside *output_dir*.

    Args:
        ir: The full IR dict.
        output_dir: Root output directory (e.g. ``.protean``).

    Returns:
        The absolute ``Path`` of the written file.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    file_path = output / "ir.json"
    file_path.write_text(
        json.dumps(ir, indent=2, sort_keys=True) + "\n"
    )
    return file_path.resolve()
