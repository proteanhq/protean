"""Plan a new element slice as a :class:`~protean.scaffold.ChangePlan`.

This module is the pure planner behind ``protean add <element-type> <name>``:
given a project directory and a name, it returns a
:class:`~protean.scaffold.ChangePlan` of :class:`CreateFileOperation`\\ s in the
ADR-0030 canonical layout. It writes nothing itself; the CLI applies the plan, or
renders it under ``--dry-run``.

For this first cut the only supported element type is ``aggregate``, which emits
one complete vertical slice: the aggregate, its create command, its created
event, the command handler that drives it, and a projector plus read-model
projection that consume the event. The projector is what makes the created event
a handled event, so ``protean verify`` on the applied slice is green.

The aggregate is split by a generation-gap seam (ADR-0035) so a later re-run of
``add`` never clobbers hand-written logic: a generated base (``aggregate_base.py``,
carrying structure and wiring) and a hand-owned subclass (``aggregate.py``, where
the developer's invariants and behavior live). Each :class:`CreateFileOperation`
carries an ``ownership`` marker (``"generated"`` vs ``"hand_owned"``) that tells
an applier which files a re-run may refresh and which it must leave alone.

The project is resolved from the ADR-0030 layout, without importing anything:
locate the single ``src/<package>/domain.py``, then AST-parse it to read the
package directory name (the import root) and the variable bound to the
``Domain(...)`` call (the name the generated decorators reference). This is not
the same mechanism as runtime discovery (``derive_domain`` honors
``PROTEAN_DOMAIN`` and a ``path:instance`` selector and imports the domain); the
planner only needs the package and the domain variable, and AST-reading them
keeps it deterministic and unit-testable against a directory of files, and correct
even when a project's domain variable differs from its package name.
"""

from __future__ import annotations

import ast
import keyword
from pathlib import Path

from protean.scaffold.change_plan import ChangePlan
from protean.scaffold.slice_generator import (
    IRField,
    SliceElement,
    SliceFragment,
    _split_words,
    generate_slice_plan,
)

__all__ = ["SUPPORTED_ELEMENT_TYPES", "AddPlanError", "plan_add_slice"]

# The element types ``add`` can plan today. The POC ships the write-side
# aggregate slice; more types come in later issues.
SUPPORTED_ELEMENT_TYPES = ("aggregate",)


class AddPlanError(Exception):
    """A user-facing planning failure: an unsupported type, a bad name, or a
    project the planner cannot resolve. The CLI turns this into a clear message
    and a usage exit code, so the message is written to be read by a human."""


def plan_add_slice(project_path: str, element_type: str, name: str) -> ChangePlan:
    """Compute a create-only :class:`ChangePlan` for one element slice.

    *project_path* is the project root (the directory that holds ``src/``).
    *element_type* must be ``"aggregate"`` for now. *name* is the aggregate name
    (e.g. ``"Order"``); it must be a valid Python identifier. It is normalized:
    the class name is the PascalCase form and the slug the snake_case one, so
    ``OrderItem``, ``orderItem`` and ``order_item`` all plan the same slice.

    Returns a plan whose operations are all :class:`CreateFileOperation`\\ s at the
    canonical ADR-0030 paths under ``src/<package>/<slug>/``. Touches no files.

    Raises :class:`AddPlanError` on an unsupported element type, a name that is
    not a valid identifier or that derives no valid class name and slug, or a
    project the planner cannot resolve (no ``src/<package>/domain.py``, more than
    one candidate, or a ``domain.py`` that does not construct a ``Domain``).
    """
    normalized_type = element_type.lower()
    if normalized_type not in SUPPORTED_ELEMENT_TYPES:
        supported = ", ".join(SUPPORTED_ELEMENT_TYPES)
        raise AddPlanError(
            f"Unsupported element type {element_type!r}. Supported: {supported}."
        )

    if not name.isidentifier():
        raise AddPlanError(
            f"Invalid name {name!r}: an element name must be a valid Python "
            "identifier (letters, digits, and underscores; not starting with a "
            "digit)."
        )

    # Class names follow the Example slice: Order / CreateOrder / OrderCreated /
    # OrderCommandHandler. The slug (the directory and the id-field prefix) is the
    # snake_case form, so ``Order`` lands in ``order/`` (ADR-0030) and
    # ``OrderItem`` in ``order_item/``. Both are derived from the same word split,
    # so ``order_item``, ``orderItem`` and ``OrderItem`` all plan the same slice.
    words = _split_words(name)
    if not words:
        raise AddPlanError(
            f"Invalid name {name!r}: an element name must contain at least one "
            "letter or digit."
        )
    class_name = "".join(word[:1].upper() + word[1:] for word in words)
    slug = "_".join(word.lower() for word in words)

    # A name like ``_2fa`` is a valid identifier but its words are not: the class
    # would be ``2fa`` and the variable ``2fa``, neither of which compiles.
    if not class_name.isidentifier() or not slug.isidentifier():
        raise AddPlanError(
            f"Invalid name {name!r}: it derives the class {class_name!r} and the "
            f"module variable {slug!r}, which are not valid Python names. Start "
            "each word with a letter or an underscore."
        )

    # A Python keyword is a valid identifier to ``str.isidentifier`` but cannot be
    # a class name or a variable name, so it would emit code that does not compile
    # (``class None:``, ``for = cls(...)``). Both derived names matter: ``None``
    # gives class ``None``; ``class`` gives slug ``class``. Reject either.
    if keyword.iskeyword(class_name) or keyword.iskeyword(slug):
        raise AddPlanError(
            f"Invalid name {name!r}: it derives a Python keyword "
            f"(class {class_name!r}, module variable {slug!r}), so the generated "
            "slice would not compile. Choose a name that is not a keyword."
        )

    package, domain_var = _resolve_project(project_path)

    # Express today's default slice as a write-side-only fragment and route it
    # through the shared generator (ADR-0041). The read side is omitted, so the
    # generator derives the default projection and projector; the result is the
    # same eight files ``add`` has always emitted. The only field is the
    # name-only aggregate's ``name`` (a bounded String); the event carries the
    # surfaced ``<slug>_id`` reference (a plain String) plus that name.
    name_field = IRField(kind="standard", type="String", required=True, max_length=100)
    id_field = IRField(kind="standard", type="String", required=True)
    fragment = SliceFragment(
        aggregate=SliceElement(name=class_name, fields={"name": name_field}),
        command=SliceElement(name=f"Create{class_name}", fields={"name": name_field}),
        event=SliceElement(
            name=f"{class_name}Created",
            fields={f"{slug}_id": id_field, "name": name_field},
        ),
    )

    return generate_slice_plan(fragment, package, domain_var)


def _resolve_project(project_path: str) -> tuple[str, str]:
    """Resolve ``(package, domain_var)`` from a project's ``src/`` tree.

    Locates the single ``src/<package>/domain.py``, then AST-parses it to read the
    variable bound to a ``Domain(...)`` call. No import, no installed deps.

    Raises :class:`AddPlanError` when ``src/`` is missing, when there is not
    exactly one ``domain.py`` candidate, or when ``domain.py`` binds no ``Domain``.
    """
    src = Path(project_path) / "src"
    if not src.is_dir():
        raise AddPlanError(
            f"No 'src' directory under {project_path!r}. Run 'add' from a project "
            "root generated by 'protean new'."
        )

    candidates = sorted(
        child
        for child in src.iterdir()
        if child.is_dir() and (child / "domain.py").is_file()
    )
    if not candidates:
        raise AddPlanError(
            f"No 'src/<package>/domain.py' found under {project_path!r}. "
            "The project must have a composition root (see ADR-0030)."
        )
    if len(candidates) > 1:
        names = ", ".join(candidate.name for candidate in candidates)
        raise AddPlanError(
            f"Found more than one 'src/<package>/domain.py' under {project_path!r} "
            f"({names}). 'add' targets a single composition root."
        )

    package_dir = candidates[0]
    package = package_dir.name
    domain_var = _read_domain_variable(package_dir / "domain.py")
    return package, domain_var


def _read_domain_variable(domain_py: Path) -> str:
    """Return the name of the top-level variable bound to a ``Domain(...)`` call.

    Reads the module with :mod:`ast` only, so a ``domain.py`` that imports heavy
    or uninstalled dependencies still resolves. Raises :class:`AddPlanError` when
    the file cannot be read or parsed, or binds no ``Domain`` at module level.
    """
    try:
        tree = ast.parse(domain_py.read_text(encoding="utf-8"), filename=str(domain_py))
    # A file that is not valid UTF-8 raises UnicodeDecodeError from read_text;
    # catch it here so a bad encoding is a usage error, not a traceback.
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise AddPlanError(f"Could not read {domain_py}: {exc}") from exc

    for node in tree.body:
        # Only plain ``name = Domain(...)`` assignments name the composition root.
        # Annotated assignments (``name: T = Domain(...)``) are handled too.
        target_name: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                target_name = target.id
                value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value = node.value

        if target_name is not None and value is not None and _is_domain_call(value):
            return target_name

    raise AddPlanError(
        f"{domain_py} does not construct a Domain at module level. "
        "Expected a line like `<name> = Domain(name=...)`."
    )


def _is_domain_call(value: ast.expr) -> bool:
    """Whether *value* is a call to ``Domain(...)`` (bare or attribute form).

    Matches on the name ``Domain``, so an import alias (``from protean import
    Domain as D`` then ``D(...)``) is not recognized. A ``protean new`` project
    always writes the bare ``Domain(...)`` form, so this only limits hand-written
    composition roots; resolving aliases is left for when that need is real.
    """
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Name):
        return func.id == "Domain"
    if isinstance(func, ast.Attribute):
        return func.attr == "Domain"
    return False
