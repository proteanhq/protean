"""Build every DX-pack skill example and require it to initialize.

Each ``skills/*/assets/*.py`` is a runnable teaching example that declares a
Protean domain. This harness runs every one of them and, for each, collects the
``Domain`` objects it defines, calls ``domain.init(traverse=False)``, and
requires the domain to have registered at least one element. That is the
structural contract the pack must keep: every bundled example is a well-formed
domain that registers real elements and initializes against the installed
framework, so an agent that copies the example gets working code.

The examples run in one child interpreter, each under its own ``run_name`` so
their element registrations land in separate namespaces and cannot collide. The
``run_name`` is never ``"__main__"``, so the runner executes each example's
definitions and skips its ``if __name__ == "__main__"`` demo block. A demo block
is a usage walk-through, and several end by launching a live uvicorn server that
never returns; initializing the domain checks the example without blocking on a
server or depending on a demo's runtime data.

The child interpreter keeps the example domains and their registrations out of
this test process. The harness reads package data and shells out; it never
touches a Domain here, so it skips the autouse ``test_domain`` fixture. It runs
in the core lane (no ``slow`` marker), so ``protean test`` gates it: one
framework import validates the whole example corpus in a couple of seconds.
"""

from __future__ import annotations

import ast
import io
import json
import re
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

from protean import dx

pytestmark = pytest.mark.no_test_domain

# The pack ships as package data; on a filesystem install its root is a real
# directory, which is what the runner needs to execute an example by path. The
# clean-venv wheel check in CI proves the same files survive the build.
PACK_ROOT = Path(str(dx.pack_files()))
SKILLS_ROOT = PACK_ROOT / dx.SKILLS_DIR

# The runner executes assets by path, so it needs the pack unpacked on disk. The
# accessor does not promise a filesystem root (a zip install would not have one);
# CI installs unzipped, so this skips cleanly only in the zip case.
if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the example runner needs a real "
        "directory to execute assets by path",
        allow_module_level=True,
    )


def _discover_assets() -> list[Path]:
    """Return every example asset under the pack, sorted, excluding package
    ``__init__.py`` markers (which define no example)."""
    return sorted(
        path for path in SKILLS_ROOT.glob("*/assets/*.py") if path.name != "__init__.py"
    )


def _independent_asset_count() -> int:
    """Count example assets by walking the tree with ``iterdir``.

    This walks the directories directly rather than reusing the glob in
    :func:`_discover_assets`, so a broken glob (one that silently matches nothing
    or too much) shows up as a count mismatch instead of a quietly empty run.
    """
    total = 0
    for skill_dir in SKILLS_ROOT.iterdir():
        assets_dir = skill_dir / "assets"
        if not (skill_dir.is_dir() and assets_dir.is_dir()):
            continue
        total += sum(
            1
            for path in assets_dir.iterdir()
            if path.suffix == ".py" and path.name != "__init__.py"
        )
    return total


ASSETS = _discover_assets()

# Every markdown page the pack ships, references pages included.
DOCS = sorted(SKILLS_ROOT.glob("**/*.md"))

# The child-interpreter runner. It discovers the same assets, runs each one's
# definitions under its own run_name (so registrations do not collide and the
# demo block is skipped), initializes every domain the example declares, and
# writes a JSON report (the count it processed and a line per failure) to the
# path in argv[2]. It writes to a file, not a stream, so the framework's own
# start-up logging on stderr cannot corrupt the report. It collects every
# failure: it runs all examples, then exits non-zero if any failed, so one run
# names every broken example instead of stopping at the first.
_RUNNER = """
import json
import pathlib
import runpy
import sys

from protean.domain import Domain

skills_root = pathlib.Path(sys.argv[1])
report_path = pathlib.Path(sys.argv[2])
assets = sorted(
    p for p in skills_root.glob("*/assets/*.py") if p.name != "__init__.py"
)
failures = []
for index, path in enumerate(assets):
    try:
        namespace = runpy.run_path(str(path), run_name="_dx_example_%d_" % index)
        domains = [v for v in namespace.values() if isinstance(v, Domain)]
        if not domains:
            raise RuntimeError("example defines no Domain")
        for domain in domains:
            domain.init(traverse=False)
            if not domain.registry.elements:
                raise RuntimeError("example domain registers no elements")
    except Exception as exc:  # report the failure, then keep going
        failures.append(
            "%s: %s: %s" % (path.relative_to(skills_root), type(exc).__name__, exc)
        )
report_path.write_text(json.dumps({"count": len(assets), "failures": failures}))
sys.exit(1 if failures else 0)
"""


def test_example_discovery_is_not_vacuous():
    # Guard against a run that validates nothing: if the glob matched no assets,
    # the harness would pass while building zero examples. Pin the count to an
    # independent walk so a broken glob fails, and to a floor near the real
    # corpus size (135 today) so a mass deletion cannot slip under it. The floor
    # leaves room for a small prune; a larger loss trips it.
    assert ASSETS, "discovered no example assets under the DX pack"
    assert len(ASSETS) == _independent_asset_count()
    assert len(ASSETS) >= 130


def test_every_example_builds_and_initializes(tmp_path):
    report_path = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, "-c", _RUNNER, str(SKILLS_ROOT), str(report_path)],
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert report_path.is_file(), (
        f"the example runner crashed before writing its report "
        f"(exit {result.returncode}):\n{result.stderr}"
    )
    report = json.loads(report_path.read_text())

    # The child ran the same set this process discovered, so a silent glob skew
    # (the child validating fewer examples than are on disk) fails here too.
    assert report["count"] == len(ASSETS)
    assert report["failures"] == [], (
        "examples failed to build and initialize:\n" + "\n".join(report["failures"])
    )
    assert result.returncode == 0


# --- The creation handler must establish every defaulted field ---------------
#
# `from_events()` builds a blank aggregate by setting every field to `None`,
# bypassing declared field defaults, then replays the events through `@apply`.
# So a field the creation event's handler leaves alone stays `None` and never
# reaches its declared default. The pack teaches exactly this, in
# `event-sourced-aggregate/SKILL.md` ("First event's `@apply` must set ALL
# fields") and again in its `references/anti-patterns.md` ("First Event's
# @apply Not Setting All Required Fields"), and then one asset broke it in the
# same PR that wrote the rule down: `Product` in
# `upcaster/assets/upcaster_multi_step_chain.py` declared
# `discount_pct = Float(default=0.0)` and never set it in `on_created`, so
# replaying a freshly created product produced `discount_pct = None`.
#
# This finds the creation handler by reading the source rather than by
# position: the factory classmethod names the event it raises, and the handler
# is the `@apply` method annotated with that event type. A positional rule
# ("the first `@apply` wins") would pass on a reordered asset that is wrong.


def _declared_defaults(class_node: ast.ClassDef) -> set[str]:
    """Field names in an aggregate body declared with a `default=`.

    Both declaration styles are in the pack: `balance = Float(default=0.0)` and
    the annotated `balance: Float(default=0.0)`.
    """
    defaults = set()
    for stmt in class_node.body:
        if isinstance(stmt, ast.AnnAssign):
            target, value = stmt.target, stmt.annotation
        elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        else:
            continue
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
            continue
        if any(kw.arg == "default" for kw in value.keywords):
            defaults.add(target.id)
    return defaults


def _is_event_sourced(class_node: ast.ClassDef) -> bool:
    for decorator in class_node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        for kw in decorator.keywords:
            if kw.arg == "event_sourced" and getattr(kw.value, "value", False) is True:
                return True
    return False


def _creation_event(class_node: ast.ClassDef) -> str | None:
    """The event type the aggregate's factory classmethod raises.

    A factory is a classmethod that returns an instance it built, so the first
    `self.raise_()`/`<name>.raise_()` inside a classmethod names the creation
    event. Returns `None` when the asset has no factory classmethod.
    """
    for stmt in class_node.body:
        if not isinstance(stmt, ast.FunctionDef):
            continue
        if not any(
            isinstance(d, ast.Name) and d.id == "classmethod"
            for d in stmt.decorator_list
        ):
            continue
        for node in ast.walk(stmt):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "raise_"
                and node.args
                and isinstance(node.args[0], ast.Call)
                and isinstance(node.args[0].func, ast.Name)
            ):
                return node.args[0].func.id
    return None


def _apply_handler(class_node: ast.ClassDef, event: str) -> ast.FunctionDef | None:
    """The `@apply` method whose event parameter is annotated with `event`."""
    for stmt in class_node.body:
        if not isinstance(stmt, ast.FunctionDef):
            continue
        if not any(
            isinstance(d, ast.Name) and d.id == "apply" for d in stmt.decorator_list
        ):
            continue
        args = stmt.args.args
        if (
            len(args) == 2
            and isinstance(args[1].annotation, ast.Name)
            and args[1].annotation.id == event
        ):
            return stmt
    return None


def _fields_assigned(func: ast.FunctionDef) -> set[str]:
    assigned = set()
    for node in ast.walk(func):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                assigned.add(target.attr)
    return assigned


def _event_sourced_aggregates() -> list[tuple[Path, ast.ClassDef]]:
    found = []
    for path in ASSETS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend(
            (path, node)
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and _is_event_sourced(node)
        )
    return found


def test_the_event_sourced_aggregate_sweep_is_not_vacuous():
    """A sweep that finds nothing would pass while checking nothing."""
    aggregates = _event_sourced_aggregates()
    assert len(aggregates) >= 6, (
        "expected the pack's event-sourced example aggregates, found "
        f"{[node.name for _, node in aggregates]}"
    )


def test_creation_handler_sets_every_defaulted_field():
    unset = []
    unchecked = []
    for path, node in _event_sourced_aggregates():
        event = _creation_event(node)
        if event is None:
            unchecked.append(
                f"{path.name}: {node.name} has no factory classmethod that "
                "raises a creation event"
            )
            continue
        handler = _apply_handler(node, event)
        if handler is None:
            unchecked.append(
                f"{path.name}: {node.name} raises {event} but has no `@apply` "
                f"handler annotated with {event}"
            )
            continue
        missing = _declared_defaults(node) - _fields_assigned(handler)
        if missing:
            unset.append(
                f"{path.name}: {node.name}.{handler.name} (handles {event}) "
                f"leaves {sorted(missing)} unset"
            )

    assert not unchecked, (
        "every event-sourced example aggregate must expose the pair this "
        "check reads (a factory that raises a creation event, and the `@apply` "
        "handler for it), or the check goes blind on that aggregate while the "
        "aggregate count still passes:\n  " + "\n  ".join(unchecked)
    )
    assert not unset, (
        "`from_events()` bypasses declared field defaults, so a field the "
        "creation event's `@apply` handler does not set replays as `None`. "
        "These examples teach that bug:\n  " + "\n  ".join(unset)
    )


# --- Every declared value object must actually be used -----------------------
#
# A teaching asset that defines a `@domain.value_object` and then never uses it
# shows the reader a concept it never demonstrates. `es_aggregate_with_entities.py`
# did exactly this: it declared `Money`, advertised "Value objects within ES
# aggregates" in its header, and gave `LineItem` a plain `unit_price: Float`, so
# `Money` sat orphaned. This sweep reads every asset and, for each value object it
# declares, requires the class name to appear somewhere else in the same file
# (embedded in an entity/aggregate via `ValueObject(...)`, constructed in a
# handler, referenced in the demo). A name used only by its own class definition
# is an orphan.


def _is_value_object(class_node: ast.ClassDef) -> bool:
    """True when the class is decorated with `@domain.value_object`.

    Both forms are in the pack: the bare `@domain.value_object` and the called
    `@domain.value_object(part_of="...")`.
    """
    for decorator in class_node.decorator_list:
        node = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(node, ast.Attribute) and node.attr == "value_object":
            return True
    return False


def _value_objects() -> list[tuple[Path, ast.Module, str]]:
    found = []
    for path in ASSETS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend(
            (path, tree, node.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and _is_value_object(node)
        )
    return found


def _name_is_referenced(tree: ast.Module, name: str) -> bool:
    """True when `name` appears as a `Name` node anywhere in the module.

    A class declaration stores its name as the `ClassDef.name` string, not as a
    `Name` node, so the declaration itself never counts as a reference. Any
    `Name` occurrence (`ValueObject(Money)`, `Money(amount=...)`) is a real use.
    """
    return any(
        isinstance(node, ast.Name) and node.id == name for node in ast.walk(tree)
    )


def test_the_value_object_sweep_is_not_vacuous():
    """A sweep that finds nothing would pass while checking nothing."""
    value_objects = _value_objects()
    assert len(value_objects) >= 40, (
        "expected the pack's example value objects, found "
        f"{sorted(name for _, _, name in value_objects)}"
    )


def test_every_value_object_is_referenced():
    orphans = []
    for path, tree, name in _value_objects():
        if not _name_is_referenced(tree, name):
            orphans.append(
                f"{path.name}: value object {name} is declared but never used"
            )

    assert not orphans, (
        "a value object an asset declares but never uses shows the reader a "
        "concept the asset does not actually demonstrate:\n  " + "\n  ".join(orphans)
    )


# --- No skill page may name a `model` option on @domain.aggregate ------------
#
# The custom-model option on `@domain.aggregate` is `database_model` (see
# `protean/core/aggregate.py`). An earlier draft of
# `aggregate/references/configuration.md` documented it as `model` and showed
# `@domain.aggregate(model=CustomUserModel)`, which is not a real option: an
# agent copying it gets a TypeError. This sweep reads every markdown page under
# the pack and rejects any that passes a bare `model=` keyword to an
# `@domain.aggregate(...)` call, or gives a `model` option its own heading.

# A heading that documents an option literally named `model`, e.g. "### `model`".
_MODEL_OPTION_HEADING = re.compile(r"(?m)^#+\s*`model`\s*$")

# The Python code fences on a page. Only these can hold a real call.
_PYTHON_FENCE = re.compile(r"```(?:python|py)[^\n]*\n(.*?)```", re.DOTALL)

_OPENING = ("(", "[", "{")
_CLOSING = (")", "]", "}")
_SKIPPED_TOKENS = frozenset(
    {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT}
)


def _model_kwarg_via_ast(code: str) -> bool | None:
    """Whether a fence passes `model=` to `aggregate(...)`, or None if unparsed.

    Reading the parsed call is the only way to answer this that cannot be
    fooled by the text around it. Scanning characters kept getting the same
    class of question wrong: first nested calls, whose `)` ended the scan
    early, then a `)` or a `model=` inside a string literal, which is not
    syntax at all. The parser settles all of them at once.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = (
            function.attr
            if isinstance(function, ast.Attribute)
            else getattr(function, "id", None)
        )
        if name == "aggregate" and any(kw.arg == "model" for kw in node.keywords):
            return True
    return False


def _model_kwarg_via_tokens(code: str) -> bool | None:
    """The same question for a fence the parser rejects, or None if unreadable.

    Pages legitimately ship snippets that do not parse: the pack's are mostly
    indented excerpts lifted out of a class body. The tokenizer still reads
    those, and it knows a string literal from code, so the delimiters it
    reports are real ones.
    """
    try:
        tokens = [
            token
            for token in tokenize.generate_tokens(io.StringIO(code).readline)
            if token.type not in _SKIPPED_TOKENS
        ]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None

    for index, token in enumerate(tokens):
        if token.type != tokenize.NAME or token.string != "aggregate":
            continue
        if index + 1 >= len(tokens) or tokens[index + 1].string != "(":
            continue
        depth = 0
        for offset in range(index + 1, len(tokens)):
            current = tokens[offset]
            if current.string in _OPENING:
                depth += 1
            elif current.string in _CLOSING:
                depth -= 1
                if depth == 0:
                    break
            elif (
                depth == 1
                and current.type == tokenize.NAME
                and current.string == "model"
                and offset + 1 < len(tokens)
                and tokens[offset + 1].string == "="
            ):
                return True
    return False


def _names_a_model_kwarg(code: str) -> bool | None:
    """True when the fence passes `model=` to an `aggregate(...)` call.

    None means neither the parser nor the tokenizer could read the fence, which
    the caller reports rather than skips.
    """
    verdict = _model_kwarg_via_ast(code)
    return _model_kwarg_via_tokens(code) if verdict is None else verdict


def test_the_docs_sweep_is_not_vacuous():
    """A sweep that finds no pages would pass while checking nothing."""
    assert len(DOCS) >= 100, f"expected the pack's markdown pages, found {len(DOCS)}"


def test_no_skill_page_names_a_model_option_on_aggregate():
    offenders = []

    def report(message: str) -> None:
        if message not in offenders:
            offenders.append(message)

    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(SKILLS_ROOT)
        for code in _PYTHON_FENCE.findall(text):
            verdict = _names_a_model_kwarg(code)
            if verdict:
                report(
                    f"{rel}: passes `model=` to @domain.aggregate; the "
                    "custom-model option is `database_model`"
                )
            elif verdict is None and "aggregate(" in code:
                report(
                    f"{rel}: a snippet calling aggregate(...) can be neither "
                    "parsed nor tokenized, so this sweep cannot check it"
                )
        if _MODEL_OPTION_HEADING.search(text):
            report(
                f"{rel}: documents an option named `model`; the custom-model "
                "option is `database_model`"
            )

    assert not offenders, (
        "`@domain.aggregate` has no `model` option (it is `database_model`), so "
        "a page that names one teaches code that raises a TypeError:\n  "
        + "\n  ".join(offenders)
    )


CLASS_BODY = "\nclass User:\n    email = String(required=True, max_length=254)\n"


@pytest.mark.parametrize(
    ("snippet", "names_a_model_kwarg"),
    [
        ("@domain.aggregate(model=CustomUserModel)" + CLASS_BODY, True),
        # A nested call closes a paren before the bad keyword is reached.
        # `add-field/SKILL.md` ships `@domain.aggregate(indexes=[Index("email")])`,
        # so this shape is real.
        (
            '@domain.aggregate(indexes=[Index("email")], model=M)' + CLASS_BODY,
            True,
        ),
        (
            '@domain.aggregate(indexes=[Index("email")], database_model=M)'
            + CLASS_BODY,
            False,
        ),
        # A `)` inside a string literal is not a delimiter.
        ('@domain.aggregate(schema_name="archive)", model=M)' + CLASS_BODY, True),
        # ... and a `model=` inside one is not a keyword.
        ('@domain.aggregate(schema_name="model=x")' + CLASS_BODY, False),
        (
            "@domain.aggregate(\n    provider='sqlite',\n    model=M,\n)" + CLASS_BODY,
            True,
        ),
        ("@domain.aggregate(database_model=CustomUserModel)" + CLASS_BODY, False),
        ('@domain.aggregate(part_of="Order")' + CLASS_BODY, False),
        # `model=` belongs to the nested call, not to the aggregate.
        ("@domain.aggregate(indexes=[Index(model=X)])" + CLASS_BODY, False),
        # An indented excerpt the parser rejects; the tokenizer still reads it.
        ("    @domain.aggregate(model=M)\n    class User:\n        pass\n", True),
        (
            '    @domain.aggregate(schema_name="a)", model=M)\n    class User:\n        pass\n',
            True,
        ),
        (
            "    @domain.aggregate(database_model=M)\n    class User:\n        pass\n",
            False,
        ),
    ],
)
def test_the_model_kwarg_scan_reads_real_syntax(snippet, names_a_model_kwarg):
    assert _names_a_model_kwarg(snippet) is names_a_model_kwarg


def test_the_indented_regression_cases_exercise_the_tokenizer():
    """The indented snippets must be the ones the parser cannot read."""
    indented = "    @domain.aggregate(model=M)\n    class User:\n        pass\n"
    assert _model_kwarg_via_ast(indented) is None
    assert _model_kwarg_via_tokens(indented) is True
