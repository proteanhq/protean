"""Check two field rules across the aggregate, entity, value-object and add-field skills.

1. A money field (a name such as ``price``, ``amount``, ``total``, ``balance``,
   ``subtotal``, ``cost``, ``fee`` or ``*_limit``) declared with ``Float``,
   ``Integer`` or ``Decimal`` is ``Decimal(precision=19, scale=4)``. This holds
   in every block, fragments included: a "wrong" example about something else
   still declares money the right way.
2. A ``Reference`` in runnable code (a block that is not a fragment, or an
   asset) sits on an entity and points to that entity's ``part_of``. A link to
   another aggregate is an ``Identifier`` field. Fragments are skipped because
   the "wrong" examples that show a cross-aggregate ``Reference`` are
   fragments.

The checks read the code with ``ast``; they do not run it.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from protean import dx
from tests.support.snippets import extract_blocks

pytestmark = pytest.mark.no_test_domain

SKILLS_ROOT = Path(str(dx.pack_files())) / dx.SKILLS_DIR
SKILLS = ("aggregate", "entity", "value-object", "add-field")

if not SKILLS_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; this test reads skills by path",
        allow_module_level=True,
    )

_MONEY_NAME = re.compile(
    r"(^|_)(price|amount|total|balance|subtotal|cost|fee|limit)s?($|_)"
)
_NUMBER_FIELDS = {"Float", "Integer", "Decimal"}


def _sources(root: Path) -> Iterator[tuple[str, str, bool]]:
    """Yield ``(location, source, is_fragment)`` for every block and asset."""
    for skill in SKILLS:
        for path in sorted((root / skill).rglob("*")):
            if path.suffix == ".md":
                for block in extract_blocks(path.read_text(encoding="utf-8")):
                    yield f"{path}:{block.line}", block.source, block.fragment
            elif path.suffix == ".py":
                yield f"{path}:1", path.read_text(encoding="utf-8"), False


def _parse(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _declared_fields(tree: ast.Module) -> Iterator[tuple[int, str, ast.Call]]:
    """Yield ``(lineno, name, call)`` for ``name: Field(...)`` and ``name = Field(...)``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.annotation
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name, value = node.targets[0].id, node.value
        else:
            continue
        if isinstance(value, ast.Call):
            yield node.lineno, name, value


def money_problems(root: Path) -> tuple[int, list[str]]:
    """Return the number of money fields seen and the ones not ``Decimal(19, 4)``."""
    seen = 0
    problems = []
    for location, source, _ in _sources(root):
        tree = _parse(source)
        if tree is None:
            continue
        for lineno, name, call in _declared_fields(tree):
            kind = _callee(call)
            if kind not in _NUMBER_FIELDS or not _MONEY_NAME.search(name):
                continue
            seen += 1
            options = {k.arg: ast.unparse(k.value) for k in call.keywords}
            if not (
                kind == "Decimal"
                and options.get("precision") == "19"
                and options.get("scale") == "4"
            ):
                problems.append(
                    f"{location} (+{lineno - 1}): {name}: {ast.unparse(call)}"
                )
    return seen, problems


def _string_or_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    return None


def _decorator_part_of(cls: ast.ClassDef) -> tuple[str | None, str | None]:
    """Return the element kind (``entity``, ``aggregate``, ...) and its ``part_of``."""
    for decorator in cls.decorator_list:
        if isinstance(decorator, ast.Attribute):
            return decorator.attr, None
        if isinstance(decorator, ast.Call) and isinstance(
            decorator.func, ast.Attribute
        ):
            part_of = next(
                (
                    _string_or_name(k.value)
                    for k in decorator.keywords
                    if k.arg == "part_of"
                ),
                None,
            )
            return decorator.func.attr, part_of
    return None, None


def reference_problems(root: Path) -> tuple[int, list[str]]:
    """Return the number of runnable ``Reference`` fields and the misplaced ones."""
    seen = 0
    problems = []
    for location, source, fragment in _sources(root):
        tree = _parse(source)
        if fragment or tree is None:
            continue
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            kind, part_of = _decorator_part_of(cls)
            for node in ast.walk(cls):
                if not (isinstance(node, ast.Call) and _callee(node) == "Reference"):
                    continue
                seen += 1
                target = _string_or_name(node.args[0]) if node.args else None
                if kind != "entity" or target != part_of:
                    problems.append(
                        f"{location} (+{node.lineno - 1}): {kind} {cls.name} "
                        f"(part_of={part_of}) references {target}"
                    )
    return seen, problems


def test_every_money_field_is_a_decimal_with_precision_19_and_scale_4():
    seen, problems = money_problems(SKILLS_ROOT)
    assert seen > 50, (
        f"only {seen} money fields found; the scan is not reading the skills"
    )
    assert problems == []


def test_every_runnable_reference_points_to_the_entitys_own_parent():
    seen, problems = reference_problems(SKILLS_ROOT)
    assert seen > 0, "no Reference fields found; the scan is not reading the skills"
    assert problems == []


def _skill_page(tmp_path: Path, body: str) -> Path:
    page = tmp_path / "aggregate" / "SKILL.md"
    page.parent.mkdir(parents=True)
    page.write_text(f"```python\n{body}\n```\n", encoding="utf-8")
    return tmp_path


def test_a_float_price_is_reported(tmp_path):
    root = _skill_page(tmp_path, "class Order:\n    price: Float()")
    assert money_problems(root) == (
        1,
        [f"{root}/aggregate/SKILL.md:2 (+1): price: Float()"],
    )


def test_a_decimal_without_precision_and_scale_is_reported(tmp_path):
    root = _skill_page(
        tmp_path, "class Order:\n    total_amount = Decimal(min_value=0)"
    )
    seen, problems = money_problems(root)
    assert seen == 1 and len(problems) == 1


def test_a_float_that_is_not_money_is_not_reported(tmp_path):
    root = _skill_page(tmp_path, "class Place:\n    latitude: Float()")
    assert money_problems(root) == (0, [])


def test_a_reference_to_another_aggregate_is_reported(tmp_path):
    root = _skill_page(
        tmp_path,
        '@domain.entity(part_of="Order")\n'
        "class LineItem:\n"
        '    customer = Reference("Customer")',
    )
    seen, problems = reference_problems(root)
    assert seen == 1
    expected = (
        f"{root}/aggregate/SKILL.md:2 (+2): entity LineItem (part_of=Order) "
        "references Customer"
    )
    assert problems == [expected]


def test_a_reference_on_an_aggregate_is_reported(tmp_path):
    root = _skill_page(
        tmp_path, "@domain.aggregate\nclass Order:\n    customer = Reference(Customer)"
    )
    seen, problems = reference_problems(root)
    assert seen == 1 and len(problems) == 1


def test_a_reference_to_the_entitys_parent_is_accepted(tmp_path):
    root = _skill_page(
        tmp_path,
        "@domain.entity(part_of=Order)\nclass LineItem:\n    order = Reference(Order)",
    )
    assert reference_problems(root) == (1, [])


def test_a_fragment_reference_is_skipped(tmp_path):
    root = _skill_page(
        tmp_path,
        "# fragment\n@domain.aggregate\nclass Order:\n    customer = Reference(Customer)",
    )
    assert reference_problems(root) == (0, [])
