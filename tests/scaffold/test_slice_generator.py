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
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.scaffold import CreateFileOperation
from protean.scaffold.add_plan import plan_add_slice
from protean.scaffold.model_parser import parse_model
from protean.scaffold.slice_generator import (
    IRField,
    SliceElement,
    SliceFragment,
    SliceGeneratorError,
    SliceProjector,
    generate_slice_plan,
    split_words,
)

pytestmark = pytest.mark.no_test_domain

# Reused field entries, exactly ADR-0041's field vocabulary.
_STR_100 = IRField(kind="standard", type="String", required=True, max_length=100)
_STR_PLAIN = IRField(kind="standard", type="String", required=True)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("order_item", ["order", "item"]),
        ("orderItem", ["order", "Item"]),
        ("OrderItem", ["Order", "Item"]),
        ("Order", ["Order"]),
        ("XMLHttp", ["XML", "Http"]),
        ("HTTPServer", ["HTTP", "Server"]),
        ("HTTPS", ["HTTPS"]),
        ("__", []),
    ],
)
def test_split_words_splits_on_underscores_and_case_changes(name, expected):
    """``add`` shares this helper with the generator, so both derive the same class
    name and slug from a name. A run of capitals stays one word except for the last
    capital, which starts the next one, and each word keeps its original casing, so
    joining them back gives ``HTTPServer`` and not ``HttpServer``."""
    assert split_words(name) == expected


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


def _aligned_fragment(fields) -> SliceFragment:
    """The Order slice with one field map across the whole write side. The generator
    makes the command carry the aggregate's fields and the event's non-id fields be
    aggregate fields, so a test that varies the fields varies them everywhere."""
    return SliceFragment(
        aggregate=SliceElement("Order", dict(fields)),
        command=SliceElement("CreateOrder", dict(fields)),
        event=SliceElement(
            "OrderCreated",
            {
                "order_id": _STR_PLAIN,
                **{name: entry for name, entry in fields.items() if name != "id"},
            },
        ),
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
    across every supported primitive type and both constraints, and every planned file
    is valid Python."""
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


@pytest.mark.parametrize("field_type", [["String"], None, 7])
def test_field_type_that_is_not_a_string_raises(field_type):
    """``IRField`` is a plain dataclass, so a malformed mapping can put anything in
    ``type``. An unhashable one would blow the supported-type lookup up with a
    ``TypeError`` instead of the generator's own error, which is what a caller reads
    to tell a human what is wrong with their model."""
    fragment = _aligned_fragment(
        {"price": IRField(kind="standard", type=field_type, required=True)}
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "price" in str(exc_info.value)


def test_command_missing_an_aggregate_field_raises():
    """The generated handler calls ``create()`` with every aggregate field read off
    the command, so a field the command does not carry renders ``command.code``,
    which fails the moment the command is dispatched."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100, "code": _STR_PLAIN}),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "'code'" in str(exc_info.value)


def test_command_field_the_aggregate_does_not_declare_raises():
    """The handler passes only the aggregate's fields to ``create()``, so a command
    field the aggregate does not declare is a value the author wrote and the slice
    drops without a word."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100}),
        command=SliceElement("CreateOrder", {"name": _STR_100, "coupon": _STR_PLAIN}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "'coupon'" in str(exc_info.value)


def test_event_field_the_aggregate_does_not_declare_raises():
    """The create factory raises the event with every field other than the surfaced
    id read off the aggregate, so an event field the aggregate does not declare
    renders ``order.total``, which fails the moment the aggregate is created."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100}),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement(
            "OrderCreated",
            {"order_id": _STR_PLAIN, "name": _STR_100, "total": _STR_PLAIN},
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "'total'" in str(exc_info.value)


def test_event_carrying_fewer_fields_than_the_aggregate_is_accepted():
    """The event is the one write-side element that may say less: it carries the
    surfaced id and whichever aggregate fields the author wants on it."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100, "code": _STR_PLAIN}),
        command=SliceElement("CreateOrder", {"name": _STR_100, "code": _STR_PLAIN}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN}),
    )

    base = _content_for(
        generate_slice_plan(fragment, "myproj", "myproj"), "aggregate_base.py"
    )

    assert "order_id=order.id," in base
    assert "code=order.code" not in base


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
    surfaced ``<slug>_id``. A non-string type rejects it, and so does a String bounded
    below the 36-character value, so the generator rejects the shape up front."""
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


def test_event_id_as_a_string_long_enough_for_the_id_is_accepted():
    """ADR-0041 allows a ``max_length`` on any string field, and the id the create
    factory assigns is a 36-character UUID string. A bound that fits it holds the
    value, so only a shorter one is rejected."""
    fragment = _fragment_with(
        event=SliceElement(
            "OrderCreated",
            {
                "order_id": IRField(
                    kind="standard", type="String", required=True, max_length=36
                ),
                "name": _STR_100,
            },
        ),
    )

    plan = generate_slice_plan(fragment, "myproj", "myproj")

    assert "order_id: Annotated[str, Field(max_length=36)]" in _content_for(
        plan, "events.py"
    )


def test_bounded_event_id_with_an_authored_aggregate_id_raises():
    """A bound that fits the 36-character identity default fits nothing else. An
    aggregate that declares its own ``id`` renders ``create(cls, id: str, ...)``, so
    the id comes from the caller: ``CreateOrder(id="x" * 37)`` builds the aggregate
    and then fails when the create factory raises the event. The generator rejects
    the pair rather than render a slice that works for some ids and not others."""
    bounded_id = IRField(kind="standard", type="String", required=True, max_length=36)
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"id": _STR_PLAIN, "name": _STR_100}),
        command=SliceElement("CreateOrder", {"id": _STR_PLAIN, "name": _STR_100}),
        event=SliceElement("OrderCreated", {"order_id": bounded_id, "name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "order_id" in str(exc_info.value)
    assert "'id'" in str(exc_info.value)


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
                "order_id": IRField(kind="standard", type="String", identifier=True),
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


@pytest.mark.parametrize("clashing_name", ["BaseAggregate", "Self", "Annotated", "on"])
def test_element_name_clashing_with_a_generated_import_raises(clashing_name):
    """A class named for a symbol imported by a module that also carries the class
    replaces that import. ``aggregate_base.py`` imports the event alongside
    ``BaseAggregate``, ``Self`` and (for a bounded String field) ``Annotated``, and
    ``projectors.py`` imports it alongside ``on``. An event named ``BaseAggregate``
    makes ``class OrderBase(BaseAggregate)`` inherit the event instead of the
    aggregate base, leaving the create path without ``raise_``."""
    fragment = _fragment_with(
        event=SliceElement(clashing_name, {"order_id": _STR_PLAIN, "name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert clashing_name in str(exc_info.value)


def test_event_named_for_a_builtin_the_generated_base_reads_raises():
    """``aggregate_base.py`` decorates its create factory with ``@classmethod``, a
    builtin it reads by bare name. The module also imports the event, so an event
    named ``classmethod`` renders ``from .events import classmethod`` above the class
    and leaves ``@classmethod`` calling the event class: importing the generated base
    raises instead of defining the aggregate."""
    fragment = _fragment_with(
        event=SliceElement("classmethod", {"order_id": _STR_PLAIN, "name": _STR_100}),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "classmethod" in str(exc_info.value)
    assert "aggregate_base.py" in str(exc_info.value)


def test_command_named_for_a_builtin_only_the_base_reads_is_allowed():
    """The builtins are tracked per module like the imports are. ``commands.py``
    never reads ``classmethod``, so a command of that name renders and runs."""
    fragment = _fragment_with(command=SliceElement("classmethod", {"name": _STR_100}))

    plan = generate_slice_plan(fragment, "myproj", "myproj")

    assert "class classmethod:" in _content_for(plan, "commands.py")
    assert "@classmethod" in _content_for(plan, "aggregate_base.py")
    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        compile(op.content, op.path, "exec")


def test_name_clashing_with_another_module_only_is_allowed():
    """A name is only taken over where both bindings land in the same module.
    ``BaseAggregate`` is imported by ``aggregate_base.py``, which imports neither the
    command nor the project's domain, so a command of that name renders."""
    fragment = _fragment_with(command=SliceElement("BaseAggregate", {"name": _STR_100}))

    plan = generate_slice_plan(fragment, "myproj", "myproj")

    assert "class BaseAggregate:" in _content_for(plan, "commands.py")
    assert "from .commands import BaseAggregate" in _content_for(
        plan, "command_handlers.py"
    )
    assert "class OrderBase(BaseAggregate):" in _content_for(plan, "aggregate_base.py")
    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        compile(op.content, op.path, "exec")


def test_domain_variable_clashing_with_the_generated_base_only_is_allowed():
    """``aggregate_base.py`` is the one generated module that does not import the
    project's domain, so the names it imports are free for the domain variable. A
    project binding ``BaseAggregate = Domain(...)`` renders."""
    plan = generate_slice_plan(_fragment_with(), "myproj", "BaseAggregate")

    base = _content_for(plan, "aggregate_base.py")
    assert "from protean.core.aggregate import BaseAggregate" in base
    assert "class OrderBase(BaseAggregate):" in base
    assert "from myproj.domain import BaseAggregate" in _content_for(
        plan, "aggregate.py"
    )
    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        compile(op.content, op.path, "exec")


def test_domain_variable_named_for_a_type_the_slice_does_not_declare_is_allowed():
    """The imported names are per fragment: a slice with no Date field imports no
    ``date``, so a project binding ``date = Domain(...)`` renders."""
    plan = generate_slice_plan(_valid_fragment(), "myproj", "date")

    assert "from myproj.domain import date" in _content_for(plan, "commands.py")
    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        compile(op.content, op.path, "exec")


def test_field_type_imports_are_per_module():
    """The imports are per module, and the event is the one write-side element that
    may carry fewer fields than the aggregate. A Date field the event does not carry
    leaves ``events.py`` without ``date``, though the two modules that declare it
    import it."""
    fields = {
        "name": _STR_100,
        "due_on": IRField(kind="standard", type="Date", required=True),
    }
    fragment = SliceFragment(
        aggregate=SliceElement("Order", dict(fields)),
        command=SliceElement("CreateOrder", dict(fields)),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
    )

    plan = generate_slice_plan(fragment, "myproj", "myproj")

    assert "from datetime import date" in _content_for(plan, "aggregate_base.py")
    assert "from datetime import date" in _content_for(plan, "commands.py")
    assert "from datetime import date" not in _content_for(plan, "events.py")


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
    """``id`` on an aggregate is not a collision. The generator writes the field on
    the generated base and registers the hand-owned subclass, and the framework
    injects its identity on that subclass, so ``id`` stays the tracked identifier and
    the generated ``{slug}.id`` resolves.
    ``test_slice_whose_fields_take_framework_names_verifies_green`` runs the slice to
    prove it."""
    fragment = _aligned_fragment({"id": _STR_PLAIN, "name": _STR_100})

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


@pytest.mark.parametrize("aggregate_name", ["self", "command", "repo"])
def test_aggregate_named_for_a_handler_local_raises(aggregate_name):
    """The handler method binds ``self``, ``command`` and ``repo``, and reads the
    aggregate class by name in the same method, to call ``create`` and to ask for its
    repository. An aggregate named ``command`` renders
    ``order = command.create(...)``, which calls the method on the command instance,
    so the slice cannot create the aggregate."""
    fragment = SliceFragment(
        aggregate=SliceElement(aggregate_name, {"name": _STR_100}),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
        # A supplied slug keeps the name clear of the slug it would derive, so the
        # handler-local collision is what this exercises.
        slug="order",
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert aggregate_name in str(exc_info.value)


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


_IDENTIFIER = IRField(kind="identifier", type="Identifier", required=True)
_TEXT = IRField(kind="text", type="Text", required=True)


def _factory_backed_fragment() -> SliceFragment:
    """A fragment whose fields all render through a field factory (``Identifier(...)``
    or ``Text(...)``), so no generated module declares a field with a plain ``str``
    annotation."""
    return SliceFragment(
        aggregate=SliceElement("Order", {"body": _TEXT}),
        command=SliceElement("CreateOrder", {"body": _TEXT}),
        event=SliceElement("OrderCreated", {"order_id": _IDENTIFIER, "body": _TEXT}),
    )


def test_domain_variable_named_str_raises():
    """The command handler returns the new aggregate's id, so ``command_handlers.py``
    writes ``-> str`` whatever the slice's fields are. A project binding
    ``str = Domain(...)`` has that module import the domain as ``str``, and the return
    annotation then resolves to the domain instead of the built-in."""
    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(_factory_backed_fragment(), "myproj", "str")

    message = str(exc_info.value)
    assert "str" in message
    assert "command_handlers.py" in message


def test_command_named_str_raises():
    """Same collision from the other side: ``command_handlers.py`` imports the command
    by name, so a command named ``str`` takes over the handler's return annotation."""
    fragment = _factory_backed_fragment()
    fragment = SliceFragment(
        aggregate=fragment.aggregate,
        command=SliceElement("str", {"body": _TEXT}),
        event=fragment.event,
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    message = str(exc_info.value)
    assert "str" in message
    assert "command_handlers.py" in message


def test_element_named_str_is_allowed_where_no_module_writes_str():
    """The collision set follows the forms a module actually emits. An ``Integer``
    slice annotates nothing ``str``: ``aggregate_base.py`` carries the event alongside
    ``qty: int`` create parameters, and ``command_handlers.py`` does not import the
    event at all. So an event named ``str`` renders."""
    qty = IRField(kind="standard", type="Integer", required=True)
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"qty": qty}),
        command=SliceElement("CreateOrder", {"qty": qty}),
        event=SliceElement("str", {"order_id": _IDENTIFIER, "qty": qty}),
    )

    plan = generate_slice_plan(fragment, "myproj", "myproj")

    assert "class str:" in _content_for(plan, "events.py")
    assert "from .events import str" in _content_for(plan, "aggregate_base.py")
    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        compile(op.content, op.path, "exec")


def test_identifier_and_text_fields_leave_str_free_in_their_own_module():
    """``Identifier`` and ``Text`` fields render through a field factory, so the module
    that declares them reads no plain annotation. ``projection.py`` here declares
    nothing but those two forms and carries no other ``str``, so a projection named
    ``str`` renders. Only the modules that do write the name (the aggregate base's
    create parameters, the handler's return annotation) reject a class of that name,
    and neither of them carries the projection."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"body": _TEXT}),
        command=SliceElement("CreateOrder", {"body": _TEXT}),
        event=SliceElement("OrderCreated", {"order_id": _IDENTIFIER, "body": _TEXT}),
        projection=SliceElement(
            "str",
            {
                "order_id": IRField(
                    kind="identifier", type="Identifier", identifier=True
                ),
                "body": _TEXT,
            },
        ),
        projector=SliceProjector(
            name="OrderViewProjector", for_="str", consumes="OrderCreated"
        ),
    )

    plan = generate_slice_plan(fragment, "myproj", "myproj")

    assert "class str:" in _content_for(plan, "projection.py")
    assert "projector_for=str" in _content_for(plan, "projectors.py")
    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        compile(op.content, op.path, "exec")


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


@pytest.mark.parametrize(
    "ir_field",
    [
        IRField(kind="standard", type="Date", required=True),
        IRField(kind="standard", type="DateTime", required=True),
        IRField(kind="standard", type="Float", required=True),
        IRField(kind="standard", type="Boolean", required=True),
        IRField(kind="text", type="Text", required=True),
    ],
)
def test_aggregate_id_the_framework_identity_cannot_hold_raises(ir_field):
    """``id`` is the aggregate's own identity. The registered subclass takes that
    field from the framework, which replaces whatever the generated base declares with
    an identity field holding a string, an integer or a UUID. A ``Date`` id renders a
    create factory whose ``id`` parameter the aggregate rejects when it is built, and
    a ``Text`` one renders a declaration the identity field drops."""
    fragment = _aligned_fragment({"id": ir_field, "name": _STR_100})

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "'id'" in str(exc_info.value)
    assert ir_field.type in str(exc_info.value)


def test_aggregate_id_declared_as_an_integer_raises():
    """The framework identity holds an integer, but the create factory passes the id
    straight into the event's surfaced ``order_id``, which ADR-0041 makes a String or
    an Identifier and both hold a string. An ``id: Integer`` renders a factory asking
    for an ``int`` that a String reference rejects and an Identifier one coerces, so
    the generator rejects the fragment instead."""
    integer_id = IRField(kind="standard", type="Integer", required=True)
    fragment = _aligned_fragment({"id": integer_id, "name": _STR_100})

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "'id'" in str(exc_info.value)
    assert "Integer" in str(exc_info.value)


def test_aggregate_id_with_a_bound_raises():
    """The identity field replaces the declaration, bound and all, so a bounded ``id``
    would render a slice that accepts a value past the bound without a word."""
    fragment = _aligned_fragment({"id": _STR_100, "name": _STR_100})

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "100" in str(exc_info.value)


@pytest.mark.parametrize(
    ("ir_field", "declaration"),
    [
        (_STR_PLAIN, "id: str"),
        (
            IRField(kind="identifier", type="Identifier", required=True),
            "id: Identifier(required=True)",
        ),
    ],
)
def test_aggregate_id_in_an_identity_shape_is_accepted(ir_field, declaration):
    """The two shapes that reach the event's surfaced reference, both of which render
    as ``str``. An authored ``id`` is how a caller supplies the identity instead of
    taking the generated one, which ``test_slice_whose_fields_take_framework_names_runs``
    and ``test_slice_with_an_identifier_id_runs`` drive end to end."""
    fragment = _aligned_fragment({"id": ir_field, "name": _STR_100})

    base = _content_for(
        generate_slice_plan(fragment, "myproj", "myproj"), "aggregate_base.py"
    )

    assert declaration in base


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


@pytest.mark.parametrize("role", ["aggregate", "command", "event"])
def test_optional_authored_field_raises(role):
    """Every authored field is required (ADR-0041) and the generator renders it that
    way: a ``Text`` field comes out ``Text(required=True)`` whatever the fragment says.
    A fragment asking for an optional field would get a required one without a word,
    so the generator rejects it instead."""
    optional = IRField(kind="text", type="Text", required=False)
    element = {
        "aggregate": SliceElement("Order", {"name": _STR_100, "note": optional}),
        "command": SliceElement("CreateOrder", {"name": _STR_100, "note": optional}),
        "event": SliceElement(
            "OrderCreated", {"order_id": _STR_PLAIN, "note": optional}
        ),
    }[role]

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(_fragment_with(**{role: element}), "myproj", "myproj")

    assert "note" in str(exc_info.value)


def test_projection_key_marked_required_raises():
    """The projection's identity key is the one field ADR-0041 leaves without the
    required flag, since it takes the framework identity default. The key renders as
    ``Identifier(identifier=True)``, which carries no required flag, so a key marked
    required would be rendered without it."""
    fragment = _explicit_read_side(
        {
            "order_id": IRField(
                kind="identifier", type="Identifier", required=True, identifier=True
            ),
            "name": _STR_100,
        }
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "order_id" in str(exc_info.value)


def test_field_named_for_an_imported_field_factory_is_accepted():
    """``Text`` and ``Identifier`` are imported factories, but a field declaration is a
    bare annotation, which does not bind the name in the class body. A field named
    ``Text`` alongside another ``Text`` field declares and constructs fine, so the
    generator does not reserve them."""
    fragment = _aligned_fragment(
        {
            "Text": IRField(kind="text", type="Text", required=True),
            "note": IRField(kind="text", type="Text", required=True),
        }
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


def test_default_event_handler_is_named_for_the_slug_not_the_event():
    """The aggregate name and the event name do not always give the same slug: ``aB``
    normalizes to class ``AB`` and slug ``a_b``, while ``ABCreated`` is one word plus
    ``Created`` and gives ``ab_created``. The default event keeps the handler name
    ``add`` has always written, which is built from the aggregate's slug."""
    fragment = SliceFragment(
        aggregate=SliceElement("AB", {"name": _STR_100}),
        command=SliceElement("CreateAB", {"name": _STR_100}),
        event=SliceElement("ABCreated", {"a_b_id": _STR_PLAIN, "name": _STR_100}),
        slug="a_b",
    )

    projectors = _content_for(
        generate_slice_plan(fragment, "myproj", "myproj"), "projectors.py"
    )

    assert "def on_a_b_created(self, event: ABCreated)" in projectors


def test_command_handler_method_is_named_after_the_command():
    """The grammar allows any command name, so the handler method is named for the
    command it dispatches, which is the framework's ``handle_<command_slug>``
    convention. A ``PlaceOrder`` command used to generate ``handle_create_order``."""
    fragment = _fragment_with(command=SliceElement("PlaceOrder", {"name": _STR_100}))

    handlers = _content_for(
        generate_slice_plan(fragment, "myproj", "myproj"), "command_handlers.py"
    )

    assert "def handle_place_order(self, command: PlaceOrder) -> str:" in handlers
    assert "handle_create_order" not in handlers
    assert "Create a Order from PlaceOrder and persist it." in handlers


def test_command_handler_method_is_unchanged_for_the_default_command():
    """Deriving the name from the command has to leave the default slice alone:
    ``CreateOrder`` still gives ``handle_create_order`` and the same docstring."""
    handlers = _content_for(
        generate_slice_plan(_fragment_with(), "myproj", "myproj"),
        "command_handlers.py",
    )

    assert "def handle_create_order(self, command: CreateOrder) -> str:" in handlers
    assert "Create a Order from the command and persist it." in handlers


def test_default_command_handler_method_is_named_for_the_slug_not_the_command():
    """The aggregate name and the command name do not always give the same slug:
    ``aB`` normalizes to class ``AB`` and slug ``a_b``, while ``CreateAB`` gives
    ``create_ab``. The default command keeps the handler name ``add`` has always
    written, which is built from the aggregate's slug."""
    fragment = SliceFragment(
        aggregate=SliceElement("AB", {"name": _STR_100}),
        command=SliceElement("CreateAB", {"name": _STR_100}),
        event=SliceElement("ABCreated", {"a_b_id": _STR_PLAIN, "name": _STR_100}),
        slug="a_b",
    )

    handlers = _content_for(
        generate_slice_plan(fragment, "myproj", "myproj"), "command_handlers.py"
    )

    assert "def handle_create_a_b(self, command: CreateAB) -> str:" in handlers


def test_command_docstring_is_accurate_for_a_non_creation_command():
    """Only the default ``Create<Name>`` command can be described as creation, so any
    other name gets wording that stays true."""
    fragment = _fragment_with(command=SliceElement("PlaceOrder", {"name": _STR_100}))

    commands = _content_for(
        generate_slice_plan(fragment, "myproj", "myproj"), "commands.py"
    )

    assert '"""Command for the Order aggregate."""' in commands
    assert "create a new" not in commands


def test_command_docstring_is_unchanged_for_the_default_command():
    """The default slice keeps the wording it has always had."""
    commands = _content_for(
        generate_slice_plan(_fragment_with(), "myproj", "myproj"), "commands.py"
    )

    assert '"""Command to create a new Order."""' in commands


def test_explicitly_empty_slug_raises():
    """``None`` is the absence value for the slug override, so an empty string is a
    bad slug rather than a request to derive one. It goes into the slice's paths, the
    handler's local and the event's id field, so the generator rejects it instead of
    planning a slice for a different slug."""
    fragment = SliceFragment(
        aggregate=SliceElement("Order", {"name": _STR_100}),
        command=SliceElement("CreateOrder", {"name": _STR_100}),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
        slug="",
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "usable Python name" in str(exc_info.value)


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


@pytest.mark.parametrize(
    "bad_package", ["../outside", "my proj", "my.proj", "class", "", "src/myproj"]
)
def test_package_that_is_not_a_usable_name_raises(bad_package):
    """``generate_slice_plan`` is exported and takes the package directly, so it
    cannot assume a caller resolved a real one. The package is both the directory the
    slice is planned under and the first segment of every generated import, so
    ``../outside`` would plan files outside the package and ``my.proj`` would write
    ``src/my.proj/order/`` with an import that points somewhere else."""
    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(_fragment_with(), bad_package, "myproj")

    assert "package" in str(exc_info.value)


@pytest.mark.parametrize("bad_var", ["not-a-name", "class", "__class__", ""])
def test_domain_variable_that_is_not_a_usable_name_raises(bad_var):
    """``generate_slice_plan`` is exported and takes the domain variable directly, so
    it cannot assume a caller resolved a real one: ``not-a-name`` would render
    ``from myproj.domain import not-a-name``."""
    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(_fragment_with(), "myproj", bad_var)

    assert "domain variable" in str(exc_info.value)


@pytest.mark.parametrize(
    ("package", "domain_var", "slug", "aggregate_name"),
    [
        (["myproj"], "myproj", None, "Order"),
        (7, "myproj", None, "Order"),
        ("myproj", ["myproj"], None, "Order"),
        ("myproj", None, None, "Order"),
        ("myproj", "myproj", 7, "Order"),
        ("myproj", "myproj", None, 7),
    ],
)
def test_input_that_is_not_a_string_raises(package, domain_var, slug, aggregate_name):
    """``generate_slice_plan`` is exported, and nothing between a caller and it
    enforces the annotations: the CLI and the MCP tool can hand it anything, and a
    caller can build a ``SliceFragment`` directly rather than through
    ``from_mapping``. Every one of these names is written into the generated code as
    written, so a non-string is the generator's own error and not an
    ``AttributeError`` from ``str.isidentifier`` or a ``TypeError`` from the split
    that derives the slug."""
    fragment = _fragment_with(
        aggregate=SliceElement(aggregate_name, {"name": _STR_100}), slug=slug
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, package, domain_var)

    assert "is not a string" in str(exc_info.value)


def test_command_field_shaped_differently_from_the_aggregate_raises():
    """The generated handler reads each field off the command and passes it to
    ``create()``, which takes the shape the aggregate declares. A command that carries
    ``name`` as an Integer renders ``Order.create(name=command.name)`` against a
    ``name: str`` parameter, so a command the author considers valid fails when the
    aggregate is built."""
    fragment = _fragment_with(
        command=SliceElement(
            "CreateOrder",
            {"name": IRField(kind="standard", type="Integer", required=True)},
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "'name'" in str(exc_info.value)


def test_command_field_bounded_differently_from_the_aggregate_raises():
    """The same holds for the constraints, not just the type: a command bounded at 200
    accepts a name the aggregate's 100 rejects, so the slice takes the command and
    fails on the create."""
    fragment = _fragment_with(
        command=SliceElement(
            "CreateOrder",
            {
                "name": IRField(
                    kind="standard", type="String", required=True, max_length=200
                )
            },
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "'name'" in str(exc_info.value)


def test_event_field_shaped_differently_from_the_aggregate_raises():
    """The create factory raises the event with each field read straight off the
    aggregate, so an event that declares ``name`` as an Integer is handed the
    aggregate's string and fails the moment the aggregate is created."""
    fragment = _fragment_with(
        event=SliceElement(
            "OrderCreated",
            {
                "order_id": _STR_PLAIN,
                "name": IRField(kind="standard", type="Integer", required=True),
            },
        ),
    )

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert "'name'" in str(exc_info.value)


@pytest.mark.parametrize("bound", [0, -1, 1.5, True, "20"])
def test_max_length_that_is_not_a_positive_integer_raises(bound):
    """ADR-0041's ``max_length`` is a positive integer, and ``IRField`` is a plain
    dataclass that does not enforce its annotations. A zero or negative bound renders
    a declaration a required field can never satisfy; a float, a bool, or a string
    renders a bound that is not one, or used to raise a ``TypeError`` from the
    comparison instead of the generator's own error."""
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


@pytest.mark.parametrize(
    ("flag_name", "value"),
    [
        ("required", "false"),
        ("required", 1),
        ("required", None),
        ("identifier", "yes"),
        ("identifier", 1),
    ],
)
def test_field_flag_that_is_not_a_boolean_raises(flag_name, value):
    """``required`` and ``identifier`` are true-or-false flags, and ``IRField`` is a
    plain dataclass that does not enforce its annotations. The guards that read them
    test truthiness, so ``required="false"`` would come out a required field and a
    truthy ``identifier`` would make the field the projection's key, both without a
    word. Only a real boolean gets past."""
    field = IRField(
        kind="standard", type="String", **{"required": True, flag_name: value}
    )
    fragment = _fragment_with(aggregate=SliceElement("Order", {"name": field}))

    with pytest.raises(SliceGeneratorError) as exc_info:
        generate_slice_plan(fragment, "myproj", "myproj")

    assert flag_name in str(exc_info.value)


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


def test_required_strings_keep_the_plain_annotation_form():
    """A required ``String`` renders as an annotation, bare or wrapped in
    ``Annotated[..., Field(max_length=N)]``. Pydantic reads either as a required
    field, and neither carries the non-empty floor Protean puts on a required
    ``String`` (``min_length=1``), which comes with the ``String(...)`` field factory:
    both forms accept ``""``. That is the output ``protean add`` has always written
    and the generator keeps it, for the bounded and the unbounded field alike.
    ``Text`` goes through the field factory and does carry ``required=True``."""
    fragment = _aligned_fragment(
        {
            "name": _STR_100,
            "code": _STR_PLAIN,
            "body": IRField(kind="text", type="Text", required=True),
        }
    )

    base = _content_for(
        generate_slice_plan(fragment, "myproj", "myproj"), "aggregate_base.py"
    )

    assert "code: str" in base
    assert "name: Annotated[str, Field(max_length=100)]" in base
    assert "body: Text(required=True)" in base


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


# --- The parser-to-generator path: a parsed fragment is a fragment ---------------

_PARSED_MODEL = """aggregate Order:
    field name: string(max_length=100)

command CreateOrder:
    field name: string(max_length=100)

event OrderCreated:
    field order_id: string
    field name: string(max_length=100)

projection OrderSummary:
    field order_id: identifier(key)
    field name: string(max_length=100)

projector OrderProjector:
    for OrderSummary
    consumes OrderCreated
"""


def test_parsed_model_promotes_to_a_plan():
    """ADR-0041's parser emits the fragment as plain data and the generator works in
    dataclasses. ``SliceFragment.from_mapping`` is the one step between them, so a
    parsed model promotes to the slice it describes, read side and all. The
    projector's ``for`` key is the grammar's word, a Python keyword, and lands in
    ``for_``."""
    fragment = SliceFragment.from_mapping(parse_model(_PARSED_MODEL))

    assert fragment.projector is not None
    assert fragment.projector.for_ == "OrderSummary"
    assert fragment.projector.consumes == "OrderCreated"

    plan = generate_slice_plan(fragment, "myproj", "myproj")

    assert [op.path for op in plan.operations] == [
        f"src/myproj/order/{filename}"
        for filename in (
            "__init__.py",
            "aggregate_base.py",
            "aggregate.py",
            "commands.py",
            "events.py",
            "command_handlers.py",
            "projection.py",
            "projectors.py",
        )
    ]
    assert "name: Annotated[str, Field(max_length=100)]" in _content_for(
        plan, "aggregate_base.py"
    )
    assert "class OrderProjector" in _content_for(plan, "projectors.py")
    assert "order_id: Identifier(identifier=True)" in _content_for(
        plan, "projection.py"
    )


def test_parsed_write_side_only_model_derives_its_read_side():
    """A model with no projection or projector parses to a fragment with neither, so
    the generator derives the default read side from the event, the same as any other
    write-side-only fragment."""
    model = _PARSED_MODEL.split("projection OrderSummary:")[0]

    fragment = SliceFragment.from_mapping(parse_model(model))

    assert fragment.projection is None
    assert fragment.projector is None
    assert "class OrderSummary" in _content_for(
        generate_slice_plan(fragment, "myproj", "myproj"), "projection.py"
    )


def test_parser_and_generator_derive_the_same_slug():
    """The fragment carries the normalized class name and no slug, so the parser and
    the generator have to derive the same one from it, and it has to be the one
    ``protean add`` derives from the name as authored. ``orderItem`` is not the class
    name and all three still land on ``order_item``. The few names where they would
    not, such as ``aB`` (class ``AB``, slug ``ab``, where ``add aB`` gives ``a_b``),
    the parser rejects: see
    ``TestParseRejections.test_aggregate_name_whose_slug_disagrees_with_add``."""
    model = (
        "aggregate orderItem:\n    field name: string\n\n"
        "command CreateOrderItem:\n    field name: string\n\n"
        "event OrderItemCreated:\n"
        "    field order_item_id: string\n"
        "    field name: string\n"
    )

    plan = generate_slice_plan(
        SliceFragment.from_mapping(parse_model(model)), "myproj", "myproj"
    )

    assert plan.operations[0].path == "src/myproj/order_item/__init__.py"
    assert "order_item_id=order_item.id" in _content_for(plan, "aggregate_base.py")


@pytest.mark.parametrize(
    ("mapping", "expected"),
    [
        ("not a fragment", "mapping"),
        ({"aggregate": {"name": "Order", "fields": {}}}, "'command', 'event'"),
        (
            {
                "aggregate": {"name": "Order", "fields": {}},
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
                "entity": {"name": "Line", "fields": {}},
            },
            "'entity'",
        ),
        (
            {
                "aggregate": {"fields": {}},
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
            },
            "'name'",
        ),
        (
            {
                "aggregate": {"name": "Order", "fields": []},
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
            },
            "fields",
        ),
        (
            {
                "aggregate": {
                    "name": "Order",
                    "fields": {"name": {"kind": "standard", "min_length": 2}},
                },
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
            },
            "'name'",
        ),
        (
            {
                "aggregate": {"name": "Order", "fields": {}},
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
                "projection": {"name": "OrderSummary", "fields": {}},
                "projector": {"name": "OrderProjector", "for": "OrderSummary"},
            },
            "'consumes'",
        ),
        (
            {
                "aggregate": "Order",
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
            },
            "not an element",
        ),
        (
            {
                "aggregate": {
                    "name": "Order",
                    "fields": {},
                    "description": "the order",
                },
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
            },
            "'description'",
        ),
        (
            {
                "aggregate": {"name": "Order", "fields": {}},
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
                "projection": {"name": "OrderSummary", "fields": {}},
                "projector": {
                    "name": "OrderProjector",
                    "for": "OrderSummary",
                    "consumes": "OrderCreated",
                    "module": "projectors",
                },
            },
            "'module'",
        ),
        (
            {
                "aggregate": {"name": 7, "fields": {}},
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
            },
            "not a string",
        ),
        (
            {
                "aggregate": {"name": "Order", "fields": {"name": "string"}},
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
            },
            "not an IR field entry",
        ),
        (
            {
                "aggregate": {
                    "name": "Order",
                    "fields": {7: {"kind": "standard", "type": "String"}},
                },
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
            },
            "keyed by 7",
        ),
        (
            {
                "aggregate": {
                    "name": "Order",
                    "fields": {None: {"kind": "standard", "type": "String"}},
                },
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
            },
            "keyed by None",
        ),
        (
            {
                "aggregate": {"name": "Order", "fields": {}},
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
                "projection": {"name": "OrderSummary", "fields": {}},
                "projector": "OrderProjector",
            },
            "not a projector",
        ),
        (
            {
                "aggregate": {"name": "Order", "fields": {}},
                "command": {"name": "CreateOrder", "fields": {}},
                "event": {"name": "OrderCreated", "fields": {}},
                "projection": {"name": "OrderSummary", "fields": {}},
                "projector": {
                    "name": 7,
                    "for": "OrderSummary",
                    "consumes": "OrderCreated",
                },
            },
            "not a string",
        ),
    ],
)
def test_mapping_that_is_not_a_fragment_raises(mapping, expected):
    """The adapter reads the shape only, and rejects rather than drop what it cannot
    read: a field entry carrying ``min_length`` is a field the generator does not
    render, so promoting it would write a field the fragment does not describe. A
    field keyed by something that is not a string goes the same way: coercing the key
    would name a field the fragment does not. An element or a projector carrying a key
    past its own is rejected too, at every level of the mapping, so a caller never gets
    a fragment that says less than the mapping it passed in."""
    with pytest.raises(SliceGeneratorError) as exc_info:
        SliceFragment.from_mapping(mapping)

    assert expected in str(exc_info.value)


def test_field_entry_keyed_by_something_that_is_not_a_string_raises():
    """Reading an entry's keys through ``str`` would let a key that is not a string,
    but prints as one, take the place of the entry the mapping carries under that
    name: the fragment says the field is a ``String`` and the generator would render
    a ``Text``. The adapter rejects the key instead, the way it rejects a field name
    that is not a string."""

    class PrintsAsType:
        def __str__(self) -> str:
            return "type"

    mapping = {
        "aggregate": {
            "name": "Order",
            "fields": {
                "name": {
                    "kind": "standard",
                    "type": "String",
                    PrintsAsType(): "Text",
                }
            },
        },
        "command": {"name": "CreateOrder", "fields": {}},
        "event": {"name": "OrderCreated", "fields": {}},
    }

    with pytest.raises(SliceGeneratorError) as exc_info:
        SliceFragment.from_mapping(mapping)

    assert "entry keyed by" in str(exc_info.value)


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


def test_parsed_model_slice_verifies_green(tmp_path):
    """The whole parser-to-code path, run rather than reasoned about: model text
    parses to a fragment mapping, ``SliceFragment.from_mapping`` reads it, the
    generator promotes it, and the slice it plans passes ``protean verify`` in a real
    ``protean new`` project. This is what ``protean new --from-model`` composes."""
    project = _generate_project(tmp_path)
    model = textwrap.dedent(
        """\
        aggregate Item:
            field name: string(max_length=100)
            field quantity: integer

        command CreateItem:
            field name: string(max_length=100)
            field quantity: integer

        event ItemCreated:
            field item_id: string
            field name: string(max_length=100)
            field quantity: integer

        projection ItemSummary:
            field item_id: identifier(key)
            field name: string(max_length=100)

        projector ItemProjector:
            for ItemSummary
            consumes ItemCreated
        """
    )

    fragment = SliceFragment.from_mapping(parse_model(model))
    plan = generate_slice_plan(fragment, _VERIFY_PACKAGE, _VERIFY_PACKAGE)
    _materialize(project, plan)

    assert (project / "src/scaffolded/item/projectors.py").is_file()

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
        "protean verify must pass on a slice generated from a parsed model:\n"
        f"{completed.stdout}\n{completed.stderr}"
    )


def test_slice_whose_fields_take_framework_names_runs(tmp_path):
    """Field names the generator deliberately does not reserve, run rather than
    reasoned about: an aggregate field named ``id``, a field named ``Text`` alongside
    another ``Text`` field, and a field named ``Identifier`` alongside another
    ``Identifier`` field.

    ``id`` on the generated base leaves the framework's identity injection to the
    hand-owned subclass, which is the class that gets registered, so ``id`` stays the
    tracked identifier. ``Text`` and ``Identifier`` are imported field factories, but
    a field declaration is a bare annotation with no ``=``, which does not bind the
    name in the class body, so the next declaration still reads the factory rather
    than the field in front of it.

    The slice is materialized into a real ``protean new`` project, which then runs
    ``protean verify`` and drives the generated command through ``domain.process``, so
    the aggregate is created, its event raised, and the aggregate read back by the id
    the authored field holds.
    """
    project = _generate_project(tmp_path)

    fields = {
        "id": _STR_PLAIN,
        "name": _STR_100,
        "Text": IRField(kind="text", type="Text", required=True),
        "note": IRField(kind="text", type="Text", required=True),
        "Identifier": IRField(kind="identifier", type="Identifier", required=True),
        "ref": IRField(kind="identifier", type="Identifier", required=True),
    }
    fragment = SliceFragment(
        aggregate=SliceElement("Thing", dict(fields)),
        command=SliceElement("CreateThing", dict(fields)),
        event=SliceElement(
            "ThingCreated",
            {"thing_id": _STR_PLAIN, **{k: v for k, v in fields.items() if k != "id"}},
        ),
    )
    plan = generate_slice_plan(fragment, _VERIFY_PACKAGE, _VERIFY_PACKAGE)
    _materialize(project, plan)

    base = (project / "src/scaffolded/thing/aggregate_base.py").read_text()
    assert "id: str" in base
    assert "Text: Text(required=True)" in base
    assert "Identifier: Identifier(required=True)" in base

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
        "protean verify must pass on a slice whose fields take framework names:\n"
        f"{completed.stdout}\n{completed.stderr}"
    )

    # ``verify`` proves the elements register. Driving the command proves they work:
    # the aggregate is read back by the id its authored ``id`` field holds, which is
    # what tracking the identity means.
    drive = textwrap.dedent(
        """
        from scaffolded.domain import scaffolded
        from scaffolded.thing.aggregate import Thing
        from scaffolded.thing.commands import CreateThing

        scaffolded.init()
        with scaffolded.domain_context():
            scaffolded.process(
                CreateThing(
                    id="thing-1",
                    name="a name",
                    Text="a",
                    note="b",
                    Identifier="i",
                    ref="r",
                )
            )
            found = scaffolded.repository_for(Thing).get("thing-1")
            print(
                "READ_BACK",
                found.id,
                found.Text,
                found.note,
                found.Identifier,
                found.ref,
            )
        """
    )
    driven = subprocess.run(
        [sys.executable, "-c", drive],
        cwd=project,
        env=_subprocess_env(project),
        capture_output=True,
        text=True,
        errors="replace",
    )

    assert driven.returncode == 0, (
        f"the generated slice must run:\n{driven.stdout}\n{driven.stderr}"
    )
    assert "READ_BACK thing-1 a b i r" in driven.stdout


def test_slice_with_an_identifier_id_runs(tmp_path):
    """The other shape an authored ``id`` may take, run rather than reasoned about.
    ``Identifier`` renders through the field factory where a ``String`` renders as a
    bare ``str``, and both hold the string the create factory passes into the event's
    surfaced ``order_id``. (``Integer`` is the shape the generator rejects: the event
    reference is a string, and an ``int`` id would not reach it.)

    ``protean verify`` is covered by the tests above; this one drives the command, so
    the id goes through the aggregate, into the raised event, and back out of the
    repository.
    """
    project = _generate_project(tmp_path)

    identifier_id = IRField(kind="identifier", type="Identifier", required=True)
    fields = {"id": identifier_id, "name": _STR_100}
    fragment = SliceFragment(
        aggregate=SliceElement("Order", dict(fields)),
        command=SliceElement("CreateOrder", dict(fields)),
        event=SliceElement("OrderCreated", {"order_id": _STR_PLAIN, "name": _STR_100}),
    )
    _materialize(
        project, generate_slice_plan(fragment, _VERIFY_PACKAGE, _VERIFY_PACKAGE)
    )

    base = (project / "src/scaffolded/order/aggregate_base.py").read_text()
    assert "id: Identifier(required=True)" in base
    assert "order_id=order.id," in base

    drive = textwrap.dedent(
        """
        from scaffolded.domain import scaffolded
        from scaffolded.order.aggregate import Order
        from scaffolded.order.commands import CreateOrder

        scaffolded.init()
        with scaffolded.domain_context():
            scaffolded.process(CreateOrder(id="order-1", name="a name"))
            print("READ_BACK", scaffolded.repository_for(Order).get("order-1").name)
        """
    )
    driven = subprocess.run(
        [sys.executable, "-c", drive],
        cwd=project,
        env=_subprocess_env(project),
        capture_output=True,
        text=True,
        errors="replace",
    )

    assert driven.returncode == 0, (
        f"the generated slice must run:\n{driven.stdout}\n{driven.stderr}"
    )
    assert "READ_BACK a name" in driven.stdout


def test_slice_whose_command_takes_a_framework_import_name_runs(tmp_path):
    """A class name only collides where the name is bound in the same module, so a
    command named ``BaseAggregate`` is valid: ``aggregate_base.py`` imports the core
    ``BaseAggregate`` but not the command, and ``command_handlers.py`` imports the
    command but not the core class. Run rather than reasoned about: the slice is
    materialized into a real ``protean new`` project, which then passes
    ``protean verify``."""
    project = _generate_project(tmp_path)

    fields = {"name": _STR_100}
    fragment = SliceFragment(
        aggregate=SliceElement("Crate", dict(fields)),
        command=SliceElement("BaseAggregate", dict(fields)),
        event=SliceElement("CrateCreated", {"crate_id": _STR_PLAIN, **fields}),
    )
    plan = generate_slice_plan(fragment, _VERIFY_PACKAGE, _VERIFY_PACKAGE)
    _materialize(project, plan)

    assert (
        "class BaseAggregate:"
        in (project / "src/scaffolded/crate/commands.py").read_text()
    )
    assert (
        "class CrateBase(BaseAggregate):"
        in (project / "src/scaffolded/crate/aggregate_base.py").read_text()
    )

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
        "protean verify must pass on a slice whose command takes a framework import "
        f"name:\n{completed.stdout}\n{completed.stderr}"
    )
