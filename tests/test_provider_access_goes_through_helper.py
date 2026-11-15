"""Tests read database adapter members only through ``provider_adapter``.

``domain.providers[name]`` is moving from the adapter itself to a provider
service that keeps the adapter behind it. The service has a short list of
members. A test that reads or assigns anything else on the provider (``_engine``,
``_metadata``, ``dao_for`` and the like) needs the adapter, so it takes it from
``tests.shared.provider_adapter``. The helper is then the one line to edit when
the container changes.

A line-oriented grep cannot check this, because most tests bind the provider to a
name first (``provider = test_domain.providers["default"]``) and read members off
the name. This guard parses every module under ``tests/`` and follows a provider
bound to a name by assignment (tuple unpacking and aliases included), walrus,
``with ... as`` or a loop over ``.values()``/``.items()``, into the functions and
lambdas nested in that scope, and from a fixture into the tests and fixtures that
take it. A provider handed to a call is flagged too, because the callee may read an
adapter member the guard cannot see. It does not follow an alias of the container
itself (``providers = domain.providers``).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_test_domain

TESTS_ROOT = Path(__file__).resolve().parent

# The members the provider service keeps, plus ``managed`` and ``owns``, which the
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
# Calls that may take the provider itself, because they read no member off it.
_SAFE_CALLEES = frozenset({"isinstance", "type", "id", "provider_adapter"})


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


def _bound_pairs(node: ast.AST) -> list[tuple[ast.AST, ast.AST]]:
    """The ``(target, value)`` pairs an assignment, walrus or ``with`` binds."""
    if isinstance(node, ast.Assign):
        return [(target, node.value) for target in node.targets]
    if isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
        return [(node.target, node.value)]
    if isinstance(node, ast.withitem) and node.optional_vars is not None:
        return [(node.optional_vars, node.context_expr)]
    return []


def _pair_names(target: ast.AST, value: ast.AST, tracked: set[str]) -> list[str]:
    """Names in ``target`` that ``value`` binds to a provider, unpacking tuples."""
    if isinstance(target, ast.Name):
        return [target.id] if _is_provider_value(value, tracked) else []
    if (
        isinstance(target, (ast.Tuple, ast.List))
        and isinstance(value, (ast.Tuple, ast.List))
        and len(target.elts) == len(value.elts)
    ):
        return [
            name
            for sub_target, sub_value in zip(target.elts, value.elts, strict=True)
            for name in _pair_names(sub_target, sub_value, tracked)
        ]
    return []


def _assign_names(node: ast.AST, tracked: set[str]) -> list[str]:
    return [
        name
        for target, value in _bound_pairs(node)
        for name in _pair_names(target, value, tracked)
    ]


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


def _tracked_names(nodes: list[ast.AST], inherited: set[str]) -> set[str]:
    """Names bound to a provider in ``nodes``, on top of ``inherited``.

    Repeats until nothing new is found, so ``q = p`` tracks ``q`` once ``p`` is.
    """
    tracked = set(inherited)
    while True:
        found = tracked | {
            name
            for node in nodes
            for name in _assign_names(node, tracked) + _loop_names(node)
        }
        if found == tracked:
            return tracked
        tracked = found


def _params(scope: ast.AST) -> set[str]:
    if not isinstance(scope, _SCOPES):
        return set()
    args = scope.args
    every = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
    return {arg.arg for arg in every if arg is not None}


def _local_names(scope: ast.AST, nodes: list[ast.AST]) -> set[str]:
    """Names ``scope`` binds itself, which hide the same name from an outer scope."""
    stored = {
        node.id
        for node in nodes
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    return stored | _params(scope)


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


def _callee_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return "<call>"


def _passed_provider(call: ast.Call, tracked: set[str]) -> str | None:
    """``passed to <callee>`` when a call takes the provider as an argument."""
    callee = _callee_name(call.func)
    if callee in _SAFE_CALLEES or _is_reflection(call.func):
        return None
    arguments = [*call.args, *(keyword.value for keyword in call.keywords)]
    if any(_is_provider_value(argument, tracked) for argument in arguments):
        return f"passed to {callee}"
    return None


def _flagged_member(node: ast.AST, tracked: set[str]) -> str | None:
    if isinstance(node, ast.Attribute):
        if node.attr not in ALLOWED and _is_provider_value(node.value, tracked):
            return node.attr
        return None
    if isinstance(node, ast.Call):
        return _reflected_member(node, tracked) or _passed_provider(node, tracked)
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


def _fixture_name(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """The name a test requests the fixture by: ``name=`` if given, else the function's."""
    for decorator in func.decorator_list:
        if isinstance(decorator, ast.Call):
            for keyword in decorator.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    return str(keyword.value.value)
    return func.name


def _returns_provider(func: ast.AST) -> bool:
    """A function whose ``return`` or ``yield`` hands back a provider."""
    nodes = list(_scope_nodes(func))
    tracked = _tracked_names(nodes, set())
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
                fixtures.setdefault(_fixture_name(node), []).append(
                    _fixture_reach(path)
                )
    return fixtures


def _requested_fixtures(
    scope: ast.AST, path: Path, fixtures: dict[str, list[Path]]
) -> set[str]:
    """Provider fixtures a test or fixture in ``path`` takes as parameters."""
    if not isinstance(scope, _FUNCTIONS):
        return set()
    if not (scope.name.startswith("test") or _is_fixture(scope)):
        return set()
    return {
        name
        for name in _params(scope) & fixtures.keys()
        if any(reach == path or reach in path.parents for reach in fixtures[name])
    }


def _module_violations(
    tree: ast.Module, path: Path, fixtures: dict[str, list[Path]]
) -> Iterator[tuple[int, str]]:
    # Each scope starts from the names its enclosing scope tracks, less the ones it
    # binds itself, so a closure that reads an outer provider is still checked.
    pending: list[tuple[ast.AST, set[str]]] = [(tree, set())]
    while pending:
        scope, outer = pending.pop()
        nodes = list(_scope_nodes(scope))
        inherited = (outer - _local_names(scope, nodes)) | _requested_fixtures(
            scope, path, fixtures
        )
        tracked = _tracked_names(nodes, inherited)
        for node in nodes:
            member = _flagged_member(node, tracked)
            if member is not None:
                yield node.lineno, member  # type: ignore[attr-defined]
        pending.extend(
            (nested, tracked) for nested in nodes if isinstance(nested, _SCOPES)
        )


def find_violations(modules: dict[Path, str]) -> list[str]:
    """One ``path:line: member`` per adapter member read off the provider.

    ``member`` is ``passed to <callee>`` when a call takes the provider itself.
    """
    trees = {path: ast.parse(source, str(path)) for path, source in modules.items()}
    fixtures = provider_fixtures(trees)
    found = {
        (path, line, member)
        for path, tree in trees.items()
        for line, member in _module_violations(tree, path, fixtures)
    }
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
        ('setattr(d.providers["x"], "_engine", 1)\n', "_engine"),
        ('delattr(d.providers["x"], "_engine")\n', "_engine"),
        ('hasattr(d.providers["x"], "_engine")\n', "_engine"),
        ('mp.delattr(d.providers["x"], "_engine")\n', "_engine"),
        ('with d.providers["x"] as p:\n    p._engine\n', "_engine"),
        ('a, p = 1, d.providers["x"]\np._engine\n', "_engine"),
        ('p = d.providers["x"]\nq = p\nq._engine\n', "_engine"),
        # A closure reads the provider its enclosing function bound.
        (
            'def test(d):\n    p = d.providers["x"]\n    def f():\n        p._engine\n',
            "_engine",
        ),
        (
            'def test(d):\n    p = d.providers["x"]\n    f = lambda: p._engine\n',
            "_engine",
        ),
        ('p = d.providers["x"]\ndef test():\n    p._engine\n', "_engine"),
        # A callee the guard cannot see into may read an adapter member.
        ('p = d.providers["x"]\ncolumn_type(p, "t")\n', "passed to column_type"),
        ('helper(provider=d.providers["x"])\n', "passed to helper"),
        ('self.check(d.providers["x"])\n', "passed to check"),
        ('(lambda p: p)(d.providers["x"])\n', "passed to <call>"),
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
        # A nested function that binds the name itself hides the outer provider.
        'def a(d):\n    p = d.providers["x"]\n    def b(p):\n        p._engine\n',
        'def a(d):\n    p = d.providers["x"]\n    def b():\n        p = o\n        p._engine\n',
        'isinstance(d.providers["x"], X); type(d.providers["x"]); id(d.providers["x"])\n',
        'p = d.providers["x"]\nprovider_adapter(d, "x")._engine; isinstance(p, X)\n',
        'getattr(d.providers["x"], member)\n',
        'getattr(d.providers["x"])\n',
        "for a, b, c in d.providers.items():\n    c._engine\n",
        'a, p = d.providers["x"], 1, 2\np._engine\n',
    ],
)
def test_guard_passes_allowed_access(source):
    assert _check(source) == []


def test_guard_reports_path_line_and_member():
    source = 'def test(d):\n    p = d.providers["default"]\n\n    p._engine\n'

    assert _check(source) == ["tests/example_test.py:4: _engine"]


def test_guard_sorts_violations_and_reports_each_once():
    modules = {
        Path("tests/b.py"): 'p = d.providers["x"]\np._metadata\np._engine; p._engine\n',
        Path("tests/a.py"): 'd.providers["x"].close()\n',
    }

    assert find_violations(modules) == [
        "tests/a.py:1: close",
        "tests/b.py:2: _metadata",
        "tests/b.py:3: _engine",
    ]


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


@pytest.mark.parametrize(
    "fixture, test",
    [
        (
            '@fixture\ndef provider(d):\n    return d.providers["x"]\n',
            "def test_a(provider):\n    provider._engine\n",
        ),
        (
            '@pytest.fixture(scope="module")\ndef provider(d):\n    return d.providers["x"]\n',
            "def test_a(provider):\n    provider._engine\n",
        ),
        (
            '@pytest.fixture\ndef provider(d):\n    yield d.providers["x"]\n',
            "def test_a(provider):\n    provider._engine\n",
        ),
        (
            '@pytest.fixture\ndef provider(d):\n    p = d.providers["x"]\n    yield p\n',
            "def test_a(provider):\n    provider._engine\n",
        ),
        (
            '@pytest.fixture\ndef provider(d):\n    p = d.providers["x"]\n    return p\n',
            "def test_a(*, provider):\n    provider._engine\n",
        ),
        (
            '@pytest.fixture\ndef provider(d):\n    return d.providers["x"]\n',
            "def test_a(provider, /):\n    provider._engine\n",
        ),
        (
            '@pytest.fixture(name="pv")\ndef _pv(d):\n    return d.providers["x"]\n',
            "def test_a(pv):\n    pv._engine\n",
        ),
        # One fixture takes another and reads the adapter off it.
        (
            '@pytest.fixture\ndef provider(d):\n    return d.providers["x"]\n',
            "@pytest.fixture\ndef engine(provider): return provider._engine\n",
        ),
    ],
)
def test_guard_follows_each_fixture_form(fixture, test):
    modules = {
        Path("tests/conftest.py"): fixture,
        Path("tests/test_a.py"): test,
    }

    assert find_violations(modules) == ["tests/test_a.py:2: _engine"]


@pytest.mark.parametrize(
    "fixture",
    [
        # Not a fixture, so a test parameter of that name is something else.
        'def provider(d):\n    return d.providers["x"]\n',
        '@other\ndef provider(d):\n    return d.providers["x"]\n',
        "@pytest.fixture\ndef provider(d):\n    return d\n",
        "@pytest.fixture\ndef provider(d):\n    yield\n",
    ],
)
def test_guard_ignores_a_parameter_no_provider_fixture_supplies(fixture):
    modules = {
        Path("tests/conftest.py"): fixture,
        Path("tests/test_a.py"): "def test_a(provider):\n    provider._engine\n",
    }

    assert find_violations(modules) == []


def test_guard_scopes_a_module_fixture_to_its_module():
    modules = {
        Path("tests/test_a.py"): _FIXTURE + "\ndef test_a(provider):\n    provider.x\n",
        Path("tests/test_b.py"): "def test_b(provider):\n    provider.x\n",
    }

    assert find_violations(modules) == ["tests/test_a.py:9: x"]
