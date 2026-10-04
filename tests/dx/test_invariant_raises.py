"""Every invariant the DX pack shows raises the dict form of ``ValidationError``.

Protean catches only ``ValidationError`` from an ``@invariant.pre`` or
``@invariant.post`` method, reads its messages as a dict, and attaches a
diagnostic code to the error it raises (``INVARIANT_PRE_FAILED`` or
``INVARIANT_POST_FAILED`` on an aggregate or entity). A ``ValueError`` or a
custom exception carries no code. A plain-string ``ValidationError("...")``
fails with a ``TypeError``.

The snippet runner in ``test_skill_snippets.py`` cannot see a bad raise: a block
that only defines an invariant never fires it. So this test reads the code
instead. It parses every fenced ``python`` block in every Markdown file of the
pack, fragments included, and every ``skills/*/assets/*.py``, and fails on any
``raise`` inside an invariant method that is not ``ValidationError({...})``. A
block that does not parse and holds an invariant with a ``raise`` fails too, so
a syntax slip cannot hide a bad raise.

The second half loads the aggregate skill's invariant asset, makes each kind of
invariant fail, and checks the code the framework attaches.
"""

from __future__ import annotations

import ast
import runpy
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.domain import Domain
from protean.exceptions import ValidationError

from .test_skill_snippets import extract_blocks

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
SKILLS_ROOT = PACK_ROOT / dx.SKILLS_DIR
INVARIANT_ASSET = SKILLS_ROOT / "aggregate" / "assets" / "aggregate_with_invariants.py"
VALUE_OBJECT_ASSET = (
    SKILLS_ROOT / "value-object" / "assets" / "value_object_with_invariants.py"
)

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the invariant scan reads files by path",
        allow_module_level=True,
    )


def _is_invariant_decorator(decorator: ast.expr) -> bool:
    """``@invariant``, ``@invariant.pre``, ``@invariant.post``, or a call of one."""
    if isinstance(decorator, ast.Call):
        decorator = decorator.func
    if isinstance(decorator, ast.Name):
        return decorator.id == "invariant"
    return (
        isinstance(decorator, ast.Attribute)
        and isinstance(decorator.value, ast.Name)
        and decorator.value.id == "invariant"
        and decorator.attr in ("pre", "post")
    )


def _is_dict_form(node: ast.Raise) -> bool:
    """``ValidationError({...})`` with at least one key, each mapped to a list.

    An empty dict makes the invariant pass silently, and a string value is read
    as a list of single characters, so both count as bad raises.
    """
    exc = node.exc
    if not (
        isinstance(exc, ast.Call)
        and isinstance(exc.func, ast.Name)
        and exc.func.id == "ValidationError"
        and exc.args
        and isinstance(exc.args[0], ast.Dict)
    ):
        return False
    messages = exc.args[0]
    return bool(messages.values) and all(
        isinstance(value, ast.List) for value in messages.values
    )


def _parse(source: str) -> tuple[ast.Module, int]:
    """Parse a block, and return the tree and the line offset to subtract.

    A block may hold indented methods with no class around them, sometimes after
    an unindented ``# fragment`` line. When the dedented block does not parse, it
    is parsed again inside a ``class`` header, which shifts it down one line.
    """
    dedented = textwrap.dedent(source)
    try:
        return ast.parse(dedented), 0
    except SyntaxError:
        wrapped = "class _Fragment:\n" + textwrap.indent(dedented, "    ")
        return ast.parse(wrapped), 1


def scan(source: str) -> tuple[int, list[tuple[int, str]]]:
    """Return the number of invariant methods and the bad raises in ``source``.

    Each bad raise is ``(line, code)``, with ``line`` counted from 1 within
    ``source``. A source that does not parse but holds ``@invariant`` and a
    ``raise`` is reported as one bad raise on line 1. Raises SyntaxError for a
    source that does not parse and holds no invariant raise.
    """
    try:
        tree, offset = _parse(source)
    except SyntaxError:
        if "@invariant" in source and "raise" in source:
            return 0, [(1, "block does not parse; cannot check its invariants")]
        raise
    methods = 0
    bad: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_is_invariant_decorator(d) for d in node.decorator_list):
            continue
        methods += 1
        bad.extend(
            (inner.lineno - offset, ast.unparse(inner))
            for inner in ast.walk(node)
            if isinstance(inner, ast.Raise) and not _is_dict_form(inner)
        )
    return methods, bad


def _sources() -> Iterator[tuple[str, int, str]]:
    """Yield ``(label, first line, source)`` for every block and asset."""
    for path in sorted(PACK_ROOT.rglob("*.md")):
        label = path.relative_to(PACK_ROOT).as_posix()
        for block in extract_blocks(path.read_text(encoding="utf-8")):
            yield label, block.line, block.source
    for path in sorted(SKILLS_ROOT.glob("*/assets/*.py")):
        yield path.relative_to(PACK_ROOT).as_posix(), 1, path.read_text("utf-8")


def test_every_invariant_in_the_pack_raises_the_dict_form():
    methods = 0
    parsed = 0
    problems = []
    for label, first_line, source in _sources():
        try:
            found, bad = scan(source)
        except SyntaxError:
            continue
        parsed += 1
        methods += found
        problems.extend(
            f"{label}:{first_line + line - 1}: {code}" for line, code in bad
        )

    # A scan that reads nothing passes; these floors make that fail instead.
    assert parsed >= 1300, f"parsed only {parsed} blocks and assets"
    assert methods >= 140, f"found only {methods} invariant methods"
    assert problems == [], (
        "invariants must raise ValidationError({'<field>': ['<message>']}):\n"
        + "\n".join(problems)
    )


# --- The scan on synthetic sources --------------------------------------------


def _method(decorator: str, body: str) -> str:
    return (
        f"class Account:\n    {decorator}\n    def rule(self):\n"
        f"        if self.balance < 0:\n            {body}\n"
    )


def test_a_dict_form_raise_passes():
    source = _method(
        "@invariant.post", 'raise ValidationError({"balance": ["Below zero"]})'
    )
    assert scan(source) == (1, [])


@pytest.mark.parametrize(
    "body",
    [
        'raise ValueError("Below zero")',
        'raise InsufficientFunds("Below zero")',
        'raise ValidationError("Below zero")',
        "raise ValidationError(...)",
        "raise ValidationError({})",
        'raise ValidationError({"balance": "Below zero"})',
        "raise ValidationError",
        "raise",
    ],
)
def test_a_raise_that_is_not_the_dict_form_fails(body):
    methods, bad = scan(_method("@invariant.post", body))
    assert methods == 1
    assert bad == [(5, ast.unparse(ast.parse(body.strip())))]


@pytest.mark.parametrize(
    "decorator",
    ["@invariant.pre", "@invariant.post", '@invariant.post(code="X")', "@invariant"],
)
def test_every_decorator_spelling_is_scanned(decorator):
    methods, bad = scan(_method(decorator, 'raise ValueError("x")'))
    assert methods == 1
    assert len(bad) == 1


def test_a_value_error_in_an_ordinary_method_passes():
    source = (
        "class Account:\n    def withdraw(self, amount):\n"
        "        if amount <= 0:\n"
        '            raise ValueError("Amount must be positive")\n'
    )
    assert scan(source) == (0, [])


def test_a_string_raise_in_a_field_validator_passes():
    source = (
        "class PhoneValidator:\n    def __call__(self, value):\n"
        "        if not value.isdigit():\n"
        '            raise ValidationError("Phone must be digits")\n'
    )
    assert scan(source) == (0, [])


def test_an_indented_method_after_a_fragment_marker_is_scanned():
    source = (
        "# fragment\n    @invariant.post\n    def rule(self):\n"
        '        raise ValueError("x")\n'
    )
    assert scan(source) == (1, [(4, "raise ValueError('x')")])


def test_an_unparseable_block_with_an_invariant_raise_fails():
    source = "@invariant.post\ndef rule(self):\n    if (:\n        raise ValueError()\n"
    assert scan(source) == (
        0,
        [(1, "block does not parse; cannot check its invariants")],
    )


def test_an_unparseable_block_without_an_invariant_is_skipped():
    with pytest.raises(SyntaxError):
        scan("def broken(:\n")


# --- The aggregate skill's invariant asset fails with the right code ----------


def _load(path: Path) -> Iterator[dict[str, Any]]:
    namespace = runpy.run_path(str(path), run_name="_dx_invariant_asset")
    domains = [value for value in namespace.values() if isinstance(value, Domain)]
    assert len(domains) == 1
    domain = domains[0]
    domain.init(traverse=False)
    with domain.domain_context():
        yield namespace


@pytest.fixture
def asset() -> Iterator[dict[str, Any]]:
    yield from _load(INVARIANT_ASSET)


@pytest.fixture
def value_object_asset() -> Iterator[dict[str, Any]]:
    yield from _load(VALUE_OBJECT_ASSET)


def test_a_failing_post_invariant_carries_invariant_post_failed(asset):
    account = asset["Account"](
        account_number="ACC-1", balance=100.0, overdraft_limit=50.0
    )
    with pytest.raises(ValidationError) as exc:
        account.withdraw(200.0)

    assert "INVARIANT_POST_FAILED" in exc.value.codes
    assert dict(exc.value.messages) == {
        "_entity": ["Balance -100.0 cannot be below overdraft limit -50.0"]
    }


def test_a_failing_pre_invariant_carries_invariant_pre_failed(asset):
    account = asset["Account"](account_number="ACC-1", balance=100.0)
    account.status = "frozen"
    with pytest.raises(ValidationError) as exc:
        account.deposit(10.0)

    assert "INVARIANT_PRE_FAILED" in exc.value.codes
    assert dict(exc.value.messages) == {
        "status": ["Cannot perform transactions on frozen account"]
    }


def test_construction_with_failing_values_carries_the_code(asset):
    with pytest.raises(ValidationError) as exc:
        asset["Warehouse"](
            name="Main", current_stock=10.0, reserved_stock=20.0, max_capacity=100.0
        )

    assert "INVARIANT_POST_FAILED" in exc.value.codes
    assert dict(exc.value.messages) == {
        "_entity": ["Reserved stock 20.0 exceeds current stock 10.0"]
    }


def test_a_failing_value_object_invariant_carries_its_own_code(value_object_asset):
    with pytest.raises(ValidationError) as exc:
        value_object_asset["Balance"](currency="USD", amount=-5.0)

    assert exc.value.codes == ["VALUE_OBJECT_INVARIANT_FAILED"]
    assert dict(exc.value.messages) == {
        "balance": ["Balance cannot be negative for USD"]
    }
