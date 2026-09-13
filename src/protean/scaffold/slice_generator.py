"""Generate a vertical slice's :class:`ChangePlan` from a slice-shaped IR fragment.

ADR-0041 defines the contract this module implements. A textual event model parses
to a **slice-shaped IR fragment** that reuses the IR's own field model, and this
**generator** promotes that fragment to the full vertical slice
``protean add`` writes today: the aggregate (split by the generation-gap seam of
ADR-0035), its create command, its created event, the command handler that drives
it, and a projector plus read-model projection that consume the event so
``protean verify`` on the applied slice is green.

The fragment is the contract between the parser and the generator. It carries only
what the text model carries: the element names, their fields (each an IR field entry
of ``kind``/``type``, the ``required`` flag, and the two constraints ``max_length``
and ``identifier``), and the read-side wiring (``for`` names the projection,
``consumes`` names the event). The read side is optional; when it is omitted, the
generator derives a default projection that mirrors the event (the surfaced
``<slug>_id`` becoming the ``Identifier`` key) and a projector that consumes the
event. That derivation makes the read side match the event. The applied slice
passes ``protean verify`` when the write side is also aligned: the command carries
the aggregate's fields and the event's non-id fields are aggregate fields. Field-set
alignment across the aggregate, command, and event is the parser's to check
(ADR-0041); this generator does not validate it.

``protean add`` routes through the generator too: it expresses its default
name-only slice as a default fragment and calls :func:`generate_slice_plan`, so the
two authoring surfaces share one promotion step and one set of renderers.

Field order is not part of the contract (ADR-0041): the generator emits fields in a
deterministic name order, with the surfaced ``<slug>_id`` first where it appears.
"""

from __future__ import annotations

import keyword
from collections.abc import Mapping
from dataclasses import dataclass

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.scaffold.change_plan import (
    OWNERSHIP_GENERATED,
    OWNERSHIP_HAND_OWNED,
    ChangePlan,
    CreateFileOperation,
)

__all__ = [
    "IRField",
    "SliceElement",
    "SliceFragment",
    "SliceGeneratorError",
    "SliceProjector",
    "generate_slice_plan",
]

# The eight grammar primitive types, keyed by their IR field ``type`` (ADR-0041's
# vocabulary table), mapped to the plain Python annotation the type resolves to. The
# generated ``create`` factory uses this base annotation for its parameters, and a
# field with no rendered constraint (a plain ``String`` reference such as the event's
# ``<slug>_id``) declares itself with it directly.
_BASE_ANNOTATION: dict[str, str] = {
    "String": "str",
    "Text": "str",
    "Integer": "int",
    "Float": "float",
    "Boolean": "bool",
    "Date": "date",
    "DateTime": "datetime",
    "Identifier": "str",
}


# Each element renders as a subclass of one of these, so a field that takes the name
# of a public member of its base shadows that member. Pydantic warns about exactly
# this ("shadows an attribute in parent"), and the shadowed member is often one the
# framework needs: an aggregate field named ``raise_`` leaves the generated create
# factory unable to raise its event.
_BASE_CLASSES: dict[str, type] = {
    "aggregate": BaseAggregate,
    "command": BaseCommand,
    "event": BaseEvent,
    "projection": BaseProjection,
}

# The nested options class the renderers emit, so no field may take its name.
_OPTIONS_CLASS = "Meta"

# The symbols the generator writes into the aggregate's generated base: the create
# factory and the classmethod's first parameter. A field named ``create`` replaces
# the factory; one named ``cls`` gives the factory two parameters of that name.
_AGGREGATE_GENERATED_NAMES = frozenset({"create", "cls"})

# The names the renderers import into the generated modules. A class named for one of
# these rebinds the import in the module that carries both: an event named
# ``BaseAggregate`` makes the generated base inherit the event, and one named for the
# project's domain variable makes the projector register against the event.
_IMPORTED_SYMBOLS = frozenset(
    {
        "Annotated",
        "BaseAggregate",
        "Field",
        "Identifier",
        "Self",
        "Text",
        "date",
        "datetime",
        "handle",
        "on",
    }
)

# The two locals the renderers bind and then read again, so a name that takes one of
# them changes what the later line refers to. The command handler holds its repository
# in ``repo`` and adds the aggregate through it, and the projector builds the
# projection into ``summary`` before asking the domain for that projection's
# repository. Every other generated local is written once and never read back, so a
# name may take it safely.
_HANDLER_LOCAL = "repo"
_PROJECTOR_LOCAL = "summary"


class SliceGeneratorError(Exception):
    """A fragment the generator cannot promote to a slice: an unsupported field
    type, an event missing the surfaced identity field, or a read side that is only
    half present or wired to the wrong participant. The message names the problem so
    a caller (the CLI, the MCP tool, or the model parser) can surface it to a human."""


@dataclass(frozen=True)
class IRField:
    """One field's IR entry, from ADR-0041's field vocabulary.

    ``kind`` is ``"standard"``, ``"text"``, or ``"identifier"``; ``type`` is one of
    the eight primitive type names (``"String"``, ``"Integer"``, ...). ``max_length``
    is set only on ``String``/``Text``; ``identifier`` marks the projection's identity
    key. ``required`` records the IR entry's required flag: the grammar makes every
    authored field required, so callers set ``required=True`` on them, and the
    projection's identity key is the one field that is not (it takes the framework
    identity default), which is why the default is ``False``.

    The create-only slice renders every authored field as required, so ``_declare``
    does not read ``required`` today. The flag is kept so the fragment stays a
    faithful IR field entry for the model parser, which produces it.
    """

    kind: str
    type: str
    required: bool = False
    max_length: int | None = None
    identifier: bool = False


@dataclass(frozen=True)
class SliceElement:
    """A named element (aggregate, command, event, or projection) and its fields."""

    name: str
    fields: Mapping[str, IRField]


@dataclass(frozen=True)
class SliceProjector:
    """The read-side wiring: the projector's name and the grammar's ``for`` and
    ``consumes`` terms, which name the projection and the event the projector reads."""

    name: str
    for_: str
    consumes: str


@dataclass(frozen=True)
class SliceFragment:
    """One slice: exactly one aggregate, command, and event, and an optional read
    side (a projection and projector, together or not at all)."""

    aggregate: SliceElement
    command: SliceElement
    event: SliceElement
    projection: SliceElement | None = None
    projector: SliceProjector | None = None


def generate_slice_plan(
    fragment: SliceFragment, package: str, domain_var: str
) -> ChangePlan:
    """Promote *fragment* to a create-only :class:`ChangePlan` for one slice.

    *package* is the project's import-root package and *domain_var* the variable the
    composition root binds the ``Domain`` to, the pair
    :func:`~protean.scaffold.add_plan._resolve_project` reads from ``domain.py``. The
    aggregate's snake_case ``<slug>`` (the slice directory and the id-field prefix) is
    derived from the aggregate name the way ``protean add`` derives it.

    Returns a plan of :class:`CreateFileOperation`\\ s at the canonical ADR-0030 paths
    under ``src/<package>/<slug>/``. Touches no files.

    Raises :class:`SliceGeneratorError` when a name the generated code carries would
    not work: an element name, field name, or derived slug that is not a usable Python
    name; two of the slice's classes sharing a name, counting the read side the
    generator derives; a name that collides with a symbol the generated modules import
    or with a local they read back; or a field name reserved by the framework or by
    the code the generator writes. It also raises when a field has an unsupported
    type, when the event does not declare the surfaced ``<slug>_id`` identity field in
    a shape that can hold the aggregate's id, when an explicit projection is not keyed
    on that field or carries a field the event does not, and when the read side is
    only half present or wired to a participant the slice does not define.
    """
    name = fragment.aggregate.name
    slug = _slug_for(name)
    _validate(fragment, slug, domain_var)

    projection = fragment.projection or _derive_projection(fragment.event, name, slug)
    projector = fragment.projector or _derive_projector(
        name, projection.name, fragment.event.name
    )

    files: tuple[tuple[str, str, str], ...] = (
        ("__init__.py", _render_init(name), OWNERSHIP_HAND_OWNED),
        (
            "aggregate_base.py",
            _render_aggregate_base(name, slug, fragment.aggregate, fragment.event),
            OWNERSHIP_GENERATED,
        ),
        (
            "aggregate.py",
            _render_aggregate(name, package, domain_var),
            OWNERSHIP_HAND_OWNED,
        ),
        (
            "commands.py",
            _render_commands(name, slug, package, domain_var, fragment.command),
            OWNERSHIP_HAND_OWNED,
        ),
        (
            "events.py",
            _render_events(name, slug, package, domain_var, fragment.event),
            OWNERSHIP_HAND_OWNED,
        ),
        (
            "command_handlers.py",
            _render_command_handlers(
                name, slug, package, domain_var, fragment.aggregate, fragment.command
            ),
            OWNERSHIP_HAND_OWNED,
        ),
        (
            "projection.py",
            _render_projection(name, slug, package, domain_var, projection),
            OWNERSHIP_HAND_OWNED,
        ),
        (
            "projectors.py",
            _render_projectors(
                name, slug, package, domain_var, projection, projector, fragment.event
            ),
            OWNERSHIP_HAND_OWNED,
        ),
    )

    base = f"src/{package}/{slug}"
    operations = tuple(
        CreateFileOperation(
            path=f"{base}/{filename}", content=content, ownership=ownership
        )
        for filename, content, ownership in files
    )

    return ChangePlan(
        operations=operations,
        description=(
            f"Add the {name} aggregate slice "
            f"(aggregate, command, event, command handler, projector, projection)"
        ),
    )


def _split_words(name: str) -> list[str]:
    """Split an identifier into the words its generated names are built from.

    Underscores separate words, and so does a case change, so ``order_item``,
    ``orderItem`` and ``OrderItem`` all split into two words and render the same
    class ``OrderItem`` and the same slug ``order_item``. A run of capitals stays
    one word except for the last capital, which starts the next one (``XMLHttp``
    gives ``["XML", "Http"]``). The rest of each word keeps its original casing,
    which is what keeps ``HTTPServer`` from becoming ``HttpServer``.
    """
    words: list[str] = []
    current = ""
    for index, char in enumerate(name):
        if char == "_":
            if current:
                words.append(current)
                current = ""
            continue
        if char.isupper() and current:
            follows_lower = not current[-1].isupper()
            starts_word = index + 1 < len(name) and name[index + 1].islower()
            if follows_lower or starts_word:
                words.append(current)
                current = ""
        current += char
    if current:
        words.append(current)
    return words


def _slug_for(name: str) -> str:
    """The snake_case slug for an aggregate name, e.g. ``OrderItem`` -> ``order_item``."""
    return "_".join(word.lower() for word in _split_words(name))


def _reserved_field_names(role: str) -> frozenset[str]:
    """The names a field on *role* may not take: the nested options class, every
    public member of the element's framework base class, and, on the aggregate, the
    symbols the generated create factory occupies."""
    reserved = {_OPTIONS_CLASS} | {
        member for member in dir(_BASE_CLASSES[role]) if not member.startswith("_")
    }
    if role == "aggregate":
        reserved |= _AGGREGATE_GENERATED_NAMES
    return frozenset(reserved)


def _check_python_name(value: str, what: str) -> None:
    """Reject a name the generator cannot write into the generated code verbatim."""
    if not value.isidentifier() or keyword.iskeyword(value):
        raise SliceGeneratorError(
            f"{what} {value!r} is not a usable Python name. The generator writes it "
            "into the generated code as written, so it must be a valid Python "
            "identifier that is not a keyword."
        )


def _carries_aggregate_id(ir_field: IRField) -> bool:
    """Whether a field can hold the aggregate's id. The generated create factory
    assigns the aggregate's id, a UUID string under the identity default ADR-0041's
    v1 targets, so the field has to be an ``Identifier`` or an unconstrained
    ``String``. A bounded ``String`` rejects the 36-character value and any other
    type rejects a string outright."""
    if ir_field.kind == "identifier":
        return ir_field.type == "Identifier"
    return ir_field.type == "String" and ir_field.max_length is None


def _validate(fragment: SliceFragment, slug: str, domain_var: str) -> None:
    """Reject a fragment that would render code that does not compile or verify."""
    id_name = f"{slug}_id"

    _check_python_name(
        slug,
        f"The slug derived from the aggregate name {fragment.aggregate.name!r}:",
    )
    if slug in {_HANDLER_LOCAL, domain_var}:
        raise SliceGeneratorError(
            f"The aggregate name {fragment.aggregate.name!r} derives the slug "
            f"{slug!r}, which the generated command handler already binds: it holds "
            f"the repository in {_HANDLER_LOCAL!r} and reaches the domain through "
            f"{domain_var!r}. The handler would then call the wrong object. Choose "
            "another aggregate name."
        )

    elements: list[tuple[str, SliceElement]] = [
        ("aggregate", fragment.aggregate),
        ("command", fragment.command),
        ("event", fragment.event),
    ]
    if fragment.projection is not None:
        elements.append(("projection", fragment.projection))

    _validate_names(fragment, elements, domain_var)

    for role, element in elements:
        reserved = _reserved_field_names(role)
        for field_name, ir_field in element.fields.items():
            _check_python_name(field_name, f"Field name on {element.name!r}:")
            if field_name.startswith("_"):
                raise SliceGeneratorError(
                    f"Field {field_name!r} on {element.name!r} starts with an "
                    "underscore. The framework and pydantic keep that namespace for "
                    "their own attributes, so a field cannot use it."
                )
            if field_name in reserved:
                raise SliceGeneratorError(
                    f"Field {field_name!r} on {element.name!r} is a reserved name: "
                    f"the generated {role} already uses it, so the field would "
                    "shadow it and the slice would not work. Rename the field."
                )
            if ir_field.type not in _BASE_ANNOTATION:
                supported = ", ".join(sorted(_BASE_ANNOTATION))
                raise SliceGeneratorError(
                    f"Field {field_name!r} on {element.name!r} has unsupported type "
                    f"{ir_field.type!r}. Supported types: {supported}."
                )

    event_id_field = fragment.event.fields.get(id_name)
    if event_id_field is None:
        raise SliceGeneratorError(
            f"The event {fragment.event.name!r} must declare the {id_name!r} field "
            "that carries the aggregate's identity, so the generated create factory "
            f"can set it from the aggregate's id. Add a {id_name!r} field to the event."
        )
    if not _carries_aggregate_id(event_id_field):
        raise SliceGeneratorError(
            f"The event {fragment.event.name!r} declares {id_name!r} as a field that "
            "cannot hold the aggregate's id, which the generated create factory "
            f"assigns to it. Declare {id_name!r} as an Identifier or as a String "
            "with no max_length."
        )

    has_projection = fragment.projection is not None
    has_projector = fragment.projector is not None
    if has_projection != has_projector:
        raise SliceGeneratorError(
            "A slice's read side is a projection and a projector together, or "
            "neither. Provide both or omit both; when both are omitted the generator "
            "derives the default read side from the event."
        )

    if fragment.projector is not None and fragment.projection is not None:
        _validate_projection_key(fragment.projection, id_name)
        _validate_projection_fields(fragment.projection, fragment.event, id_name)
        if fragment.projector.for_ != fragment.projection.name:
            raise SliceGeneratorError(
                f"The projector's 'for' names {fragment.projector.for_!r}, but the "
                f"slice's projection is {fragment.projection.name!r}. They must match."
            )
        if fragment.projector.consumes != fragment.event.name:
            raise SliceGeneratorError(
                f"The projector 'consumes' {fragment.projector.consumes!r}, but the "
                f"slice's event is {fragment.event.name!r}. They must match."
            )


def _validate_names(
    fragment: SliceFragment,
    elements: list[tuple[str, SliceElement]],
    domain_var: str,
) -> None:
    """Check the class names the slice defines.

    Each has to be a usable Python name, has to stay clear of the names the generated
    modules import, and has to be distinct from the others: they all land in one
    package, and the command handler and projector import several of them into one
    module. The read side counts even when the fragment omits it, because the
    generator then derives a projection and projector that carry names of their own.
    """
    for role, element in elements:
        _check_python_name(element.name, f"The {role} name")
    if fragment.projector is not None:
        _check_python_name(fragment.projector.name, "The projector name")

    defined = [(role, element.name) for role, element in elements]
    defined.append(("aggregate base", f"{fragment.aggregate.name}Base"))
    if fragment.projector is not None:
        defined.append(("projector", fragment.projector.name))
    if fragment.projection is None and fragment.projector is None:
        defined.append(
            ("derived projection", _derived_projection_name(fragment.aggregate.name))
        )
        defined.append(
            ("derived projector", _derived_projector_name(fragment.aggregate.name))
        )

    for role, class_name in defined:
        if class_name in _IMPORTED_SYMBOLS or class_name == domain_var:
            raise SliceGeneratorError(
                f"The slice's {role} is named {class_name!r}, which the generated "
                "code imports under that name. The class would replace the import in "
                "the module that carries both, so the slice would inherit from, "
                "register against, or be keyed on the wrong object. Rename it."
            )

    projection_name = (
        fragment.projection.name
        if fragment.projection is not None
        else _derived_projection_name(fragment.aggregate.name)
    )
    if projection_name == _PROJECTOR_LOCAL:
        raise SliceGeneratorError(
            f"The slice's projection is named {projection_name!r}, which the "
            "generated projector binds to the projection it just built. The next "
            "line asks the domain for that projection's repository and would pass "
            "the instance instead of the class. Rename the projection."
        )

    seen: dict[str, str] = {}
    for role, class_name in defined:
        if class_name in seen:
            raise SliceGeneratorError(
                f"The slice defines {class_name!r} twice, as its {seen[class_name]} "
                f"and as its {role}. Each of the slice's classes needs its own name."
            )
        seen[class_name] = role


def _validate_projection_fields(
    projection: SliceElement, event: SliceElement, id_name: str
) -> None:
    """A projection's non-key fields are drawn from the event by name and carry the
    event field's type and constraints (ADR-0041). The generated projector copies each
    one straight off the event, so a field the event does not carry, or one whose
    shape differs, fails when the projector handles the event."""
    for field_name, ir_field in projection.fields.items():
        if field_name == id_name:
            continue
        event_field = event.fields.get(field_name)
        if event_field is None:
            raise SliceGeneratorError(
                f"The projection {projection.name!r} declares {field_name!r}, which "
                f"the event {event.name!r} does not carry. The generated projector "
                f"reads every projection field off the event, so handling "
                f"{event.name!r} would fail. Drop the field or add it to the event."
            )
        if ir_field != event_field:
            raise SliceGeneratorError(
                f"The projection {projection.name!r} declares {field_name!r} in a "
                f"different shape from the event {event.name!r}, which the projector "
                "copies it from. Declare it the way the event does."
            )


def _validate_projection_key(projection: SliceElement, id_name: str) -> None:
    """A projection's identity is exactly one key, the surfaced ``<slug>_id``
    (ADR-0041). The framework rejects a projection with no identifier, and a key of
    any other name leaves the projection keyed on the wrong field."""
    keys = sorted(
        field_name
        for field_name, ir_field in projection.fields.items()
        if ir_field.identifier
    )
    if keys != [id_name]:
        found = (
            f"marks {', '.join(repr(key) for key in keys)}" if keys else "marks none"
        )
        raise SliceGeneratorError(
            f"The projection {projection.name!r} must mark exactly one identity key, "
            f"its {id_name!r} field, but {found}. The framework rejects a projection "
            "without an identifier, and any other key reads the projection on the "
            "wrong field."
        )

    key_field = projection.fields[id_name]
    if key_field.kind != "identifier" or not _carries_aggregate_id(key_field):
        raise SliceGeneratorError(
            f"The projection {projection.name!r} declares its {id_name!r} key as a "
            "field that cannot hold the aggregate's id, which the projector copies "
            f"from the event. Declare {id_name!r} as an Identifier."
        )


def _derived_projection_name(aggregate_name: str) -> str:
    """The name the generator gives a read side the fragment omits."""
    return f"{aggregate_name}Summary"


def _derived_projector_name(aggregate_name: str) -> str:
    """The name the generator gives a projector the fragment omits."""
    return f"{aggregate_name}Projector"


def _derive_projection(event: SliceElement, name: str, slug: str) -> SliceElement:
    """The default projection for a write-side-only fragment: the event's fields with
    the surfaced ``<slug>_id`` promoted to the projection's ``Identifier`` key."""
    id_name = f"{slug}_id"
    fields: dict[str, IRField] = {}
    for field_name, ir_field in event.fields.items():
        if field_name == id_name:
            fields[field_name] = IRField(
                kind="identifier", type="Identifier", identifier=True
            )
        else:
            fields[field_name] = ir_field
    return SliceElement(name=_derived_projection_name(name), fields=fields)


def _derive_projector(
    name: str, projection_name: str, event_name: str
) -> SliceProjector:
    """The default projector for a write-side-only fragment: it reads the event into
    the derived projection."""
    return SliceProjector(
        name=_derived_projector_name(name), for_=projection_name, consumes=event_name
    )


# ---------------------------------------------------------------------------
# Per-field declaration forms
# ---------------------------------------------------------------------------
def _declare(ir_field: IRField) -> str:
    """The class-attribute annotation for one field (ADR-0041's per-field forms).

    A ``String`` with a ``max_length`` becomes ``Annotated[str, Field(max_length=N)]``
    and a plain ``String`` becomes ``str``; a projection's identity key becomes
    ``Identifier(identifier=True)`` and any other identifier reference
    ``Identifier(required=True)``; ``Text`` uses the ``Text`` field factory; and every
    other primitive type declares itself with its plain Python annotation.
    """
    if ir_field.kind == "identifier":
        if ir_field.identifier:
            return "Identifier(identifier=True)"
        return "Identifier(required=True)"
    if ir_field.type == "Text":
        if ir_field.max_length is not None:
            return f"Text(required=True, max_length={ir_field.max_length})"
        return "Text(required=True)"
    if ir_field.type == "String" and ir_field.max_length is not None:
        return f"Annotated[str, Field(max_length={ir_field.max_length})]"
    return _BASE_ANNOTATION[ir_field.type]


def _ordered_names(fields: Mapping[str, IRField], slug: str) -> list[str]:
    """Field names in a deterministic order: the surfaced ``<slug>_id`` first where it
    appears, then the rest by name. Field order is non-normative (ADR-0041)."""
    id_name = f"{slug}_id"
    names = sorted(fields)
    if id_name in fields:
        names.remove(id_name)
        return [id_name, *names]
    return names


def _field_block(fields: Mapping[str, IRField], slug: str) -> str:
    """The indented class body of field declarations, one per line."""
    return "\n".join(
        f"    {field_name}: {_declare(fields[field_name])}"
        for field_name in _ordered_names(fields, slug)
    )


def _event_value(field_name: str, slug: str) -> str:
    """The expression the create factory assigns to one event field: the aggregate's
    id for the surfaced ``<slug>_id``, else the aggregate attribute of the same name."""
    if field_name == f"{slug}_id":
        return f"{slug}.id"
    return f"{slug}.{field_name}"


# ---------------------------------------------------------------------------
# Import assembly
# ---------------------------------------------------------------------------
def _uses_annotated(fields: Mapping[str, IRField]) -> bool:
    """Whether any field renders as ``Annotated[str, Field(...)]`` (a bounded String),
    which is the only form that needs ``typing.Annotated`` and ``pydantic.Field``."""
    return any(f.type == "String" and f.max_length is not None for f in fields.values())


def _datetime_names(fields: Mapping[str, IRField]) -> list[str]:
    """The ``datetime`` names the fields need (``date`` for Date, ``datetime`` for
    DateTime), in import order."""
    names: set[str] = set()
    for f in fields.values():
        if f.type == "Date":
            names.add("date")
        elif f.type == "DateTime":
            names.add("datetime")
    return sorted(names)


def _protean_field_names(fields: Mapping[str, IRField]) -> list[str]:
    """The ``protean.fields`` factory names the fields need (``Identifier`` for an
    identifier field, ``Text`` for a text field), in import order."""
    names: set[str] = set()
    for f in fields.values():
        if f.kind == "identifier":
            names.add("Identifier")
        elif f.type == "Text":
            names.add("Text")
    return sorted(names)


def _join_groups(groups: list[list[str]]) -> str:
    """Join non-empty import groups with a blank line between them."""
    return "\n\n".join("\n".join(group) for group in groups if group)


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------
def _render_init(name: str) -> str:
    # ADR-0030 rule 4: the package initializer is side-effect free (docstring
    # only). A re-export here would run during traversal and risk the
    # partially-initialized-module cycle that discovery hit before.
    return (
        f'"""The {name} slice.\n\n'
        "Modules are discovered independently by ``domain.init()``. Keep this\n"
        "package initializer side-effect free so relative imports during\n"
        "traversal cannot create partially initialized-module cycles.\n"
        '"""\n'
    )


def _render_aggregate_base(
    name: str, slug: str, aggregate: SliceElement, event: SliceElement
) -> str:
    # The generated side of the seam. Carries structure (fields) and wiring (the
    # ``create`` factory that raises the created event). A plain, undecorated
    # ``BaseAggregate`` subclass: it registers nothing on its own, so importing it
    # during discovery adds no element; only the decorated subclass in
    # ``aggregate.py`` is registered. A re-run of ``add`` refreshes this file.
    agg_fields = aggregate.fields
    ordered_agg = _ordered_names(agg_fields, slug)

    field_lines = _field_block(agg_fields, slug)
    params = ", ".join(
        f"{field_name}: {_BASE_ANNOTATION[agg_fields[field_name].type]}"
        for field_name in ordered_agg
    )
    ctor_args = ", ".join(f"{field_name}={field_name}" for field_name in ordered_agg)
    event_args = "\n".join(
        f"                {field_name}={_event_value(field_name, slug)},"
        for field_name in _ordered_names(event.fields, slug)
    )

    stdlib: list[str] = []
    dt = _datetime_names(agg_fields)
    if dt:
        stdlib.append(f"from datetime import {', '.join(dt)}")
    typing_names = (["Annotated"] if _uses_annotated(agg_fields) else []) + ["Self"]
    stdlib.append(f"from typing import {', '.join(typing_names)}")

    third_party = ["from pydantic import Field"] if _uses_annotated(agg_fields) else []

    protean_group = ["from protean.core.aggregate import BaseAggregate"]
    protean_fields = _protean_field_names(agg_fields)
    if protean_fields:
        protean_group.append(f"from protean.fields import {', '.join(protean_fields)}")

    imports = _join_groups(
        [stdlib, third_party, protean_group, [f"from .events import {event.name}"]]
    )

    return f'''"""Generated base for the {name} aggregate.

``protean add`` generates this file and refreshes it on every re-run, so do not
edit it. Put your invariants and behavior in ``aggregate.py``, the hand-owned
subclass a re-run never overwrites (the generation-gap seam, ADR-0035).
"""

{imports}


class {name}Base(BaseAggregate):
    """Generated structure and wiring for {name}. Edit the subclass, not this."""

{field_lines}

    @classmethod
    def create(cls, {params}) -> Self:
        """Create a new {name} and raise {event.name}."""
        {slug} = cls({ctor_args})

        {slug}.raise_(
            {event.name}(
{event_args}
            )
        )

        return {slug}
'''


def _render_aggregate(name: str, package: str, domain_var: str) -> str:
    # The hand-owned side of the seam. The decorated subclass: this is the
    # registered aggregate, and where the developer's invariants and behavior
    # live. A re-run of ``add`` leaves this file as it is, so those edits are safe.
    # The class body is a docstring only; the developer fills it in.
    return f'''"""The {name} aggregate.

Your own logic lives here. ``protean add`` never overwrites this file, so add
invariants (``@invariant.post``) and behavior as methods on the class below. The
generated structure and wiring sit in ``aggregate_base.py`` (the generation-gap
seam, ADR-0035).
"""

from {package}.domain import {domain_var}

from .aggregate_base import {name}Base


@{domain_var}.aggregate
class {name}({name}Base):
    """The {name} aggregate root."""
'''


def _render_commands(
    name: str, slug: str, package: str, domain_var: str, command: SliceElement
) -> str:
    field_lines = _field_block(command.fields, slug)
    imports = _message_imports(command.fields, package, domain_var)
    return f'''"""Commands for the {name} aggregate."""

{imports}


@{domain_var}.command(part_of="{name}")
class {command.name}:
    """Command to create a new {name}."""

{field_lines}
'''


def _render_events(
    name: str, slug: str, package: str, domain_var: str, event: SliceElement
) -> str:
    field_lines = _field_block(event.fields, slug)
    imports = _message_imports(event.fields, package, domain_var)
    return f'''"""Events emitted by the {name} aggregate."""

{imports}


@{domain_var}.event(part_of="{name}")
class {event.name}:
    """Event emitted when a {name} is created."""

{field_lines}
'''


def _message_imports(
    fields: Mapping[str, IRField], package: str, domain_var: str
) -> str:
    """The import block for a command or event: stdlib, pydantic, protean.fields, and
    the project's ``domain`` module, each its own group."""
    stdlib: list[str] = []
    dt = _datetime_names(fields)
    if dt:
        stdlib.append(f"from datetime import {', '.join(dt)}")
    if _uses_annotated(fields):
        stdlib.append("from typing import Annotated")

    third_party = ["from pydantic import Field"] if _uses_annotated(fields) else []

    protean_fields = _protean_field_names(fields)
    protean_group = (
        [f"from protean.fields import {', '.join(protean_fields)}"]
        if protean_fields
        else []
    )

    return _join_groups(
        [
            stdlib,
            third_party,
            protean_group,
            [f"from {package}.domain import {domain_var}"],
        ]
    )


def _render_command_handlers(
    name: str,
    slug: str,
    package: str,
    domain_var: str,
    aggregate: SliceElement,
    command: SliceElement,
) -> str:
    create_args = ", ".join(
        f"{field_name}=command.{field_name}"
        for field_name in _ordered_names(aggregate.fields, slug)
    )
    return f'''"""Command handlers for the {name} aggregate."""

from protean import handle

from {package}.domain import {domain_var}

from .aggregate import {name}
from .commands import {command.name}


@{domain_var}.command_handler(part_of="{name}")
class {name}CommandHandler:
    """Handle commands for the {name} aggregate."""

    @handle({command.name})
    def handle_create_{slug}(self, command: {command.name}) -> str:
        """Create a {name} from the command and persist it.

        Returns the new aggregate's id so a synchronous caller can look it up
        right after ``domain.process``.
        """
        {slug} = {name}.create({create_args})

        repo = {domain_var}.repository_for({name})
        repo.add({slug})

        return {slug}.id
'''


def _render_projection(
    name: str, slug: str, package: str, domain_var: str, projection: SliceElement
) -> str:
    field_lines = _field_block(projection.fields, slug)
    imports = _projection_imports(projection.fields, package, domain_var)
    return f'''"""Read-model projection for the {name} aggregate."""

{imports}


@{domain_var}.projection
class {projection.name}:
    """A read-optimized view of {name} aggregates."""

{field_lines}

    class Meta:
        stream_name = "{slug}"
'''


def _projection_imports(
    fields: Mapping[str, IRField], package: str, domain_var: str
) -> str:
    """The import block for a projection. A projection always has an ``Identifier``
    key, so ``protean.fields`` and ``pydantic`` sit in one group (``protean.fields``
    first), matching the layout ``protean add`` has always emitted."""
    stdlib: list[str] = []
    dt = _datetime_names(fields)
    if dt:
        stdlib.append(f"from datetime import {', '.join(dt)}")
    if _uses_annotated(fields):
        stdlib.append("from typing import Annotated")

    middle: list[str] = []
    protean_fields = _protean_field_names(fields)
    if protean_fields:
        middle.append(f"from protean.fields import {', '.join(protean_fields)}")
    if _uses_annotated(fields):
        middle.append("from pydantic import Field")

    return _join_groups(
        [stdlib, middle, [f"from {package}.domain import {domain_var}"]]
    )


def _render_projectors(
    name: str,
    slug: str,
    package: str,
    domain_var: str,
    projection: SliceElement,
    projector: SliceProjector,
    event: SliceElement,
) -> str:
    summary_args = "\n".join(
        f"            {field_name}=event.{field_name},"
        for field_name in _ordered_names(projection.fields, slug)
    )
    return f'''"""Projector that keeps {projection.name} up to date."""

from protean.core.projector import on

from {package}.domain import {domain_var}

from .aggregate import {name}
from .events import {event.name}
from .projection import {projection.name}


@{domain_var}.projector(projector_for={projection.name}, aggregates=[{name}])
class {projector.name}:
    """Update the {projection.name} projection from {name} events."""

    @on({event.name})
    def on_{slug}_created(self, event: {event.name}) -> None:
        """Create a {projection.name} when a {name} is created."""
        summary = {projection.name}(
{summary_args}
        )

        repo = {domain_var}.repository_for({projection.name})
        repo.add(summary)
'''
