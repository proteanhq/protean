"""Tests for the slice generator: it promotes a slice-shaped IR fragment (ADR-0041)
to the same create-only :class:`ChangePlan` ``protean add`` emits.

The generator is the shared machinery behind both ``protean add`` (which builds a
default fragment from a name) and ``protean new --from-model`` (which parses
one from text). These tests drive it directly with fragments and assert the planned
files reflect the fragment's fields, that a write-side-only fragment derives its read
side, that the default fragment reproduces today's slice, and that a fragment-driven
slice passes ``protean verify``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.scaffold import CreateFileOperation
from protean.scaffold.add_plan import plan_add_slice
from protean.scaffold.slice_generator import (
    IRField,
    SliceElement,
    SliceFragment,
    SliceGeneratorError,
    SliceProjector,
    generate_slice_plan,
)

pytestmark = pytest.mark.no_test_domain

# Reused field entries, exactly ADR-0041's field vocabulary.
_STR_100 = IRField(kind="standard", type="String", required=True, max_length=100)
_STR_PLAIN = IRField(kind="standard", type="String", required=True)


def _content_for(plan, suffix: str) -> str:
    op = next(
        op
        for op in plan.operations
        if isinstance(op, CreateFileOperation) and op.path.endswith(suffix)
    )
    return op.content


def _valid_fragment() -> SliceFragment:
    """A minimal, valid write-side-only fragment (the ADR's Order slice, read side
    omitted)."""
    return SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100}),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
    )


def test_default_fragment_reproduces_plan_add_slice(tmp_path):
    """The default fragment ``protean add`` builds, promoted through the generator,
    plans exactly the same operations ``plan_add_slice`` returns.

    Both sides route through ``generate_slice_plan``, so this is an equivalence
    check: it confirms the fragment ``plan_add_slice`` builds internally is the same
    one built here, not a guard against renderer drift. The anchor against drift from
    the pre-refactor ``add`` output is ``tests/scaffold/test_add_plan.py``.
    """
    package_dir = tmp_path / "proj" / "src" / "myproj"
    package_dir.mkdir(parents=True)
    (package_dir / "domain.py").write_text(
        "from protean.domain import Domain\n\nmyproj = Domain(name='myproj')\n"
    )

    via_add = plan_add_slice(str(tmp_path / "proj"), "aggregate", "Order")
    via_generator = generate_slice_plan(_valid_fragment(), "myproj", "myproj")

    assert via_add.description == via_generator.description
    assert [(op.path, op.content, op.ownership) for op in via_add.operations] == [
        (op.path, op.content, op.ownership) for op in via_generator.operations
    ]


def test_rich_fragment_is_reflected_in_every_file(tmp_path):
    """A fragment richer than the default declares each field in its per-type form,
    across all eight primitive types and both constraints, and every planned file is
    valid Python."""
    fields = {
        "title": IRField(kind="standard", type="String", required=True, max_length=200),
        "body": IRField(kind="text", type="Text", required=True),
        "note": IRField(kind="text", type="Text", required=True, max_length=500),
        "views": IRField(kind="standard", type="Integer", required=True),
        "rating": IRField(kind="standard", type="Float", required=True),
        "published": IRField(kind="standard", type="Boolean", required=True),
        "published_on": IRField(kind="standard", type="Date", required=True),
        "created_at": IRField(kind="standard", type="DateTime", required=True),
        "author_ref": IRField(kind="identifier", type="Identifier", required=True),
    }
    event_fields = {"article_id": _STR_PLAIN, **fields}
    fragment = SliceFragment(
        aggregate=SliceElement("Article", dict(fields)),
        command=SliceElement("CreateArticle", dict(fields)),
        event=SliceElement("ArticleCreated", event_fields),
    )

    plan = generate_slice_plan(fragment, "blog", "blog")

    base = _content_for(plan, "aggregate_base.py")
    # Each primitive type's declaration form, plus both constraints.
    assert "title: Annotated[str, Field(max_length=200)]" in base
    assert "body: Text(required=True)" in base
    assert "note: Text(required=True, max_length=500)" in base
    assert "views: int" in base
    assert "rating: float" in base
    assert "published: bool" in base
    assert "published_on: date" in base
    assert "created_at: datetime" in base
    assert "author_ref: Identifier(required=True)" in base
    # Imports the richer types pull in.
    assert "from datetime import date, datetime" in base
    assert "from typing import Annotated, Self" in base
    assert "from pydantic import Field" in base
    assert "from protean.fields import Identifier, Text" in base

    # The create factory takes the aggregate's fields (plain base annotations) and
    # sets the event's fields, the surfaced id from the aggregate's id.
    assert "views: int" in base
    assert "title: str" in base  # the create parameter, not the field declaration
    assert "article_id=article.id," in base
    assert "title=article.title," in base

    # The command carries the same fields; the event carries the surfaced id as a
    # plain String and the rest by name.
    assert "title: Annotated[str, Field(max_length=200)]" in _content_for(
        plan, "commands.py"
    )
    assert "article_id: str" in _content_for(plan, "events.py")

    # The command handler drives create from the command's fields.
    handler = _content_for(plan, "command_handlers.py")
    assert "Article.create(" in handler
    assert "title=command.title" in handler

    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        compile(op.content, op.path, "exec")


def test_write_side_only_fragment_derives_the_default_read_side(tmp_path):
    """Omit the projection and projector; the generator derives the default
    ``<Name>Summary`` projection (the surfaced id as the ``Identifier`` key) and the
    ``<Name>Projector``, so a write-side-only fragment is still a complete slice."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100}),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
    )

    plan = generate_slice_plan(fragment, "myproj", "myproj")

    projection = _content_for(plan, "projection.py")
    assert "class OrderSummary:" in projection
    # The surfaced id becomes the projection's identity key; the other field mirrors
    # the event.
    assert "order_id: Identifier(identifier=True)" in projection
    assert "name: Annotated[str, Field(max_length=100)]" in projection

    projectors = _content_for(plan, "projectors.py")
    assert "class OrderProjector:" in projectors
    assert "projector_for=OrderSummary" in projectors
    assert "@on(OrderCreated)" in projectors
    assert "order_id=event.order_id," in projectors

    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        compile(op.content, op.path, "exec")


def test_explicit_read_side_is_honored(tmp_path):
    """When the fragment carries its own projection and projector, the generator uses
    them instead of deriving a default."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100}),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
        projection=SliceElement(
            "OrderView",
            {
                "order_id": IRField(
                    kind="identifier", type="Identifier", identifier=True
                ),
                "name": _STR_100,
            },
        ),
        projector=SliceProjector(
            name="OrderViewProjector", for_="OrderView", consumes="OrderCreated"
        ),
    )

    plan = generate_slice_plan(fragment, "myproj", "myproj")

    assert "class OrderView:" in _content_for(plan, "projection.py")
    projectors = _content_for(plan, "projectors.py")
    assert "class OrderViewProjector:" in projectors
    assert "projector_for=OrderView" in projectors

    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        compile(op.content, op.path, "exec")


def test_unsupported_field_type_raises(tmp_path):
    """A field of a type the generator does not render raises a clear error rather
    than emitting code that will not compile."""
    fragment = SliceFragment(
        aggregate=SliceElement(
            "Order",
            {"price": IRField(kind="standard", type="Decimal", required=True)},
        ),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    message = str(exc_info.value)
    assert "Decimal" in message and "price" in message


def test_event_without_surfaced_id_raises(tmp_path):
    """The event must declare the surfaced ``<slug>_id`` so the create factory can set
    it from the aggregate's id; without it the generator refuses to render."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100}),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement("OrderCreated", {"name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "order_id" in str(exc_info.value)


def _fragment_with(**overrides) -> SliceFragment:
    """The valid fragment with one participant replaced, for the rejection tests."""
    parts = {
        "aggregate": SliceElement("Order", {"name": _STR_100}),
        "command": SliceElement("CreateOrder", {"name": _STR_100}),
        "event": SliceElement(
            "OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}
        ),
    }
    parts.update(overrides)
    return SliceFragment(**parts)


@pytest.mark.parametrize(
    ("field_name", "role"),
    [
        ("create", "aggregate"),
        ("cls", "aggregate"),
        ("raise_", "aggregate"),
        ("to_dict", "aggregate"),
        ("Meta", "event"),
        ("copy", "command"),
    ],
)
def test_reserved_field_name_raises(field_name, role):
    """A field that takes the name of a framework member or of a symbol the generator
    writes shadows it, and the slice then cannot create or project. The generator
    rejects the fragment instead of rendering the broken class.

    ``create`` replaces the generated factory, ``cls`` collides with its first
    parameter, ``raise_`` and ``to_dict`` shadow ``BaseAggregate`` members, ``Meta``
    collides with the nested options class, and ``copy`` shadows a pydantic method.
    """
    element = {
        "aggregate": SliceElement("Order", {field_name: _STR_100}),
        "command": SliceElement("CreateOrder", {field_name: _STR_100}),
        "event": SliceElement(
            "OrderCreated", {"order_id": _STR_PLAIN, field_name: _STR_100}
        ),
    }[role]

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(_fragment_with(**{role: element}), "myproj", "myproj")

    assert field_name in str(exc_info.value)
    assert "reserved" in str(exc_info.value)


def test_underscore_field_name_raises():
    """The framework and pydantic own the underscore namespace, so a field cannot
    take a name in it."""
    fragment = _fragment_with(aggregate=SliceElement("Order", {"_name": _STR_100}))

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "_name" in str(exc_info.value)


@pytest.mark.parametrize("bad_name", ["class", "order-id", "2nd", ""])
def test_unusable_field_name_raises(bad_name):
    """The generator writes a field name into the generated class as written, so a
    keyword or a name that is not an identifier would not compile."""
    fragment = _fragment_with(aggregate=SliceElement("Order", {bad_name: _STR_100}))

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "usable Python name" in str(exc_info.value)


def test_unusable_element_name_raises():
    """An element name is written as a class name and imported by name, so it has the
    same constraint."""
    fragment = _fragment_with(command=SliceElement("Create-Order", {"name": _STR_100}))

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "Create-Order" in str(exc_info.value)


@pytest.mark.parametrize("clashing_name", ["OrderCreated", "OrderBase"])
def test_duplicate_class_name_raises(clashing_name):
    """The slice's classes land in one package and the command handler and projector
    import several into one module, so two of them cannot share a name. ``OrderBase``
    is the generated aggregate base, which is a name the slice defines too."""
    fragment = _fragment_with(
        command=SliceElement(clashing_name, {"name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert clashing_name in str(exc_info.value)


@pytest.mark.parametrize(
    "id_field",
    [
        IRField(kind="standard", type="Integer", required=True),
        IRField(kind="standard", type="String", required=True, max_length=20),
        IRField(kind="standard", type="DateTime", required=True),
    ],
)
def test_event_id_that_cannot_hold_the_aggregate_id_raises(id_field):
    """The create factory assigns the aggregate's id, a UUID string, to the event's
    surfaced ``<slug>_id``. A non-string type rejects it and a bounded String is too
    short for the 36-character value, so the generator rejects the shape up front."""
    fragment = _fragment_with(
        event=SliceElement("OrderCreated", {"order_id": id_field, "name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "order_id" in str(exc_info.value)


def test_event_id_as_identifier_is_accepted():
    """ADR-0041 allows the surfaced reference as an ``identifier`` as well as an
    unconstrained ``string``."""
    fragment = _fragment_with(
        event=SliceElement(
            "OrderCreated",
            {
                "order_id": IRField(
                    kind="identifier", type="Identifier", required=True
                ),
                "name": _STR_100,
            },
        ),
    )

    plan = generate_slice_plan(fragment, "myproj", "myproj")

    assert "order_id: Identifier(required=True)" in _content_for(plan, "events.py")


@pytest.mark.parametrize(
    ("projection_fields", "reason"),
    [
        ({"order_id": _STR_PLAIN, "name": _STR_100}, "no key at all"),
        (
            {
                "order_id": _STR_PLAIN,
                "name": IRField(kind="identifier", type="Identifier", identifier=True),
            },
            "the key on the wrong field",
        ),
        (
            {
                "order_id": IRField(
                    kind="identifier", type="Identifier", identifier=True
                ),
                "name": IRField(kind="identifier", type="Identifier", identifier=True),
            },
            "two keys",
        ),
    ],
)
def test_explicit_projection_without_the_surfaced_key_raises(projection_fields, reason):
    """A projection is keyed on exactly one field, the surfaced ``<slug>_id``
    (ADR-0041). The framework rejects a projection with no identifier outright, and a
    key on any other field reads the projection on the wrong value, so the generator
    checks the explicit read side rather than rendering it."""
    fragment = _fragment_with(
        projection=SliceElement("OrderView", projection_fields),
        projector=SliceProjector(
            name="OrderViewProjector", for_="OrderView", consumes="OrderCreated"
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "OrderView" in str(exc_info.value), reason


def test_explicit_projection_key_must_be_an_identifier():
    """A key marked on a plain ``String`` renders without the ``identifier=True``
    declaration, so the framework would reject the projection. The generator catches
    it first."""
    fragment = _fragment_with(
        projection=SliceElement(
            "OrderView",
            {
                "order_id": IRField(
                    kind="standard", type="String", required=True, identifier=True
                ),
                "name": _STR_100,
            },
        ),
        projector=SliceProjector(
            name="OrderViewProjector", for_="OrderView", consumes="OrderCreated"
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "Identifier" in str(exc_info.value)


def test_slug_that_is_not_a_usable_name_raises():
    """The slug is a local variable, a method suffix, and the id-field prefix, so it
    has to be a usable Python name even when the aggregate name is. ``class_`` is a
    valid element name whose slug is the keyword ``class``."""
    fragment = SliceFragment(
        aggregate=SliceElement("class_", {"name": _STR_100}),
        command=SliceElement("CreateThing", {"name": _STR_100}),
        event=SliceElement("ThingCreated", {"class_id": _STR_PLAIN, "name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "usable Python name" in str(exc_info.value)


@pytest.mark.parametrize(
    ("aggregate_name", "domain_var"),
    [("Repo", "myproj"), ("Domain", "domain")],
)
def test_slug_colliding_with_a_handler_local_raises(aggregate_name, domain_var):
    """The generated command handler holds its repository in ``repo`` and reaches the
    domain through the project's domain variable, and reads both back. A slug that
    takes either name makes the handler call the wrong object: ``Repo`` gives
    ``repo.add(repo)`` and ``Domain`` gives ``domain.repository_for`` on the
    aggregate."""
    slug = aggregate_name.lower()
    fragment = SliceFragment(
        aggregate=SliceElement(aggregate_name, {"name": _STR_100}),
        command=SliceElement(f"Create{aggregate_name}", {"name": _STR_100}),
        event=SliceElement(
            f"{aggregate_name}Created",
            {f"{slug}_id": _STR_PLAIN, "name": _STR_100},
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", domain_var)

    assert slug in str(exc_info.value)


@pytest.mark.parametrize("clashing_name", ["OrderSummary", "OrderProjector"])
def test_clash_with_a_derived_read_side_name_raises(clashing_name):
    """A fragment that omits its read side still defines ``<Aggregate>Summary`` and
    ``<Aggregate>Projector``, because the generator derives them. An event named
    ``OrderSummary`` would have ``projectors.py`` import that name from both
    ``events`` and ``projection``."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100}),
        command=SliceElement(clashing_name, {"name": _STR_100}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert clashing_name in str(exc_info.value)


@pytest.mark.parametrize("clashing_name", ["BaseAggregate", "Identifier", "handle"])
def test_element_name_clashing_with_a_generated_import_raises(clashing_name):
    """The generated modules import these names, so a class named for one replaces the
    import in the module carrying both. An event named ``BaseAggregate`` makes
    ``class OrderBase(BaseAggregate)`` inherit the event instead of the aggregate
    base, leaving the create path without ``raise_``."""
    fragment = _fragment_with(
        event=SliceElement(clashing_name, {"order_id": _STR_PLAIN, "name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert clashing_name in str(exc_info.value)


def test_element_name_clashing_with_the_domain_variable_raises():
    """The generated modules import the project's domain variable by name, so a class
    that takes it would be what the decorators resolve to."""
    fragment = _fragment_with(command=SliceElement("domain", {"name": _STR_100}))

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "domain")

    assert "domain" in str(exc_info.value)


def test_projection_named_for_the_projector_local_raises():
    """The projector builds the projection into ``summary`` and then asks the domain
    for that projection's repository. A projection named ``summary`` would have the
    second line pass the instance instead of the class."""
    fragment = _fragment_with(
        projection=SliceElement(
            "summary",
            {
                "order_id": IRField(
                    kind="identifier", type="Identifier", identifier=True
                ),
                "name": _STR_100,
            },
        ),
        projector=SliceProjector(
            name="OrderProjector", for_="summary", consumes="OrderCreated"
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "summary" in str(exc_info.value)


def _explicit_read_side(projection_fields) -> SliceFragment:
    return _fragment_with(
        projection=SliceElement("OrderView", projection_fields),
        projector=SliceProjector(
            name="OrderViewProjector", for_="OrderView", consumes="OrderCreated"
        ),
    )


_PROJECTION_KEY = IRField(kind="identifier", type="Identifier", identifier=True)


def test_projection_field_the_event_does_not_carry_raises():
    """The projector reads every projection field straight off the event (ADR-0041),
    so a field the event does not carry raises when the event is handled."""
    fragment = _explicit_read_side({"order_id": _PROJECTION_KEY, "extra": _STR_100})

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "extra" in str(exc_info.value)


def test_projection_field_shaped_differently_from_the_event_raises():
    """A projection's non-key fields carry the event field's type and constraints
    (ADR-0041); the projector copies the value across unchanged."""
    fragment = _explicit_read_side(
        {
            "order_id": _PROJECTION_KEY,
            "name": IRField(kind="standard", type="Integer", required=True),
        }
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "name" in str(exc_info.value)


def test_aggregate_field_named_id_is_accepted():
    """``id`` on an aggregate is not a collision: the framework keeps auto-injecting
    the identity and the declared field stays the tracked identifier, so the generated
    ``{slug}.id`` still resolves."""
    fragment = _fragment_with(
        aggregate=SliceElement("Order", {"id": _STR_PLAIN, "name": _STR_100})
    )

    plan = generate_slice_plan(fragment, "myproj", "myproj")

    assert "id: str" in _content_for(plan, "aggregate_base.py")


def test_aggregate_named_as_its_own_slug_raises():
    """An already-snake-case aggregate name equals its slug, so the handler renders
    ``order_item = order_item.create(...)``. Python makes the name local for the whole
    method, so reading the imported class raises ``UnboundLocalError``. The message
    points at the PascalCase name to use instead."""
    fragment = SliceFragment(
        aggregate=SliceElement("order_item", {"name": _STR_100}),
        command=SliceElement("CreateOrderItem", {"name": _STR_100}),
        event=SliceElement(
            "OrderItemCreated", {"order_item_id": _STR_PLAIN, "name": _STR_100}
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "OrderItem" in str(exc_info.value)


@pytest.mark.parametrize("domain_var", ["repo", "summary", "event", "command", "on"])
def test_domain_variable_colliding_with_generated_code_raises(domain_var):
    """The generated modules import the project's domain variable and read it inside
    the handler and projector. A project binding ``repo = Domain(...)`` renders
    ``repo = repo.repository_for(...)``, an ``UnboundLocalError``; one binding ``on``
    collides with the projector's imported decorator."""
    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(_fragment_with(), "myproj", domain_var)

    assert domain_var in str(exc_info.value)


@pytest.mark.parametrize("projection_name", ["summary", "repo", "event", "self"])
def test_projection_named_for_a_projector_local_raises(projection_name):
    """The projector method binds ``self``, ``event``, ``summary`` and ``repo``, and
    reads the projection class by name in the same method. A projection named for any
    of them resolves to the local instead."""
    fragment = _fragment_with(
        projection=SliceElement(
            projection_name,
            {
                "order_id": IRField(
                    kind="identifier", type="Identifier", identifier=True
                ),
                "name": _STR_100,
            },
        ),
        projector=SliceProjector(
            name="OrderProjector", for_=projection_name, consumes="OrderCreated"
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert projection_name in str(exc_info.value)


def test_event_field_reserved_on_the_derived_projection_raises():
    """A fragment with no read side has its projection derived from the event, so the
    event's field names have to clear the projection's reserved set too. ``defaults``
    is free on an event and a member of ``BaseProjection``."""
    fragment = _fragment_with(
        event=SliceElement(
            "OrderCreated", {"order_id": _STR_PLAIN, "defaults": _STR_100}
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "defaults" in str(exc_info.value)


@pytest.mark.parametrize("event_name", ["cls", "name"])
def test_event_named_for_a_create_factory_local_raises(event_name):
    """The create factory binds ``cls``, the slug, and one parameter per aggregate
    field, and reads the event class by name to raise it. An event named ``cls`` or
    after an aggregate field resolves to the local instead."""
    fragment = _fragment_with(
        event=SliceElement(event_name, {"order_id": _STR_PLAIN, "name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert event_name in str(exc_info.value)


@pytest.mark.parametrize(
    ("clashing_name", "field_type"),
    [("str", "String"), ("int", "Integer"), ("float", "Float"), ("bool", "Boolean")],
)
def test_element_named_for_a_field_annotation_raises(clashing_name, field_type):
    """The field declarations resolve their plain annotations at module level. An
    event named ``str`` is imported into ``aggregate_base.py``, where the create
    factory's ``name: str`` parameter then resolves to the event class."""
    typed = IRField(kind="standard", type=field_type, required=True)
    fragment = _fragment_with(
        aggregate=SliceElement("Order", {"value": typed}),
        event=SliceElement(clashing_name, {"order_id": _STR_PLAIN, "value": typed}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert clashing_name in str(exc_info.value)


def test_domain_variable_named_for_a_field_annotation_raises():
    """Same collision from the other side: importing the domain as ``bool`` takes the
    name over in a module whose declarations use it as an annotation."""
    flag = IRField(kind="standard", type="Boolean", required=True)
    fragment = _fragment_with(
        aggregate=SliceElement("Order", {"active": flag}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "active": flag}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "bool")

    assert "bool" in str(exc_info.value)


@pytest.mark.parametrize("domain_var", ["date", "datetime", "int", "Text"])
def test_domain_variable_a_slice_does_not_emit_is_accepted(domain_var):
    """The collision set is built per fragment, not from everything the renderers can
    emit. A String-only slice imports no ``date`` and annotates nothing ``int``, so a
    project that binds its domain to one of those names still plans, the way it did
    before the generator took over ``add``."""
    plan = generate_slice_plan(_fragment_with(), "myproj", domain_var)

    assert f"from myproj.domain import {domain_var}" in _content_for(
        plan, "commands.py"
    )


def test_domain_variable_a_slice_does_emit_is_rejected():
    """The same name is a real collision once the slice carries a field that needs it:
    a Date field imports ``date`` into the module that imports the domain."""
    when = IRField(kind="standard", type="Date", required=True)
    fragment = _fragment_with(
        aggregate=SliceElement("Order", {"due": when}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "due": when}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "date")

    assert "date" in str(exc_info.value)


def test_aggregate_declaring_the_surfaced_id_raises():
    """The create factory raises the event with ``<slug>_id=<slug>.id``, so an
    aggregate field of that name would be set on the aggregate and then dropped when
    the event is built. Rejected rather than silently discarded."""
    fragment = _fragment_with(
        aggregate=SliceElement("Order", {"order_id": _STR_PLAIN, "name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "order_id" in str(exc_info.value)


@pytest.mark.parametrize("role", ["aggregate", "command", "event"])
def test_identity_key_marked_outside_a_projection_raises(role):
    """The ``key`` flag is valid only on a projection's identifier field (ADR-0041).
    An event carrying an identifier reference such as ``user_id`` marked as a key would
    give the derived projection a second identity key."""
    marked = IRField(
        kind="identifier", type="Identifier", required=True, identifier=True
    )
    element = {
        "aggregate": SliceElement("Order", {"name": _STR_100, "user_id": marked}),
        "command": SliceElement("CreateOrder", {"name": _STR_100, "user_id": marked}),
        "event": SliceElement(
            "OrderCreated", {"order_id": _STR_PLAIN, "user_id": marked}
        ),
    }[role]

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(_fragment_with(**{role: element}), "myproj", "myproj")

    assert "user_id" in str(exc_info.value)


def test_field_named_for_an_imported_field_factory_is_accepted():
    """``Text`` and ``Identifier`` are imported factories, but a field declaration is a
    bare annotation, which does not bind the name in the class body. A field named
    ``Text`` alongside another ``Text`` field declares and constructs fine, so the
    generator does not reserve them."""
    fragment = _fragment_with(
        event=SliceElement(
            "OrderCreated",
            {
                "order_id": _STR_PLAIN,
                "Text": IRField(kind="text", type="Text", required=True),
                "note": IRField(kind="text", type="Text", required=True),
            },
        ),
    )

    plan = generate_slice_plan(fragment, "myproj", "myproj")

    events = _content_for(plan, "events.py")
    assert "Text: Text(required=True)" in events
    assert "note: Text(required=True)" in events


def test_domain_variable_named_for_the_generated_handler_raises():
    """``command_handlers.py`` imports the domain and defines
    ``<Aggregate>CommandHandler`` in the same module, and the handler method reads the
    domain by name. A project binding its domain to that name gets the handler class
    instead."""
    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(_fragment_with(), "myproj", "OrderCommandHandler")

    assert "OrderCommandHandler" in str(exc_info.value)


def test_element_clashing_with_the_generated_handler_name_raises():
    """The generated command handler is one of the slice's class names, so another
    element cannot take it either."""
    fragment = _fragment_with(
        command=SliceElement("OrderCommandHandler", {"name": _STR_100})
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "OrderCommandHandler" in str(exc_info.value)


@pytest.mark.parametrize(
    "ir_field",
    [
        IRField(kind="standard", type="Identifier", required=True),
        IRField(kind="identifier", type="String", required=True),
        IRField(kind="standard", type="Text", required=True),
        IRField(kind="text", type="String", required=True),
    ],
)
def test_mismatched_kind_and_type_raises(ir_field):
    """ADR-0041 pairs each type with one kind, and the generator reads both. A
    mismatched pair renders a field the fragment does not describe: standard over
    ``Identifier`` comes out a plain ``str``, identifier over ``String`` comes out an
    ``Identifier``. Rejected rather than rendered silently."""
    fragment = _fragment_with(aggregate=SliceElement("Order", {"ref": ir_field}))

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "ref" in str(exc_info.value)


@pytest.mark.parametrize("field_type", ["Integer", "Date", "Identifier"])
def test_max_length_on_a_type_that_takes_no_bound_raises(field_type):
    """``max_length`` is a string-only constraint. The renderers drop it on any other
    type, so the fragment would be honoured in part and in silence."""
    kind = "identifier" if field_type == "Identifier" else "standard"
    fragment = _fragment_with(
        aggregate=SliceElement(
            "Order",
            {"ref": IRField(kind=kind, type=field_type, required=True, max_length=10)},
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "max_length" in str(exc_info.value)


def test_projector_handler_is_named_after_the_event():
    """The grammar allows any event name, so the handler is named for the event it
    consumes rather than for creation. An ``OrderPlaced`` event used to generate
    ``on_order_created``, documented as handling creation."""
    fragment = _fragment_with(
        event=SliceElement("OrderPlaced", {"order_id": _STR_PLAIN, "name": _STR_100}),
    )

    projectors = _content_for(
        generate_slice_plan(fragment, "myproj", "myproj"), "projectors.py"
    )

    assert "def on_order_placed(self, event: OrderPlaced)" in projectors
    assert "on_order_created" not in projectors
    assert "is created" not in projectors


def test_projector_handler_name_is_unchanged_for_the_default_event():
    """Deriving the name from the event has to leave the default slice alone:
    ``OrderCreated`` still gives ``on_order_created`` and the same docstring."""
    projectors = _content_for(
        generate_slice_plan(_fragment_with(), "myproj", "myproj"), "projectors.py"
    )

    assert "def on_order_created(self, event: OrderCreated)" in projectors
    assert "Create a OrderSummary when a Order is created." in projectors


@pytest.mark.parametrize("bad_name", ["__class__", "__init__", "__evt"])
def test_element_name_with_two_underscores_raises(bad_name):
    """The generated code reads these names inside a class body. Python mangles a
    ``__name`` reference to ``_Class__name`` so the read misses, and the compiler
    binds ``__class__`` in any method that mentions it, so an event of that name has
    the create factory raise the enclosing aggregate class."""
    fragment = _fragment_with(
        event=SliceElement(bad_name, {"order_id": _STR_PLAIN, "name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert bad_name in str(exc_info.value)


@pytest.mark.parametrize("private_name", ["_Order", "_domain"])
def test_single_underscore_names_are_accepted(private_name):
    """One leading underscore is an ordinary private name, not a mangled one.
    ``_domain = Domain(...)`` is a composition root the planner has always accepted,
    and ``from pkg.domain import _domain`` with ``@_domain.aggregate`` renders and
    runs, so the generator must not reject it."""
    plan = generate_slice_plan(_fragment_with(), "myproj", private_name)

    assert f"@{private_name}.aggregate" in _content_for(plan, "aggregate.py")


def test_event_named_for_an_overridden_slug_raises():
    """The aggregate-base collision check has to use the slug the renderer receives,
    not one re-derived from the aggregate name. With a ``slug`` override the two
    differ, and an event named for the override would be called as the aggregate
    instance the factory just built."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100}),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement("custom", {"custom_id": _STR_PLAIN, "name": _STR_100}),
        slug="custom",
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "custom" in str(exc_info.value)


@pytest.mark.parametrize("bad_var", ["not-a-name", "class", "__class__", ""])
def test_domain_variable_that_is_not_a_usable_name_raises(bad_var):
    """``generate_slice_plan`` is exported and takes the domain variable directly, so
    it cannot assume a caller resolved a real one: ``not-a-name`` would render
    ``from myproj.domain import not-a-name``."""
    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(_fragment_with(), "myproj", bad_var)

    assert "domain variable" in str(exc_info.value)


@pytest.mark.parametrize("bound", [0, -1])
def test_non_positive_max_length_raises(bound):
    """ADR-0041's ``max_length`` is a positive integer. A zero or negative bound
    renders a declaration a required field can never satisfy."""
    fragment = _fragment_with(
        aggregate=SliceElement(
            "Order",
            {
                "name": IRField(
                    kind="standard", type="String", required=True, max_length=bound
                )
            },
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "max_length" in str(exc_info.value)


def test_event_docstring_is_accurate_for_a_non_creation_event():
    """Only the default ``<Name>Created`` event can be described as creation. The
    scaffold's own documentation has to stay true for any other event name."""
    fragment = _fragment_with(
        event=SliceElement("OrderPlaced", {"order_id": _STR_PLAIN, "name": _STR_100}),
    )

    events = _content_for(
        generate_slice_plan(fragment, "myproj", "myproj"), "events.py"
    )

    assert '"""Event emitted by the Order aggregate."""' in events
    assert "is created" not in events


def test_event_docstring_is_unchanged_for_the_default_event():
    """The default slice keeps the wording it has always had."""
    events = _content_for(
        generate_slice_plan(_fragment_with(), "myproj", "myproj"), "events.py"
    )

    assert '"""Event emitted when a Order is created."""' in events


def test_fragment_slug_overrides_the_name_derived_one():
    """A caller that already normalized passes its slug, because a name's class and
    slug do not always round-trip: ``aB`` normalizes to class ``AB`` and slug ``a_b``,
    while ``_slug_for('AB')`` is ``ab``. Without this the generator would look for the
    wrong id field and reject a slice ``add`` used to plan."""
    fragment = SliceFragment(
        aggregate=SliceElement("AB", {"name": _STR_100}),
        command=SliceElement("CreateAB", {"name": _STR_100}),
        event=SliceElement("ABCreated", {"a_b_id": _STR_PLAIN, "name": _STR_100}),
        slug="a_b",
    )

    plan = generate_slice_plan(fragment, "myproj", "myproj")

    assert plan.operations[0].path == "src/myproj/a_b/__init__.py"
    assert "a_b_id=a_b.id" in _content_for(plan, "aggregate_base.py")


def test_half_present_read_side_raises(tmp_path):
    """A projection without a projector (or the reverse) is rejected: the read side is
    both together or neither."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100}),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
        projection=SliceElement(
            "OrderSummary",
            {
                "order_id": IRField(
                    kind="identifier", type="Identifier", identifier=True
                )
            },
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "read side" in str(exc_info.value)


def test_projector_without_projection_raises(tmp_path):
    """The other half-present direction: a projector with no projection is rejected
    just like a projection with no projector."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100}),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
        projector=SliceProjector(
            name="OrderProjector", for_="OrderSummary", consumes="OrderCreated"
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "read side" in str(exc_info.value)


def test_projector_wired_to_the_wrong_participant_raises(tmp_path):
    """The projector's ``for`` and ``consumes`` must name the slice's own projection
    and event; a mismatch would generate a projector referencing a class the slice
    does not define."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100}),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
        projection=SliceElement(
            "OrderSummary",
            {
                "order_id": IRField(
                    kind="identifier", type="Identifier", identifier=True
                )
            },
        ),
        projector=SliceProjector(
            name="OrderProjector", for_="WrongName", consumes="OrderCreated"
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "WrongName" in str(exc_info.value)


def test_projector_consuming_the_wrong_event_raises(tmp_path):
    """When the projector's ``for`` matches the projection but its ``consumes`` names
    an event the slice does not define, the generator refuses to render."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100}),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
        projection=SliceElement(
            "OrderSummary",
            {
                "order_id": IRField(
                    kind="identifier", type="Identifier", identifier=True
                )
            },
        ),
        projector=SliceProjector(
            name="OrderProjector", for_="OrderSummary", consumes="OrderUpdated"
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "OrderUpdated" in str(exc_info.value)


# --- Acceptance #2: a fragment-driven slice passes ``protean verify`` ------------

_VERIFY_PACKAGE = "scaffolded"


def _generate_project(tmp_path: Path) -> Path:
    """Run ``protean new`` and return the generated project root."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    result = CliRunner().invoke(
        app,
        ["new", _VERIFY_PACKAGE, "-o", str(out), "--defaults", "--skip-setup"],
    )
    assert result.exit_code == 0, f"protean new failed: {result.output}"
    return out / _VERIFY_PACKAGE


def _materialize(project: Path, plan) -> None:
    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        target = project / op.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(op.content)


def _subprocess_env(project: Path) -> dict[str, str]:
    src = str(project / "src")
    existing = os.environ.get("PYTHONPATH", "")
    env = {
        **os.environ,
        "PYTHONPATH": src + os.pathsep + existing if existing else src,
    }
    env.pop("VIRTUAL_ENV", None)
    env.pop("PROTEAN_ENV", None)
    env.pop("PROTEAN_DEBUG", None)
    return env


def test_fragment_driven_slice_verifies_green(tmp_path):
    """Acceptance #2: a slice generated from a fragment with typed fields beyond the
    default, materialized into a ``protean new`` project, passes ``protean verify``
    (init + check + the project's pytest suite) as a real subprocess."""
    project = _generate_project(tmp_path)

    # Include richer types (Text and Date) alongside String and Integer so a green
    # verdict proves those field declarations register and validate in a real domain,
    # not just that they compile.
    fields = {
        "name": _STR_100,
        "quantity": IRField(kind="standard", type="Integer", required=True),
        "note": IRField(kind="text", type="Text", required=True, max_length=500),
        "available_on": IRField(kind="standard", type="Date", required=True),
    }
    fragment = SliceFragment(
        aggregate=SliceElement("Item", dict(fields)),
        command=SliceElement("CreateItem", dict(fields)),
        event=SliceElement("ItemCreated", {"item_id": _STR_PLAIN, **fields}),
    )
    plan = generate_slice_plan(fragment, _VERIFY_PACKAGE, _VERIFY_PACKAGE)
    _materialize(project, plan)

    # Prove the slice actually landed, so a green verdict reflects the generated
    # slice, not just the base project.
    assert (project / "src/scaffolded/item/aggregate_base.py").is_file()

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "protean",
            "verify",
            "-d",
            "src/scaffolded/domain.py:scaffolded",
            "--path",
            ".",
        ],
        cwd=project,
        env=_subprocess_env(project),
        capture_output=True,
        text=True,
        errors="replace",
    )

    assert completed.returncode == 0, (
        "protean verify must pass on a fragment-driven slice:\n"
        f"{completed.stdout}\n{completed.stderr}"
    )
