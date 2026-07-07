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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from protean.ir.generators.avro import generate_avro_schema
from protean.ir.generators.base import short_name
from protean.ir.generators.protobuf import generate_proto_schema
from protean.ir.generators.schema import (
    _build_flat_elements,
    generate_element_schema,
    iter_data_elements,
)


def _serialize_json(schema: Any) -> str:
    """Serialize a schema dict to deterministic JSON with a trailing newline."""
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


# Per-format: (file extension, single-element generator, serializer). JSON and
# Avro both serialize a dict as canonical JSON; Protobuf generates ``.proto``
# text directly, so its serializer is the identity.
_FORMATS: dict[str, tuple[str, Callable[..., Any], Callable[[Any], str]]] = {
    "json": ("json", generate_element_schema, _serialize_json),
    "avro": ("avsc", generate_avro_schema, _serialize_json),
    "protobuf": ("proto", generate_proto_schema, str),
}

# The schema formats accepted by ``write_schemas`` (and the CLI ``--format``).
SUPPORTED_FORMATS: tuple[str, ...] = tuple(_FORMATS)


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


def _cluster_for_fqn(fqn: str, ir: dict[str, Any]) -> str | None:
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_schemas(
    ir: dict[str, Any],
    output_dir: str | Path,
    fmt: str = "json",
) -> list[Path]:
    """Generate schemas from *ir* and write per-version files to *output_dir*.

    The ``schemas/`` subdirectory is cleared before writing so that stale files
    from a previous run are removed.

    Args:
        ir: The full IR dict (from ``IRBuilder.build()``).
        output_dir: Root output directory (e.g. ``.protean``).
        fmt: Output format — ``"json"`` (default), ``"avro"`` (``.avsc``), or
            ``"protobuf"`` (``.proto``).

    Returns:
        A sorted list of absolute ``Path`` objects for every file written.
    """
    if fmt not in _FORMATS:
        raise ValueError(
            f"Unknown schema format {fmt!r}; expected one of {sorted(_FORMATS)}."
        )
    ext, generate_one, serialize = _FORMATS[fmt]

    output = Path(output_dir)
    schemas_dir = output / "schemas"

    # Clean re-generation: remove existing schemas directory
    if schemas_dir.exists():
        shutil.rmtree(schemas_dir)

    flat = _build_flat_elements(ir)
    written: list[Path] = []

    for fqn, element in iter_data_elements(flat):
        element_type = element.get("element_type", "").upper()
        name = element.get("name", "") or short_name(fqn)
        version = int(element.get("__version__", 1))
        filename = f"{name}.v{version}.{ext}"

        if element_type == "PROJECTION":
            # Projections go under top-level projections/ directory
            file_dir = schemas_dir / "projections"
        else:
            # Cluster-aware placement
            cluster_name = _cluster_for_fqn(fqn, ir) or short_name(fqn)
            subdir = _ELEMENT_TYPE_TO_DIR.get(element_type, "other")
            file_dir = schemas_dir / cluster_name / subdir

        file_dir.mkdir(parents=True, exist_ok=True)
        file_path = file_dir / filename
        file_path.write_text(
            serialize(generate_one(element, all_elements=flat)), encoding="utf-8"
        )
        written.append(file_path.resolve())

    return sorted(written)


def write_ir(
    ir: dict[str, Any],
    output_dir: str | Path,
) -> Path:
    """Write the canonical IR baseline to ``ir.json`` inside *output_dir*.

    The written baseline omits the volatile ``generated_at`` timestamp (via
    :func:`protean.ir.constants.canonical_ir_json`) so a committed
    ``.protean/ir.json`` only churns when the domain contract changes. This is
    the same canonical form ``protean ir show --canonical`` and the ``--fix``
    staleness hook emit, keeping every baseline writer byte-identical.

    Args:
        ir: The full IR dict (from ``IRBuilder.build()``).
        output_dir: Root output directory (e.g. ``.protean``).

    Returns:
        The absolute ``Path`` of the written file.
    """
    from protean.ir.constants import canonical_ir_json  # noqa: PLC0415

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    file_path = output / "ir.json"
    file_path.write_text(
        canonical_ir_json(ir) + "\n",
        encoding="utf-8",
    )
    return file_path.resolve()
