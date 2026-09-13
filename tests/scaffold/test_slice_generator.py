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
