"""Parse a textual event model into a slice-shaped IR fragment, and emit one back.

This module implements the textual event-model grammar of ADR-0041. The grammar
is a human authoring surface over the IR (ADR-0005): a person writes a small
one-slice model as text, and :func:`parse_model` reads it into a **slice-shaped IR
fragment** that reuses the IR's own field model. A field's shape is an IR field
entry, exactly as ``IRBuilder`` emits it.

Three pieces live here:

- :func:`parse_model` turns model text into a fragment: a dict with ``aggregate``,
  ``command``, ``event``, and an optional ``projection`` and ``projector``. Each
  element carries its authored name and a ``fields`` map of IR field entries. The
  parse is deterministic, infers nothing, and reports every violation with its
  1-based line number via :class:`ModelParseError`.
- :func:`emit_model` reads a full IR and a cluster FQN and produces grammar text
  for the covered subset (the participants' names, their authored fields, and the
  read-side wiring). On a cluster the grammar cannot express it raises
  :class:`ModelEmitError`; it never drops a covered participant in silence.
- Together the two are inverses over the covered subset, which the conformance
  test in ``tests/scaffold/test_model_parser.py`` checks as a build-time round trip
  (IR to text to IR), with no live sync.

The generator promotes a fragment to a full IR and then to code; this module
produces and reads the fragment only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from keyword import iskeyword
from typing import Any

from protean.scaffold.add_plan import _split_words

__all__ = ["ModelEmitError", "ModelParseError", "emit_model", "parse_model"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ModelParseError(Exception):
    """A model that does not parse. ``line`` is the 1-based line number the
    violation is reported at."""

    def __init__(self, message: str, line: int) -> None:
        self.line = line
        super().__init__(f"line {line}: {message}")


class ModelEmitError(Exception):
    """An IR cluster the grammar cannot express. The emitter raises rather than
    drop a covered participant or field in silence."""


# ---------------------------------------------------------------------------
# The grammar's type table (ADR-0041)
# ---------------------------------------------------------------------------

# Grammar type token -> the IR field ``kind`` and ``type`` it resolves to.
_TYPE_TABLE: dict[str, tuple[str, str]] = {
    "string": ("standard", "String"),
    "text": ("text", "Text"),
    "integer": ("standard", "Integer"),
    "float": ("standard", "Float"),
    "boolean": ("standard", "Boolean"),
    "date": ("standard", "Date"),
    "datetime": ("standard", "DateTime"),
    "identifier": ("identifier", "Identifier"),
}

# The inverse, for the emitter: (kind, type) -> grammar token. The key is typed
# loosely because the emitter looks it up with values read from an IR field entry
# (``dict[str, Any]``), which arrive as ``Any``.
_REVERSE_TYPE_TABLE: dict[tuple[Any, Any], str] = {
    value: key for key, value in _TYPE_TABLE.items()
}

_BLOCK_KEYWORDS = frozenset(
    {"aggregate", "command", "event", "projection", "projector"}
)

# Field names the generated slice already declares, per block. A model field of the
# same name would shadow generated code or be shadowed by it, so the parser refuses
# it instead of letting promotion lose the authored field.
#
# ``id`` on an aggregate is the framework's injected identity: an aggregate that
# declares its own ``id`` has it replaced by the injected ``Auto`` field, so the
# authored declaration disappears from the IR entirely. ``create`` is the generated
# aggregate factory and ``Meta`` the nested options class (ADR-0035, ADR-0041). The
# generator owns the rest of the enumeration.
_RESERVED_FIELD_NAMES: dict[str, frozenset[str]] = {
    "aggregate": frozenset({"Meta", "create", "id"}),
    "command": frozenset({"Meta"}),
    "event": frozenset({"Meta"}),
    "projection": frozenset({"Meta"}),
}

# Field-entry keys the grammar can express or safely ignore. ``max_length`` and
# ``identifier`` map to the two constraints; ``required`` is the grammar default;
# ``description`` is documentation metadata, not a validation constraint, so the
# grammar drops it. ``min_length`` needs a value check (see ``_emit_field``): a
# required field carries the implicit ``min_length: 1`` bound (ADR-0026), which the
# grammar's ``required`` re-derives, but a larger hand-set bound is an author
# constraint the grammar cannot carry. Any other key means the field carries
# something the grammar cannot express.
_EXPRESSIBLE_FIELD_KEYS = frozenset(
    {
        "kind",
        "type",
        "required",
        "identifier",
        "max_length",
        "min_length",
        "description",
    }
)

# The implicit non-empty bound a required field carries (ADR-0026). The grammar's
# ``required`` re-derives exactly this value, so the emitter drops a ``min_length``
# equal to it and raises on any other, including an explicit ``0``: a required field
# that accepts the empty string has no grammar form.
_IMPLICIT_MIN_LENGTH = 1


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^(\w+)\s+(\w+)\s*:\s*$")
_FIELD_RE = re.compile(r"^field\s+(\w+)\s*:\s*(\w+)\s*(?:\((.*)\))?\s*$")
_FOR_RE = re.compile(r"^for\s+(\w+)\s*$")
_CONSUMES_RE = re.compile(r"^consumes\s+(\w+)\s*$")
_MAX_LENGTH_RE = re.compile(r"^max_length\s*=\s*(\w+)$")


@dataclass
class _Block:
    """One parsed block, before cross-block validation."""

    keyword: str
    name: str  # normalized PascalCase
    raw_name: str
    header_line: int
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    field_lines: dict[str, int] = field(default_factory=dict)
    for_target: str | None = None
    for_line: int | None = None
    consumes_target: str | None = None
    consumes_line: int | None = None


def parse_model(text: str) -> dict[str, Any]:
    """Parse a one-slice event model into a slice-shaped IR fragment.

    Returns a dict with ``aggregate``, ``command``, ``event`` and, when the model
    carries a read side, ``projection`` and ``projector``. Each of the first four
    is ``{"name": <PascalCase>, "fields": {<name>: <IR field entry>}}``; the
    projector is ``{"name", "for", "consumes"}`` with the grammar terms kept as
    authored (the generator promotes them to references). Field names are
    read verbatim; block names are normalized to PascalCase using the same
    word-splitting as ``protean add``.

    Raises :class:`ModelParseError` with its 1-based line number on any grammar or
    referential violation.
    """
    if not isinstance(text, str):
        raise ModelParseError("model text must be a string", 1)
    lines = text.splitlines()
    blocks: list[_Block] = []
    current: _Block | None = None

    for lineno, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw_line[:1].isspace():
            current = _parse_header(raw_line, lineno)
            blocks.append(current)
        else:
            if current is None:
                raise ModelParseError(
                    "an indented line appears before any block header", lineno
                )
            _parse_body_line(current, stripped, lineno)

    return _finalize(blocks, len(lines))


def _parse_header(raw_line: str, lineno: int) -> _Block:
    match = _HEADER_RE.match(raw_line.rstrip())
    if match is None:
        raise ModelParseError(
            "malformed block header; expected '<keyword> <Name>:'", lineno
        )
    kw, raw_name = match.group(1), match.group(2)
    if kw not in _BLOCK_KEYWORDS:
        allowed = ", ".join(sorted(_BLOCK_KEYWORDS))
        raise ModelParseError(
            f"unknown block keyword {kw!r}; expected one of {allowed}", lineno
        )
    _validate_name(raw_name, lineno)
    normalized = _normalize_name(raw_name)
    slug = _slug(raw_name)
    # Both derived names matter, the way ``plan_add_slice`` checks them: the class
    # name and the module-level slug. ``class_`` normalizes to the valid class
    # ``Class`` but the slug ``class``, a keyword the generated module cannot use as
    # a variable, and it is the slug the projection key is derived from.
    if (
        not normalized.isidentifier()
        or iskeyword(normalized)
        or not slug.isidentifier()
        or iskeyword(slug)
    ):
        raise ModelParseError(
            f"block name {raw_name!r} does not normalize to a valid class name and "
            f"module variable (got {normalized!r} and {slug!r})",
            lineno,
        )
    return _Block(
        keyword=kw,
        name=normalized,
        raw_name=raw_name,
        header_line=lineno,
    )


def _parse_body_line(block: _Block, stripped: str, lineno: int) -> None:
    if block.keyword == "projector":
        _parse_projector_line(block, stripped, lineno)
    else:
        _parse_field_line(block, stripped, lineno)


def _parse_field_line(block: _Block, stripped: str, lineno: int) -> None:
    match = _FIELD_RE.match(stripped)
    if match is None:
        raise ModelParseError("expected a field line 'field <name>: <type>'", lineno)
    fname, ftype, constraints = match.group(1), match.group(2), match.group(3)

    if not fname.isidentifier():
        raise ModelParseError(f"field name {fname!r} is not a valid name", lineno)
    if iskeyword(fname):
        raise ModelParseError(f"field name {fname!r} is a Python keyword", lineno)
    if fname in _RESERVED_FIELD_NAMES.get(block.keyword, frozenset()):
        raise ModelParseError(
            f"field name {fname!r} is reserved: the generated {block.keyword} "
            f"already declares it",
            lineno,
        )
    if ftype not in _TYPE_TABLE:
        allowed = ", ".join(_TYPE_TABLE)
        raise ModelParseError(
            f"unknown field type {ftype!r}; expected one of {allowed}", lineno
        )
    if fname in block.fields:
        raise ModelParseError(f"duplicate field {fname!r} in this block", lineno)

    kind, type_name = _TYPE_TABLE[ftype]
    max_length, is_key = _parse_constraints(constraints, ftype, block.keyword, lineno)

    entry: dict[str, Any] = {"kind": kind, "type": type_name}
    if max_length is not None:
        entry["max_length"] = max_length
    if is_key:
        # The projection's identity key takes the framework identity default, so
        # it carries ``identifier: true`` and no ``required`` (ADR-0041).
        entry["identifier"] = True
    else:
        entry["required"] = True

    block.fields[fname] = entry
    block.field_lines[fname] = lineno


def _parse_constraints(
    constraints: str | None, ftype: str, keyword: str, lineno: int
) -> tuple[int | None, bool]:
    """Parse the parenthesized constraint list into ``(max_length, is_key)``."""
    max_length: int | None = None
    is_key = False
    if constraints is None or not constraints.strip():
        return max_length, is_key

    seen: set[str] = set()
    for part in constraints.split(","):
        token = part.strip()
        if token == "key":
            if "key" in seen:
                raise ModelParseError("duplicate 'key' constraint", lineno)
            seen.add("key")
            if ftype != "identifier" or keyword != "projection":
                raise ModelParseError(
                    "'key' is valid only on an identifier field of a projection",
                    lineno,
                )
            is_key = True
        elif token.startswith("max_length"):
            length_match = _MAX_LENGTH_RE.match(token)
            if length_match is None:
                raise ModelParseError(f"malformed constraint {token!r}", lineno)
            if "max_length" in seen:
                raise ModelParseError("duplicate 'max_length' constraint", lineno)
            seen.add("max_length")
            value = length_match.group(1)
            if not value.isdigit() or int(value) <= 0:
                raise ModelParseError("max_length must be a positive integer", lineno)
            if ftype not in ("string", "text"):
                raise ModelParseError(
                    "max_length is valid only on string and text fields", lineno
                )
            max_length = int(value)
        else:
            raise ModelParseError(f"unknown constraint {token!r}", lineno)

    return max_length, is_key


def _parse_projector_line(block: _Block, stripped: str, lineno: int) -> None:
    for_match = _FOR_RE.match(stripped)
    consumes_match = _CONSUMES_RE.match(stripped)
    if for_match is not None:
        if block.for_target is not None:
            raise ModelParseError("duplicate 'for' line in projector", lineno)
        block.for_target = for_match.group(1)
        block.for_line = lineno
    elif consumes_match is not None:
        if block.consumes_target is not None:
            raise ModelParseError("duplicate 'consumes' line in projector", lineno)
        block.consumes_target = consumes_match.group(1)
        block.consumes_line = lineno
    else:
        raise ModelParseError(
            "expected 'for <Projection>' or 'consumes <Event>'", lineno
        )


def _finalize(blocks: list[_Block], last_line: int) -> dict[str, Any]:
    end_line = last_line if last_line >= 1 else 1
    by_keyword: dict[str, list[_Block]] = {kw: [] for kw in _BLOCK_KEYWORDS}
    for block in blocks:
        by_keyword[block.keyword].append(block)

    for required in ("aggregate", "command", "event"):
        found = by_keyword[required]
        if not found:
            raise ModelParseError(f"model must define exactly one {required}", end_line)
        if len(found) > 1:
            raise ModelParseError(
                f"model defines more than one {required}", found[1].header_line
            )

    aggregate = by_keyword["aggregate"][0]
    command = by_keyword["command"][0]
    event = by_keyword["event"][0]

    projections = by_keyword["projection"]
    projectors = by_keyword["projector"]
    if len(projections) > 1:
        raise ModelParseError(
            "model defines more than one projection", projections[1].header_line
        )
    if len(projectors) > 1:
        raise ModelParseError(
            "model defines more than one projector", projectors[1].header_line
        )

    has_projection = len(projections) == 1
    has_projector = len(projectors) == 1
    if has_projection != has_projector:
        present = projections[0] if has_projection else projectors[0]
        raise ModelParseError(
            "the read side needs both a projection and a projector, or neither",
            present.header_line,
        )

    fragment: dict[str, Any] = {
        "aggregate": {"name": aggregate.name, "fields": aggregate.fields},
        "command": {"name": command.name, "fields": command.fields},
        "event": {"name": event.name, "fields": event.fields},
    }

    if has_projection:
        _validate_read_side(aggregate, event, projections[0], projectors[0])
        fragment["projection"] = {
            "name": projections[0].name,
            "fields": projections[0].fields,
        }
        fragment["projector"] = {
            "name": projectors[0].name,
            "for": projections[0].name,
            "consumes": event.name,
        }

    return fragment


def _validate_read_side(
    aggregate: _Block, event: _Block, projection: _Block, projector: _Block
) -> None:
    if projector.for_target is None:
        raise ModelParseError(
            "projector needs a 'for <Projection>' line", projector.header_line
        )
    if projector.consumes_target is None:
        raise ModelParseError(
            "projector needs a 'consumes <Event>' line", projector.header_line
        )
    if _normalize_name(projector.for_target) != projection.name:
        raise ModelParseError(
            f"'for {projector.for_target}' does not name the model's projection "
            f"{projection.raw_name!r}",
            projector.for_line or projector.header_line,
        )
    if _normalize_name(projector.consumes_target) != event.name:
        raise ModelParseError(
            f"'consumes {projector.consumes_target}' does not name the model's "
            f"event {event.raw_name!r}",
            projector.consumes_line or projector.header_line,
        )

    key_names = [
        name for name, entry in projection.fields.items() if entry.get("identifier")
    ]
    if not key_names:
        raise ModelParseError(
            "projection needs exactly one 'key' field", projection.header_line
        )
    if len(key_names) > 1:
        raise ModelParseError(
            "projection has more than one 'key' field",
            projection.field_lines[key_names[1]],
        )

    key_name = key_names[0]
    expected_key = f"{_slug(aggregate.raw_name)}_id"
    if key_name != expected_key:
        raise ModelParseError(
            f"projection key must be {expected_key!r} (the aggregate's surfaced "
            f"id), not {key_name!r}",
            projection.field_lines[key_name],
        )

    # The key is the surfaced aggregate id, and promotion populates the projection
    # from the event with no other source (ADR-0041), so the event has to carry it.
    # Its shape is not compared: the ADR has the event surface the reference as an
    # unconstrained ``string`` or ``identifier`` while the projection's key takes the
    # framework identity default.
    if key_name not in event.fields:
        raise ModelParseError(
            f"projection key {key_name!r} is not on the event {event.name!r}; the "
            "projector has no source to populate it from",
            projection.field_lines[key_name],
        )

    for fname, entry in projection.fields.items():
        if fname == key_name:
            continue
        if fname not in event.fields:
            raise ModelParseError(
                f"projection field {fname!r} is not on the event {event.name!r}",
                projection.field_lines[fname],
            )
        if event.fields[fname] != entry:
            raise ModelParseError(
                f"projection field {fname!r} does not match the shape of the same "
                f"field on the event {event.name!r}",
                projection.field_lines[fname],
            )


def _validate_name(raw_name: str, lineno: int) -> None:
    if not raw_name.isidentifier():
        raise ModelParseError(f"block name {raw_name!r} is not a valid name", lineno)
    if iskeyword(raw_name):
        raise ModelParseError(f"block name {raw_name!r} is a Python keyword", lineno)


def _normalize_name(raw_name: str) -> str:
    """The PascalCase class name ``protean add`` derives from a raw name."""
    words = _split_words(raw_name)
    return "".join(word[:1].upper() + word[1:] for word in words)


def _slug(raw_name: str) -> str:
    """The snake_case slug ``protean add`` derives from an aggregate name."""
    return "_".join(word.lower() for word in _split_words(raw_name))


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


def emit_model(ir: dict[str, Any], cluster_fqn: str) -> str:
    """Emit grammar text for the covered subset of one IR cluster.

    Reads a full IR and a cluster FQN, resolves the slice's read side through the
    top-level ``projections`` map, and produces the model text: the participants'
    names, their authored fields (name-sorted; field order is non-normative), and
    the ``for``/``consumes`` wiring. The framework-injected identity and a field's
    ``description`` are filtered.

    Raises :class:`ModelEmitError` on a cluster the grammar cannot express (a
    field outside the eight types and two constraints, an optional field, a
    hand-set ``min_length``, a non-primitive field kind, a field default or
    choices, more than one command or authored event, or a multi-aggregate /
    multi-handler projector). It never drops a covered participant or field in
    silence, and it never returns text :func:`parse_model` would reject: the
    emitted model is read back before it is returned, so a read side that breaks
    the grammar's contract (a projection keyed on something other than the
    aggregate's surfaced id, or a projected field the event does not source)
    raises here rather than producing unreadable text.
    """
    clusters = ir.get("clusters", {})
    if cluster_fqn not in clusters:
        raise ModelEmitError(f"cluster {cluster_fqn!r} is not in the IR")
    cluster = clusters[cluster_fqn]

    aggregate = cluster["aggregate"]

    commands = cluster.get("commands", {})
    if len(commands) != 1:
        raise ModelEmitError(
            f"cluster {cluster_fqn!r} has {len(commands)} commands; the grammar "
            "covers exactly one command"
        )
    command = next(iter(commands.values()))

    events = cluster.get("events", {})
    authored_events = {
        fqn: entry
        for fqn, entry in events.items()
        if not entry.get("is_fact_event") and not entry.get("auto_generated")
    }
    if len(authored_events) != 1:
        raise ModelEmitError(
            f"cluster {cluster_fqn!r} has {len(authored_events)} authored events; "
            "the grammar covers exactly one non-fact event"
        )
    event = next(iter(authored_events.values()))

    read_side = _resolve_read_side(ir, cluster_fqn, event.get("__type__"))

    blocks = [
        _emit_block("aggregate", aggregate["name"], aggregate.get("fields", {}), False),
        _emit_block("command", command["name"], command.get("fields", {}), False),
        _emit_block("event", event["name"], event.get("fields", {}), False),
    ]
    if read_side is not None:
        projection, projector = read_side
        blocks.append(
            _emit_block(
                "projection", projection["name"], projection.get("fields", {}), True
            )
        )
        blocks.append(
            _emit_projector(projector["name"], projection["name"], event["name"])
        )

    text = "\n\n".join(blocks) + "\n"

    # The emitter's contract is that its output reads back: emit and parse are
    # inverses over the covered subset. The parser holds rules the per-field and
    # per-participant checks above do not (the projection key is the aggregate's
    # surfaced id, every other projected field is sourced from the event with the
    # same shape), so read the text back rather than mirror those rules here, where
    # a second copy would drift from the parser. A cluster whose model does not
    # re-parse is outside the covered subset, and the parse error says why.
    try:
        parse_model(text)
    except ModelParseError as exc:
        raise ModelEmitError(
            f"cluster {cluster_fqn!r} emits a model the grammar cannot read back "
            f"({exc}); the cluster is outside the covered subset"
        ) from exc

    return text


def _resolve_read_side(
    ir: dict[str, Any], cluster_fqn: str, event_type: str | None
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Find the projection and projector for this cluster's slice, or ``None``.

    A projector belongs to the slice when it names this cluster among its
    aggregates or consumes this cluster's event. A matching projector that spans
    more than this one aggregate, or handles more than this one event, is
    ineligible and raises rather than emit a lossy subset.
    """
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for group in ir.get("projections", {}).values():
        for projector in group.get("projectors", {}).values():
            references = cluster_fqn in projector.get("aggregates", []) or (
                event_type is not None and event_type in projector.get("handlers", {})
            )
            if references:
                matches.append((group, projector))

    if not matches:
        return None
    if len(matches) > 1:
        raise ModelEmitError(
            f"cluster {cluster_fqn!r} is served by {len(matches)} projectors; the "
            "grammar covers a single read side"
        )

    group, projector = matches[0]
    if projector.get("aggregates", []) != [cluster_fqn]:
        raise ModelEmitError(
            f"projector {projector['name']!r} spans aggregates "
            f"{projector.get('aggregates', [])}; the grammar covers a "
            "single-aggregate projector"
        )
    handlers = projector.get("handlers", {})
    if list(handlers) != [event_type] or any(len(v) != 1 for v in handlers.values()):
        raise ModelEmitError(
            f"projector {projector['name']!r} handles {sorted(handlers)}; the "
            "grammar covers a projector that consumes exactly one event"
        )
    return group["projection"], projector


def _emit_block(
    keyword: str, name: str, fields: dict[str, Any], in_projection: bool
) -> str:
    header = f"{keyword} {name}:"
    lines = []
    for fname in sorted(fields):
        entry = fields[fname]
        if entry.get("auto_generated"):
            # The framework-injected identity is derived, not authored. Only the
            # marker identifies it: an authored ``Auto`` field (``sequence =
            # Auto(increment=True)``) also carries IR kind ``auto`` but no marker,
            # and it reaches ``_emit_field``, which refuses it as inexpressible
            # rather than drop it.
            continue
        lines.append(_emit_field(fname, entry, in_projection))
    if not lines:
        return header
    return header + "\n" + "\n".join(lines)


def _emit_field(name: str, entry: dict[str, Any], in_projection: bool) -> str:
    kind = entry.get("kind")
    type_name = entry.get("type")
    grammar_type = _REVERSE_TYPE_TABLE.get((kind, type_name))
    if grammar_type is None:
        raise ModelEmitError(
            f"field {name!r} has kind/type {kind}/{type_name}, which the grammar "
            "cannot express"
        )

    extra = set(entry) - _EXPRESSIBLE_FIELD_KEYS
    if extra:
        raise ModelEmitError(
            f"field {name!r} carries {sorted(extra)}, which the grammar cannot express"
        )

    # Every grammar field is required; the projection key is the one exception, and
    # it carries the framework identity default rather than ``required``. An
    # optional field has no grammar form, so the emitter raises rather than emit it
    # as required and silently change its meaning.
    if not entry.get("identifier") and not entry.get("required"):
        raise ModelEmitError(
            f"field {name!r} is optional; the grammar expresses only required fields"
        )

    # A hand-set ``min_length`` other than the implicit bound cannot round-trip: the
    # re-parsed field would carry the implicit bound again. That holds below the bound
    # as well as above it, since an explicit ``min_length=0`` on a required field
    # accepts the empty string and re-parsing would silently forbid it.
    min_length = entry.get("min_length")
    if min_length is not None and min_length != _IMPLICIT_MIN_LENGTH:
        raise ModelEmitError(
            f"field {name!r} sets min_length={min_length}, which the grammar "
            "cannot express"
        )

    constraints: list[str] = []
    max_length = entry.get("max_length")
    if max_length is not None:
        if grammar_type not in ("string", "text"):
            raise ModelEmitError(
                f"field {name!r} has max_length on a {grammar_type} field"
            )
        constraints.append(f"max_length={max_length}")
    if entry.get("identifier"):
        if not in_projection or grammar_type != "identifier":
            raise ModelEmitError(
                f"field {name!r} is flagged as a key outside a projection "
                "identifier field"
            )
        constraints.append("key")

    suffix = f"({', '.join(constraints)})" if constraints else ""
    return f"    field {name}: {grammar_type}{suffix}"


def _emit_projector(name: str, projection_name: str, event_name: str) -> str:
    return f"projector {name}:\n    for {projection_name}\n    consumes {event_name}"
