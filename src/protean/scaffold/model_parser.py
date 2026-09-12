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

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
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


def _inherited_members(cls: type) -> frozenset[str]:
    """The public members a block's base class already declares.

    Read off the class rather than listed by hand, so the set cannot fall behind
    the base classes. Underscore-prefixed members are left out because no field
    name may start with an underscore at all (see ``_parse_field_line``).
    """
    return frozenset(name for name in dir(cls) if not name.startswith("_"))


# Field names a block already declares, so an authored field of the same name
# collides. Promotion writes model fields as class attributes, and a field that
# collides with an inherited member breaks in one of three ways, all of them quiet:
# the field value shadows the method on the instance (a ``raise_`` field makes
# ``self.raise_(event)`` a string, so the generated ``create`` cannot publish its
# event), or the inherited descriptor wins and the field value is lost (``state_``),
# or the field is dropped from the model altogether (``meta_``).
#
# The three added on top of the inherited members are the grammar's own. ``id`` on an
# aggregate: identity injection only stands down when the class declares a field
# marked ``identifier``, so a plain authored ``id`` does not stop it, and the injected
# ``Auto`` overwrites the authored declaration, which then does not reach the IR.
# ``create`` is the generated aggregate factory and ``Meta`` the nested options class
# (ADR-0035, ADR-0041).
_RESERVED_FIELD_NAMES: dict[str, frozenset[str]] = {
    "aggregate": _inherited_members(BaseAggregate) | {"Meta", "create", "id"},
    "command": _inherited_members(BaseCommand) | {"Meta"},
    "event": _inherited_members(BaseEvent) | {"Meta"},
    "projection": _inherited_members(BaseProjection) | {"Meta"},
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

# The element options the grammar covers, with the value promotion fills in. The
# grammar carries no option syntax, so a cluster whose options differ from these is
# outside the covered subset: dropping ``is_event_sourced: true`` or a projection's
# ``cache`` would emit a model that promotes back to a slice with different runtime
# behaviour. ADR-0041 lists these among the derived keys promotion fills.
#
# ``schema_name`` and ``stream_category`` are left out because promotion derives them
# from the element's name and the domain's, so they carry no authored choice. An
# option key absent from a table means the emitter refuses the cluster rather than
# guess, which is the safe direction when the framework gains an option.
_DEFAULT_OPTIONS: dict[str, dict[str, Any]] = {
    "aggregate": {
        "auto_add_id_field": True,
        "fact_events": False,
        "is_event_sourced": False,
        "limit": 100,
        "provider": "default",
    },
    "projection": {
        "cache": None,
        "externally_populated": False,
        "limit": 100,
        "order_by": [],
        "provider": "default",
    },
}

# Option keys promotion derives from the element's own name, so they hold no choice
# the grammar could lose.
_DERIVED_OPTION_KEYS = frozenset({"schema_name", "stream_category"})

# A projector's subscription settings as promotion fills them. A projector carries no
# ``options`` (ADR-0041), so its subscription is what stands in for them here.
_DEFAULT_SUBSCRIPTION: dict[str, Any] = {"config": {}, "profile": None, "type": None}


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
    if not normalized.isidentifier() or iskeyword(normalized):
        raise ModelParseError(
            f"block name {raw_name!r} does not normalize to a valid class name "
            f"(got {normalized!r})",
            lineno,
        )
    # Only the aggregate's slug is load-bearing in the grammar: it is what the
    # surfaced ``<slug>_id`` is derived from. ``class_`` gives the valid class
    # ``Class`` but the slug ``class``, a keyword, the same pair ``plan_add_slice``
    # rejects. Slugs for the other blocks are the generator's to derive and check.
    if kw == "aggregate":
        slug = _slug(raw_name)
        if not slug.isidentifier() or iskeyword(slug):
            raise ModelParseError(
                f"aggregate name {raw_name!r} derives the module variable "
                f"{slug!r}, which is not a usable Python name",
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
    if fname.startswith("_"):
        # Promotion writes the field as a class attribute, and the namespace scan
        # skips a leading underscore, so the field would not reach the model at all.
        raise ModelParseError(
            f"field name {fname!r} may not start with an underscore", lineno
        )
    if fname in _RESERVED_FIELD_NAMES.get(block.keyword, frozenset()):
        raise ModelParseError(
            f"field name {fname!r} is reserved: a {block.keyword} already declares "
            f"it, so the field would collide with it",
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
    if constraints is None:
        return max_length, is_key
    if not constraints.strip():
        raise ModelParseError(
            "empty constraint list; drop the parentheses or name a constraint", lineno
        )

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
            # ``isdecimal`` and not ``isdigit``: a Unicode numeric like the
            # superscript two satisfies ``isdigit`` but ``int()`` then raises a
            # ValueError, and every violation here reports as a ModelParseError.
            if not value.isdecimal():
                raise ModelParseError("max_length must be a positive integer", lineno)
            try:
                length = int(value)
            except ValueError as exc:
                # A decimal token past CPython's int-from-string digit limit. Still a
                # grammar violation, so it reports as one.
                raise ModelParseError(
                    f"max_length has {len(value)} digits, which is too long to read",
                    lineno,
                ) from exc
            if length <= 0:
                raise ModelParseError("max_length must be a positive integer", lineno)
            if ftype not in ("string", "text"):
                raise ModelParseError(
                    "max_length is valid only on string and text fields", lineno
                )
            max_length = length
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

    surfaced_id = _validate_surfaced_id(aggregate, event)

    fragment: dict[str, Any] = {
        "aggregate": {"name": aggregate.name, "fields": aggregate.fields},
        "command": {"name": command.name, "fields": command.fields},
        "event": {"name": event.name, "fields": event.fields},
    }

    if has_projection:
        _validate_read_side(
            aggregate, event, projections[0], projectors[0], surfaced_id
        )
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


# The IR field shapes the aggregate's surfaced id reference may take on the event.
# ADR-0041 v1 has the author surface it as a ``string`` or an ``identifier``; an
# integer or a date cannot hold the aggregate's id.
_SURFACED_ID_SHAPES = (("standard", "String"), ("identifier", "Identifier"))


def _validate_surfaced_id(aggregate: _Block, event: _Block) -> str:
    """Check that the event carries the aggregate's surfaced id, and return its name.

    The author writes the ``<slug>_id`` field on the event, and promotion wires the
    generated ``create`` to set it from the aggregate's id (ADR-0041). The read side
    reads it from there: an authored projection keys on it, and an omitted one is
    derived from the event with that field as the key. So it is required either way.

    Its length is not checked. Whether a bound is wide enough to hold an id depends
    on the domain's ``identity_type`` and ``identity_strategy``, which live in the
    composition root the grammar does not carry, so that check belongs to promotion.
    """
    expected = f"{_slug(aggregate.raw_name)}_id"
    if expected not in event.fields:
        raise ModelParseError(
            f"event {event.name!r} must carry {expected!r}, the aggregate's surfaced "
            "id, for the read side to key on",
            event.header_line,
        )
    entry = event.fields[expected]
    if (entry.get("kind"), entry.get("type")) not in _SURFACED_ID_SHAPES:
        raise ModelParseError(
            f"the surfaced id {expected!r} must be a string or an identifier, "
            f"not a {entry.get('type')}",
            event.field_lines[expected],
        )
    return expected


def _validate_read_side(
    aggregate: _Block,
    event: _Block,
    projection: _Block,
    projector: _Block,
    surfaced_id: str,
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
    if key_name != surfaced_id:
        raise ModelParseError(
            f"projection key must be {surfaced_id!r} (the aggregate's surfaced "
            f"id), not {key_name!r}",
            projection.field_lines[key_name],
        )

    # The key's shape is not compared against the event's. ``_validate_surfaced_id``
    # has already checked the event carries it as a string or an identifier, while
    # the projection's key takes the framework identity default.
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

    _check_options(cluster_fqn, "aggregate", aggregate)

    read_side = _resolve_read_side(ir, cluster_fqn, event.get("__type__"))

    blocks = [
        _emit_block("aggregate", aggregate["name"], aggregate.get("fields", {}), False),
        _emit_block("command", command["name"], command.get("fields", {}), False),
        _emit_block("event", event["name"], event.get("fields", {}), False),
    ]
    if read_side is not None:
        projection, projector = read_side
        _check_options(cluster_fqn, "projection", projection)
        subscription = projector.get("subscription")
        if subscription is not None and subscription != _DEFAULT_SUBSCRIPTION:
            raise ModelEmitError(
                f"projector {projector['name']!r} sets a non-default subscription "
                f"({subscription}), which the grammar cannot express"
            )
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
    # per-participant checks above do not (the event carries the aggregate's surfaced
    # id, the projection keys on it, every other projected field is sourced from the
    # event with the same shape), so read the text back rather than mirror those
    # rules here, where a second copy would drift from the parser. A cluster whose
    # model does not re-parse is outside the covered subset, and the parse error
    # says why.
    try:
        fragment = parse_model(text)
    except ModelParseError as exc:
        raise ModelEmitError(
            f"cluster {cluster_fqn!r} emits a model the grammar cannot read back "
            f"({exc}); the cluster is outside the covered subset"
        ) from exc

    # Parsing back is not enough on its own: the parser normalizes a block name to
    # PascalCase, so an IR name that is not already canonical (an aggregate class
    # written ``order_item``) reads back as a different participant. Text that
    # renames the cluster is not a faithful emission, so refuse it.
    for keyword, emitted in (
        ("aggregate", aggregate["name"]),
        ("command", command["name"]),
        ("event", event["name"]),
    ):
        _check_name_is_canonical(cluster_fqn, keyword, emitted, fragment)
    if read_side is not None:
        _check_name_is_canonical(
            cluster_fqn, "projection", read_side[0]["name"], fragment
        )
        _check_name_is_canonical(
            cluster_fqn, "projector", read_side[1]["name"], fragment
        )

    return text


def _check_name_is_canonical(
    cluster_fqn: str, keyword: str, emitted: str, fragment: dict[str, Any]
) -> None:
    """Refuse an IR name the parser would read back as a different name."""
    read_back = fragment[keyword]["name"]
    if read_back != emitted:
        raise ModelEmitError(
            f"cluster {cluster_fqn!r} has the {keyword} {emitted!r}, which the "
            f"grammar reads back as {read_back!r}; the grammar covers names that "
            "are already in its normal form"
        )


def _resolve_read_side(
    ir: dict[str, Any], cluster_fqn: str, event_type: str | None
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Find the projection and projector for this cluster's slice, or ``None``.

    A projector belongs to the slice when it consumes this cluster's event, which
    is how the event-model renderer attaches one (``_drawn_consumers`` in
    ``protean.ir.generators.event_model``): the handler map decides, not the
    aggregate list. A projector that names this aggregate but handles some other
    cluster's event is not part of this slice and is passed over. One that does
    consume this event but spans more than this aggregate, or handles more than
    this event, is ineligible and raises rather than emit a lossy subset.
    """
    # An event with no ``__type__`` matches nothing, since a handler map is keyed by
    # event type, so such a cluster comes out write-side-only.
    matches = [
        (group, projector)
        for group in ir.get("projections", {}).values()
        for projector in group.get("projectors", {}).values()
        if event_type in projector.get("handlers", {})
    ]

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


def _check_options(cluster_fqn: str, keyword: str, element: dict[str, Any]) -> None:
    """Refuse an element whose options the grammar cannot carry.

    The grammar has no option syntax, so it can only express an element promotion
    would give the framework defaults. Emitting one with a non-default option would
    return text that promotes back to different behaviour, with nothing in the model
    to show for it.
    """
    defaults = _DEFAULT_OPTIONS[keyword]
    options = element.get("options") or {}
    for key, value in sorted(options.items()):
        if key in _DERIVED_OPTION_KEYS:
            continue
        if key not in defaults:
            raise ModelEmitError(
                f"cluster {cluster_fqn!r} sets the {keyword} option {key!r}, which "
                "the grammar does not carry"
            )
        if value != defaults[key]:
            raise ModelEmitError(
                f"cluster {cluster_fqn!r} sets the {keyword} option {key}={value!r} "
                f"rather than {defaults[key]!r}, which the grammar cannot express"
            )


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
