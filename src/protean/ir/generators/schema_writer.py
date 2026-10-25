"""Schema file writer — materializes generated schemas to disk.

Writes JSON Schema files produced by :mod:`protean.ir.generators.schema`
to a ``.protean/schemas/`` directory tree, grouped by aggregate cluster.
Avro and Protobuf files go into the same tree. A ``.proto`` file imports the
files of the value objects and entities it references by their paths relative
to ``schemas/``, so compile the tree with ``protoc -I <output_dir>/schemas``.

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
from pathlib import Path, PurePosixPath
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


def _relative_schema_path(
    fqn: str,
    element: dict[str, Any],
    ir: dict[str, Any],
    ext: str,
) -> PurePosixPath:
    """Return where *element*'s schema file goes, relative to ``schemas/``.

    Projections go under ``projections/``; every other element goes under its
    owning cluster and element-type subdirectory. The writer places files with
    this path and the protobuf generator imports files by it, so both agree.
    """
    name = element.get("name", "") or short_name(fqn)
    version = int(element.get("__version__", 1))
    filename = f"{name}.v{version}.{ext}"

    if element.get("element_type", "").upper() == "PROJECTION":
        return PurePosixPath("projections", filename)

    cluster_name = _cluster_for_fqn(fqn, ir) or short_name(fqn)
    subdir = _ELEMENT_TYPE_TO_DIR.get(element.get("element_type", "").upper(), "other")
    return PurePosixPath(cluster_name, subdir, filename)


def _check_unique_paths(paths: dict[str, PurePosixPath]) -> None:
    """Raise if two elements would be written to the same schema file.

    Two elements with the same short name in one cluster (or two aggregates
    with the same short name in different modules) map to one path, and the
    second file would silently replace the first.
    """
    by_path: dict[PurePosixPath, list[str]] = {}
    for fqn, path in paths.items():
        by_path.setdefault(path, []).append(fqn)
    clashes = {path: fqns for path, fqns in by_path.items() if len(fqns) > 1}
    if clashes:
        details = "; ".join(
            f"{path.as_posix()}: {', '.join(fqns)}"
            for path, fqns in sorted(clashes.items())
        )
        raise ValueError(
            f"Several elements map to the same schema file, so one would "
            f"overwrite the other. Give them distinct names. {details}"
        )


_PROTO_REFERENCE_KINDS = frozenset(
    {"value_object", "value_object_list", "has_one", "has_many"}
)


def _proto_references(
    fqn: str,
    flat: dict[str, dict[str, Any]],
    paths: dict[str, PurePosixPath],
) -> set[str]:
    """Return the elements with a file that *fqn*'s ``.proto`` file refers to.

    A target without a file is defined inside the referencing file, so its own
    references count as the referencing file's.
    """
    found: set[str] = set()
    seen = {fqn}
    pending = [fqn]
    while pending:
        current = pending.pop()
        for field in flat.get(current, {}).get("fields", {}).values():
            if field.get("kind") not in _PROTO_REFERENCE_KINDS:
                continue
            target = field.get("target", "")
            if not target or target in seen:
                continue
            seen.add(target)
            if target in paths:
                found.add(target)
            else:
                pending.append(target)
    return found


def _reachable(start: str, graph: dict[str, set[str]]) -> set[str]:
    """Return every node reachable from *start* in one or more steps."""
    found: set[str] = set()
    pending = list(graph.get(start, ()))
    while pending:
        node = pending.pop()
        if node not in found:
            found.add(node)
            pending.extend(graph.get(node, ()))
    return found


def _proto_import_lookups(
    flat: dict[str, dict[str, Any]],
    paths: dict[str, PurePosixPath],
) -> dict[str, Callable[[str], str | None]]:
    """Build, per element, the lookup the protobuf generator imports through.

    ``protoc`` rejects files that import each other in a cycle, which entities
    referring to each other through ``HasOne``/``HasMany`` would produce. So an
    element never imports a file from its own cycle: the lookup returns
    ``None`` for those targets and the generator defines them as nested
    messages instead.
    """
    import_paths = {fqn: path.as_posix() for fqn, path in paths.items()}
    graph = {fqn: _proto_references(fqn, flat, paths) for fqn in paths}
    reachable = {fqn: _reachable(fqn, graph) for fqn in paths}

    def lookup_for(fqn: str) -> Callable[[str], str | None]:
        cycle = {other for other in reachable[fqn] if fqn in reachable[other]}
        if not cycle:
            return import_paths.get
        return lambda target: None if target in cycle else import_paths.get(target)

    return {fqn: lookup_for(fqn) for fqn in paths}


def _reset_schemas_dir(output_dir: str | Path) -> Path:
    """Return the ``schemas/`` directory under *output_dir*, cleared of any
    previous run's files so a re-generation never leaves stale schemas behind.
    """
    schemas_dir = Path(output_dir) / "schemas"
    if schemas_dir.exists():
        shutil.rmtree(schemas_dir)
    return schemas_dir


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

    schemas_dir = _reset_schemas_dir(output_dir)
    return sorted(_write_format(ir, schemas_dir, fmt))


def write_all_schemas(
    ir: dict[str, Any],
    output_dir: str | Path,
) -> list[Path]:
    """Write every supported format into one ``schemas/`` tree (the on-ramp).

    Clears ``schemas/`` once, then emits JSON, Avro, and Protobuf side by side.
    The three formats use distinct extensions (``.json`` / ``.avsc`` / ``.proto``)
    so they coexist in the same per-cluster directories — exactly the versioned
    tree an external schema registry would publish from.

    Unlike calling :func:`write_schemas` once per format (which clears the tree
    on every call and would clobber the previous format), this clears only once.

    Args:
        ir: The full IR dict (from ``IRBuilder.build()``).
        output_dir: Root output directory (e.g. ``.protean``).

    Returns:
        A sorted list of absolute ``Path`` objects for every file written.
    """
    schemas_dir = _reset_schemas_dir(output_dir)

    written: list[Path] = []
    for fmt in SUPPORTED_FORMATS:
        written.extend(_write_format(ir, schemas_dir, fmt))
    return sorted(written)


def _write_format(
    ir: dict[str, Any],
    schemas_dir: Path,
    fmt: str,
) -> list[Path]:
    """Write every data element's schema for a single *fmt* under *schemas_dir*.

    Does **not** clear ``schemas_dir`` — the caller owns clearing, so multiple
    formats can share one tree. Returns the (unsorted) paths written.
    """
    ext, generate_one, serialize = _FORMATS[fmt]

    flat = _build_flat_elements(ir)
    paths = {
        fqn: _relative_schema_path(fqn, element, ir, ext)
        for fqn, element in iter_data_elements(flat)
    }
    _check_unique_paths(paths)

    # Protobuf files import the files of the value objects and entities they
    # reference, so the generator needs every written file's path. Only
    # elements that get a file are in the lookup, so no import can dangle.
    lookups: dict[str, Callable[[str], str | None]] = {}
    if fmt == "protobuf":
        lookups = _proto_import_lookups(flat, paths)

    written: list[Path] = []
    for fqn, element in iter_data_elements(flat):
        extra: dict[str, Any] = {}
        if fqn in lookups:
            extra["import_path"] = lookups[fqn]
        file_path = schemas_dir.joinpath(*paths[fqn].parts)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            serialize(generate_one(element, all_elements=flat, **extra)),
            encoding="utf-8",
        )
        written.append(file_path.resolve())

    return written


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
