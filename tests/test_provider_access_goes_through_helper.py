"""Tests read database adapter members only through ``provider_adapter``.

``domain.providers[name]`` is moving from the adapter itself to a provider
service that keeps the adapter behind it. The service has a short list of
members. A test that reads or assigns anything else on the provider (``_engine``,
``_metadata``, ``dao_for`` and the like) needs the adapter, so it takes it from
``tests.shared.provider_adapter``. The helper is then the one line to edit when
the container changes.

A line-oriented grep cannot check this, because most tests bind the provider to a
name first (``provider = test_domain.providers["default"]``) and read members off
the name. This guard parses every module under ``tests/`` and follows those names
within each function, loop and fixture.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_test_domain

TESTS_ROOT = Path(__file__).resolve().parent

# The members the provider service keeps, plus the two ownership flags the
# framework reads today. Anything else lives on the adapter.
ALLOWED = frozenset(
    {
        "name",
        "config",
        "capabilities",
        "raw",
        "ping",
        "health",
        "get_connection",
        "clear",
        "managed",
        "owns",
        "_adapter",
    }
)

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_REFLECTION_BUILTINS = frozenset({"getattr", "setattr", "delattr", "hasattr"})
# ``patch.object``, ``monkeypatch.setattr`` and ``monkeypatch.delattr``.
_REFLECTION_METHODS = frozenset({"object", "setattr", "delattr"})


def _is_container(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "providers"


def is_provider_expr(node: ast.AST | None) -> bool:
    """``<expr>.providers[...]`` or ``<expr>.providers.get(...)``."""
    if isinstance(node, ast.Subscript):
        return _is_container(node.value)
    if isinstance(node, ast.Call):
        func = node.func
        return (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and _is_container(func.value)
        )
    return False


def _is_container_call(node: ast.AST, method: str) -> bool:
    """``<expr>.providers.<method>()``."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == method
        and _is_container(node.func.value)
    )


def _scope_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """Every node in ``scope`` that does not belong to a nested function or lambda."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _assigned_name(node: ast.AST) -> str | None:
    """The name an assignment, walrus or ``with`` binds to a provider, if any."""
    if isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
        target, value = node.target, node.value
    elif isinstance(node, ast.withitem):
        target, value = node.optional_vars, node.context_expr
    else:
        return None
    if isinstance(target, ast.Name) and is_provider_expr(value):
        return target.id
    return None


def _assign_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign) and is_provider_expr(node.value):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    name = _assigned_name(node)
    return [name] if name else []


def _loop_names(node: ast.AST) -> list[str]:
    """The provider a loop or comprehension binds from ``.values()``/``.items()``."""
    if not isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        return []
    target = node.target
    if _is_container_call(node.iter, "values") and isinstance(target, ast.Name):
        return [target.id]
    if (
        _is_container_call(node.iter, "items")
        and isinstance(target, ast.Tuple)
        and len(target.elts) == 2
        and isinstance(target.elts[1], ast.Name)
    ):
        return [target.elts[1].id]
    return []


def _tracked_names(nodes: list[ast.AST]) -> set[str]:
    return {name for node in nodes for name in _assign_names(node) + _loop_names(node)}


def _is_provider_value(node: ast.AST, tracked: set[str]) -> bool:
    if isinstance(node, ast.NamedExpr):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id in tracked
    return is_provider_expr(node)


def _is_reflection(func: ast.AST) -> bool:
    if isinstance(func, ast.Name):
        return func.id in _REFLECTION_BUILTINS
    return isinstance(func, ast.Attribute) and func.attr in _REFLECTION_METHODS


def _reflected_member(call: ast.Call, tracked: set[str]) -> str | None:
    """The member ``getattr(provider, "<member>")`` and its kin name, if disallowed."""
    if not _is_reflection(call.func) or len(call.args) < 2:
        return None
    target, member = call.args[0], call.args[1]
    if not (isinstance(member, ast.Constant) and isinstance(member.value, str)):
        return None
    if member.value in ALLOWED or not _is_provider_value(target, tracked):
        return None
    return member.value


def _flagged_member(node: ast.AST, tracked: set[str]) -> str | None:
    if isinstance(node, ast.Attribute):
        if node.attr not in ALLOWED and _is_provider_value(node.value, tracked):
            return node.attr
        return None
    if isinstance(node, ast.Call):
        return _reflected_member(node, tracked)
    return None


def _is_fixture(func: ast.AST) -> bool:
    if not isinstance(func, _FUNCTIONS):
        return False
    for decorator in func.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name) and target.id == "fixture":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "fixture":
            return True
    return False


def _returns_provider(func: ast.AST) -> bool:
    """A function whose ``return`` or ``yield`` hands back a provider."""
    nodes = list(_scope_nodes(func))
    tracked = _tracked_names(nodes)
    return any(
        isinstance(node, (ast.Return, ast.Yield))
        and node.value is not None
        and _is_provider_value(node.value, tracked)
        for node in nodes
    )


def _fixture_reach(path: Path) -> Path:
    """The file or directory whose tests can request a fixture defined in ``path``."""
    return path.parent if path.name == "conftest.py" else path


def provider_fixtures(modules: dict[Path, ast.Module]) -> dict[str, list[Path]]:
    """Fixtures that hand a test the provider, by name, with where each is visible."""
    fixtures: dict[str, list[Path]] = {}
    for path, tree in modules.items():
        for node in ast.walk(tree):
            if _is_fixture(node) and _returns_provider(node):
                assert isinstance(node, _FUNCTIONS)
                fixtures.setdefault(node.name, []).append(_fixture_reach(path))
    return fixtures


def _requested_fixtures(
    scope: ast.AST, path: Path, fixtures: dict[str, list[Path]]
) -> set[str]:
    """Provider fixtures a test or fixture in ``path`` takes as parameters."""
    if not isinstance(scope, _FUNCTIONS):
        return set()
    if not (scope.name.startswith("test") or _is_fixture(scope)):
        return set()
    params = {arg.arg for arg in scope.args.args + scope.args.kwonlyargs}
    return {
        name
        for name in params & fixtures.keys()
        if any(reach == path or reach in path.parents for reach in fixtures[name])
    }


def _scope_violations(
    scope: ast.AST, path: Path, fixtures: dict[str, list[Path]]
) -> Iterator[tuple[int, str]]:
    nodes = list(_scope_nodes(scope))
    tracked = _tracked_names(nodes) | _requested_fixtures(scope, path, fixtures)
    for node in nodes:
        member = _flagged_member(node, tracked)
        if member is not None:
            yield node.lineno, member  # type: ignore[attr-defined]


def find_violations(modules: dict[Path, str]) -> list[str]:
    """One ``path:line: member`` per adapter member read off the provider."""
    trees = {path: ast.parse(source, str(path)) for path, source in modules.items()}
    fixtures = provider_fixtures(trees)
    found: set[tuple[Path, int, str]] = set()
    for path, tree in trees.items():
        scopes = [tree, *(n for n in ast.walk(tree) if isinstance(n, _SCOPES))]
        for scope in scopes:
            for line, member in _scope_violations(scope, path, fixtures):
                found.add((path, line, member))
    return [f"{path}:{line}: {member}" for path, line, member in sorted(found)]


def _test_modules() -> dict[Path, str]:
    return {
        path.relative_to(TESTS_ROOT.parent): path.read_text(encoding="utf-8")
        for path in sorted(TESTS_ROOT.rglob("*.py"))
    }


def test_tests_read_adapter_members_only_through_the_helper():
    modules = _test_modules()
    # The walk found the test tree, so an empty result means something.
    assert len(modules) > 500

    violations = find_violations(modules)

    assert not violations, (
        "These lines read a database adapter member off the provider. "
        "Take the adapter from tests.shared.provider_adapter instead:\n"
        + "\n".join(violations)
    )


def _check(source: str) -> list[str]:
    return find_violations({Path("tests/example_test.py"): source})


def _members(source: str) -> list[str]:
    return [violation.rsplit(": ", 1)[1] for violation in _check(source)]


@pytest.mark.parametrize(
    "source, member",
    [
        ('def test(d):\n    d.providers["default"]._engine\n', "_engine"),
        ('def test(d):\n    d.providers.get("default").dao_for(X)\n', "dao_for"),
        (
            'def test(d):\n    p = d.providers["default"]\n    p._metadata\n',
            "_metadata",
        ),
        ('def test(d):\n    p: Any = d.providers["x"]\n    p.collation\n', "collation"),
        ('def test(d):\n    (p := d.providers["x"])._databases\n', "_databases"),
        (
            "def test(d):\n    for p in d.providers.values():\n        p.close()\n",
            "close",
        ),
        (
            "def test(d):\n    for n, p in d.providers.items():\n        p.is_alive = 1\n",
            "is_alive",
        ),
        (
            "def test(d):\n    [p._engine for p in d.providers.values()]\n",
            "_engine",
        ),
        ('def test(d):\n    d.providers["default"]._engine = None\n', "_engine"),
        (
            'def test(d):\n    getattr(d.providers["default"], "_engine", None)\n',
            "_engine",
        ),
        (
            'def test(d, mp):\n    p = d.providers["x"]\n    mp.setattr(p, "_engine", 1)\n',
            "_engine",
        ),
        (
            'def test(d):\n    p = d.providers["x"]\n    patch.object(p, "model_for")\n',
            "model_for",
        ),
        ('lambda d: d.providers["default"].dao_for(X)\n', "dao_for"),
        ('p = d.providers["default"]\np._engine\n', "_engine"),
    ],
)
def test_guard_flags_adapter_member(source, member):
    assert _members(source) == [member]


@pytest.mark.parametrize(
    "source",
    [
        'def test(d):\n    d.providers["default"].ping()\n',
        'def test(d):\n    d.providers["default"]._adapter._engine\n',
        'def test(d):\n    p = d.providers["default"]\n    p.health(); p.managed; p.owns\n',
        "def test(d):\n    for p in d.providers.values():\n        p.ping = None\n",
        'def test(d):\n    getattr(d.providers["default"], "capabilities")\n',
        'def test():\n    registry.providers.get("sqlite")(n, d, c).dao_for\n',
        "def test(d):\n    d.providers._providers.items()\n",
        'def test(d):\n    provider_adapter(d, "default")._engine\n',
        "def test(d):\n    for name in d.providers.keys():\n        name.upper()\n",
        # The name is bound in one function and read in another.
        'def a(d):\n    p = d.providers["x"]\n\ndef b(p):\n    p._engine\n',
    ],
)
def test_guard_passes_allowed_access(source):
    assert _check(source) == []


def test_guard_reports_path_line_and_member():
    source = 'def test(d):\n    p = d.providers["default"]\n\n    p._engine\n'

    assert _check(source) == ["tests/example_test.py:4: _engine"]


_FIXTURE = """
import pytest

@pytest.fixture
def provider(test_domain):
    return test_domain.providers["default"]
"""


def test_guard_follows_a_fixture_into_the_tests_that_take_it():
    modules = {
        Path("tests/pkg/conftest.py"): _FIXTURE,
        Path(
            "tests/pkg/sub/test_a.py"
        ): "def test_a(provider):\n    provider._engine\n",
        # Outside the conftest's directory the same name is another fixture.
        Path("tests/other/test_b.py"): "def test_b(provider):\n    provider._engine\n",
        # A plain helper with that parameter name is not given the fixture.
        Path("tests/pkg/test_c.py"): "def helper(provider):\n    provider._engine\n",
    }

    assert find_violations(modules) == ["tests/pkg/sub/test_a.py:2: _engine"]


def test_guard_scopes_a_module_fixture_to_its_module():
    modules = {
        Path("tests/test_a.py"): _FIXTURE + "\ndef test_a(provider):\n    provider.x\n",
        Path("tests/test_b.py"): "def test_b(provider):\n    provider.x\n",
    }

    assert find_violations(modules) == ["tests/test_a.py:9: x"]
