"""Every top-level config key the framework reads is in ``_default_config()``.

``Config2._normalize_config`` keeps only the top-level keys listed in
``_default_config()`` and drops the rest without a warning. A key read by the
framework but missing from the defaults cannot be set at the top level of
``domain.toml``, ``pyproject.toml`` or a ``config=`` dict. This test parses each
module in ``src/protean`` and checks the key of every read on a domain's config
against the defaults.

A read is ``<config>["key"]`` or ``<config>.get("key", ...)`` with a string
literal key. ``<config>`` is ``<receiver>.config``, or a name bound to one by
an earlier assignment, such as ``cfg = self._domain.config`` or
``cfg: Config = domain.config``. The receiver is ``domain``,
``derived_domain``, ``current_domain``, any attribute named ``domain`` or
``_domain``, and ``self`` inside the domain package.

A bound name follows Python's scopes. A function or lambda sees the names
bound in the scopes around it before its definition, unless it binds the same
name itself, for example as a parameter. A comprehension sees the names bound
before it, and its first iterable is read in the scope around it. A class
body's bindings stay in the class body. Another binding of the name, such as a
``for`` target, ``with ... as``, ``except ... as``, an import, ``del`` or a
``match`` capture, ends it. The scan does not follow branches: it reads the
arms of an ``if`` in source order, so the last binding of a name in the source
wins.

A bare ``config`` that no assignment binds is often a nested section
(``telemetry``, a subscription config), whose keys are not top-level, so the
scan skips it. Docstrings and comments hold no reads.
"""

import ast
from collections.abc import Iterable, Iterator
from pathlib import Path

import protean
from protean.domain.config import _default_config

_SRC = Path(protean.__file__).parent

# User-facing skill examples, not framework code.
_EXCLUDED = _SRC / "dx" / "pack"

# A bare ``self.config`` is the domain's config only inside the domain package.
# Elsewhere it is the object's own section, such as a database provider's
# ``databases.<name>`` entry, whose keys are not top-level.
_DOMAIN_PACKAGE = _SRC / "domain"

_DOMAIN_NAMES = frozenset({"domain", "derived_domain", "current_domain"})
_DOMAIN_ATTRIBUTES = frozenset({"domain", "_domain"})

_Function = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
_Comprehension = ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
_Binding = ast.Assign | ast.AnnAssign | ast.AugAssign | ast.NamedExpr
_AliasBinding = ast.Assign | ast.AnnAssign | ast.NamedExpr


def _is_domain(node: ast.expr, in_domain_package: bool) -> bool:
    """Return whether ``node`` is an expression for a domain."""
    if isinstance(node, ast.Name):
        if node.id == "self":
            return in_domain_package
        return node.id in _DOMAIN_NAMES
    return isinstance(node, ast.Attribute) and node.attr in _DOMAIN_ATTRIBUTES


def _is_domain_config(node: ast.expr | None, in_domain_package: bool) -> bool:
    """Return whether ``node`` is ``<domain>.config``."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "config"
        and _is_domain(node.value, in_domain_package)
    )


def _string(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _read(node: ast.AST) -> tuple[ast.expr, str, int] | None:
    """Return the config expression, key and line of a read, or ``None``."""
    if isinstance(node, ast.Subscript):
        key = _string(node.slice)
        return (node.value, key, node.lineno) if key is not None else None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
    ):
        key = _string(node.args[0])
        return (node.func.value, key, node.lineno) if key is not None else None
    return None


def _targets(node: _AliasBinding) -> list[ast.expr]:
    return node.targets if isinstance(node, ast.Assign) else [node.target]


def _children(node: ast.AST) -> list[ast.AST]:
    """Return the children of ``node`` in the order Python evaluates them.

    The value of an assignment and the iterable of a ``for`` loop run before
    their targets are bound, so ``cfg = cfg["section"]`` reads the alias first.
    """
    if isinstance(node, ast.AnnAssign) and node.value is None:
        # ``cfg: dict`` with no value binds nothing, so the alias stays live.
        if isinstance(node.target, ast.Name):
            return [node.annotation]
        return [node.target, node.annotation]
    if isinstance(node, _Binding) and node.value is not None:
        rest = [c for c in ast.iter_child_nodes(node) if c is not node.value]
        return [node.value, *rest]
    if isinstance(node, ast.For | ast.AsyncFor):
        return [node.iter, node.target, *node.body, *node.orelse]
    return list(ast.iter_child_nodes(node))


def _bound_names(node: ast.AST) -> set[str]:
    """Return the names ``node`` itself binds in its scope."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
        return {node.id}
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return {node.name}
    if isinstance(node, ast.alias):
        return {node.asname or node.name.split(".")[0]}
    if isinstance(node, ast.ExceptHandler) and node.name:
        return {node.name}
    if isinstance(node, ast.MatchAs | ast.MatchStar) and node.name:
        return {node.name}
    if isinstance(node, ast.MatchMapping) and node.rest:
        return {node.rest}
    return set()


def _scope_walk(nodes: Iterable[ast.AST]) -> Iterator[ast.AST]:
    """Yield ``nodes`` and the nodes under them, stopping at nested scopes."""
    for node in nodes:
        yield node
        if not isinstance(node, _Function | _Comprehension | ast.ClassDef):
            yield from _scope_walk(ast.iter_child_nodes(node))


def _local_names(node: _Function) -> set[str]:
    """Return the parameters of ``node`` and the names its body binds."""
    args = node.args
    params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    params += [a for a in (args.vararg, args.kwarg) if a is not None]
    body = node.body if isinstance(node.body, list) else [node.body]
    bound = {name for n in _scope_walk(body) for name in _bound_names(n)}
    return {a.arg for a in params} | bound


class _Reads:
    """Collect the reads of a domain's config in one module."""

    def __init__(self, in_domain_package: bool) -> None:
        self.in_domain_package = in_domain_package
        self.found: list[tuple[int, str]] = []

    def scope(
        self, nodes: Iterable[ast.AST], aliases: set[str], enclosing: set[str]
    ) -> None:
        """Walk ``nodes`` with ``aliases`` live.

        ``enclosing`` is the alias set a nested function starts from. It is
        ``aliases`` itself, except in a class body, whose bindings a method
        does not see.
        """
        for node in nodes:
            if isinstance(node, _Function):
                self.function(node, aliases, enclosing)
            elif isinstance(node, ast.ClassDef):
                self.class_body(node, aliases)
            elif isinstance(node, _Comprehension):
                self.comprehension(node, aliases, enclosing)
            elif isinstance(node, ast.ExceptHandler):
                self.handler(node, aliases, enclosing)
            elif isinstance(node, ast.Call):
                # The receiver of ``cfg.get`` is fixed before the arguments
                # run, so an argument that rebinds ``cfg`` does not change it.
                self.scope([node.func], aliases, enclosing)
                self.check(node, aliases)
                self.scope([*node.args, *node.keywords], aliases, enclosing)
            else:
                self.scope(_children(node), aliases, enclosing)
                self.check(node, aliases)
                self.bind(node, aliases)

    def function(self, node: _Function, aliases: set[str], enclosing: set[str]) -> None:
        # Decorators and defaults run in the enclosing scope, when the
        # function is defined.
        args = node.args
        outer = [*args.defaults, *(d for d in args.kw_defaults if d is not None)]
        if not isinstance(node, ast.Lambda):
            outer = [*node.decorator_list, *outer]
        self.scope(outer, aliases, enclosing)
        inner = enclosing - _local_names(node)
        body = node.body if isinstance(node.body, list) else [node.body]
        self.scope(body, inner, inner)
        if not isinstance(node, ast.Lambda):
            aliases.discard(node.name)

    def class_body(self, node: ast.ClassDef, aliases: set[str]) -> None:
        self.scope(
            [*node.decorator_list, *node.bases, *node.keywords], aliases, aliases
        )
        self.scope(node.body, set(aliases), aliases)
        aliases.discard(node.name)

    def handler(
        self, node: ast.ExceptHandler, aliases: set[str], enclosing: set[str]
    ) -> None:
        if node.type is not None:
            self.scope([node.type], aliases, enclosing)
        # ``except ... as cfg`` binds ``cfg`` before the body and deletes it
        # after.
        aliases.discard(node.name or "")
        self.scope(node.body, aliases, enclosing)
        aliases.discard(node.name or "")

    def comprehension(
        self, node: _Comprehension, aliases: set[str], enclosing: set[str]
    ) -> None:
        first, *generators = node.generators
        # Python evaluates the first iterable in the enclosing scope, before
        # the comprehension binds its targets.
        self.scope([first.iter], aliases, enclosing)
        targets = {
            n.id
            for g in node.generators
            for n in ast.walk(g.target)
            if isinstance(n, ast.Name)
        }
        inner = aliases - targets
        results = [
            c
            for c in ast.iter_child_nodes(node)
            if not isinstance(c, ast.comprehension)
        ]
        self.scope([first.target, *first.ifs, *generators, *results], inner, inner)

    def check(self, node: ast.AST, aliases: set[str]) -> None:
        read = _read(node)
        if read is None:
            return
        config, key, lineno = read
        if isinstance(config, ast.Name):
            is_config = config.id in aliases
        else:
            is_config = _is_domain_config(config, self.in_domain_package)
        if is_config:
            self.found.append((lineno, key))

    def bind(self, node: ast.AST, aliases: set[str]) -> None:
        """Record an alias, or end one when ``node`` binds its name to anything else."""
        if isinstance(node, _AliasBinding) and _is_domain_config(
            node.value, self.in_domain_package
        ):
            aliases.update(t.id for t in _targets(node) if isinstance(t, ast.Name))
        else:
            aliases.difference_update(_bound_names(node))


def _file_reads(path: Path) -> list[tuple[int, str]]:
    """Return ``(line, key)`` for each read in the module at ``path``, by line."""
    # Bytes let ``ast`` honour a BOM and a coding header.
    tree = ast.parse(path.read_bytes(), filename=str(path))
    reads = _Reads(path.is_relative_to(_DOMAIN_PACKAGE))
    aliases: set[str] = set()
    reads.scope(tree.body, aliases, aliases)
    return sorted(reads.found)


def _scan() -> dict[str, list[str]]:
    """Map each top-level key read in the framework to its ``file:line`` sites."""
    found: dict[str, list[str]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        if path.is_relative_to(_EXCLUDED):
            continue
        for lineno, key in _file_reads(path):
            site = f"{path.relative_to(_SRC.parent)}:{lineno}"
            found.setdefault(key, []).append(site)
    return found


def test_scan_finds_known_reads():
    found = _scan()

    # ``snapshot_threshold`` is read only by subscript, so it pins the ``[``
    # branch of the scan. ``source_uri`` is read only through
    # ``current_domain.config``, so it pins that receiver.
    assert {
        "lint",
        "observatory",
        "databases",
        "snapshot_threshold",
        "source_uri",
    } <= found.keys()
    # ``sqlalchemy.py`` reads ``identity_strategy`` only through a local alias
    # (``config = provider.domain.config``), so it pins the alias branch.
    assert any(
        site.startswith("protean/adapters/database/sqlalchemy.py:")
        for site in found["identity_strategy"]
    )


def test_every_read_key_is_a_default_key():
    defaults = _default_config().keys()

    missing = {key: sites for key, sites in _scan().items() if key not in defaults}

    assert not missing, "Top-level config keys read but missing from " + (
        "_default_config(), so the loader drops them: "
        + "; ".join(f"{key!r} at {', '.join(sites)}" for key, sites in missing.items())
    )


def test_scan_finds_a_read_wrapped_across_lines(tmp_path, monkeypatch):
    module = tmp_path / "wrapped.py"
    module.write_text('value = domain.config.get(\n    "wrapped_key", {}\n)\n')
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"wrapped_key": [f"{tmp_path.name}/wrapped.py:1"]}


def test_scan_reads_self_config_inside_the_domain_package(tmp_path, monkeypatch):
    domain_package = tmp_path / "domain"
    domain_package.mkdir()
    (domain_package / "__init__.py").write_text('flag = self.config.get("lint")\n')
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)
    monkeypatch.setattr(f"{__name__}._DOMAIN_PACKAGE", domain_package)

    assert _scan() == {"lint": [f"{tmp_path.name}/domain/__init__.py:1"]}


def test_scan_skips_self_config_outside_the_domain_package(tmp_path, monkeypatch):
    (tmp_path / "domain").mkdir()
    (tmp_path / "provider.py").write_text('uri = self.config["database_uri"]\n')
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)
    monkeypatch.setattr(f"{__name__}._DOMAIN_PACKAGE", tmp_path / "domain")

    assert _scan() == {}


def test_scan_finds_a_read_through_a_local_alias(tmp_path, monkeypatch):
    (tmp_path / "alias.py").write_text(
        'def build():\n    cfg = domain.config\n    return cfg["alias_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"alias_key": [f"{tmp_path.name}/alias.py:3"]}


def test_scan_finds_a_get_read_through_an_attribute_alias(tmp_path, monkeypatch):
    (tmp_path / "alias.py").write_text(
        "def build(self):\n"
        "    cfg = self._domain.config\n"
        '    return cfg.get("alias_get_key", {})\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"alias_get_key": [f"{tmp_path.name}/alias.py:3"]}


def test_scan_skips_an_unbound_bare_config(tmp_path, monkeypatch):
    (tmp_path / "section.py").write_text('value = config.get("section_key")\n')
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {}


def test_scan_skips_an_alias_after_it_is_rebound(tmp_path, monkeypatch):
    (tmp_path / "rebound.py").write_text(
        "def build(section):\n"
        "    cfg = domain.config\n"
        "    cfg = section\n"
        '    return cfg["section_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {}


def test_scan_skips_docstrings_and_comments(tmp_path, monkeypatch):
    (tmp_path / "prose.py").write_text(
        '"""Read with ``domain.config.get("doc_key")``."""\n'
        '# value = domain.config["comment_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {}


def test_scan_scopes_aliases_per_function(tmp_path, monkeypatch):
    (tmp_path / "scopes.py").write_text(
        "def validate(provider):\n"
        "    config = provider.domain.config\n"
        '    return config["identity_type"]\n'
        "\n"
        "def resolve(config):\n"
        '    return config["section_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"identity_type": [f"{tmp_path.name}/scopes.py:3"]}


def test_scan_skips_a_self_config_alias_outside_the_domain_package(
    tmp_path, monkeypatch
):
    (tmp_path / "domain").mkdir()
    (tmp_path / "provider.py").write_text(
        'def connect(self):\n    cfg = self.config\n    return cfg["database_uri"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)
    monkeypatch.setattr(f"{__name__}._DOMAIN_PACKAGE", tmp_path / "domain")

    assert _scan() == {}


def test_scan_reads_an_alias_on_the_right_of_its_own_rebinding(tmp_path, monkeypatch):
    (tmp_path / "narrow.py").write_text(
        "def build():\n"
        "    cfg = domain.config\n"
        '    cfg = cfg["databases"]\n'
        '    return cfg.get("default")\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"databases": [f"{tmp_path.name}/narrow.py:3"]}


def test_scan_finds_a_read_through_an_annotated_alias(tmp_path, monkeypatch):
    (tmp_path / "annotated.py").write_text(
        "def build(self):\n"
        "    cfg: dict = self._domain.config\n"
        '    return cfg["annotated_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"annotated_key": [f"{tmp_path.name}/annotated.py:3"]}


def test_scan_reads_current_and_derived_domain_config(tmp_path, monkeypatch):
    (tmp_path / "receivers.py").write_text(
        'a = current_domain.config["current_key"]\n'
        'b = derived_domain.config.get("derived_key")\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {
        "current_key": [f"{tmp_path.name}/receivers.py:1"],
        "derived_key": [f"{tmp_path.name}/receivers.py:2"],
    }


def test_scan_ends_an_alias_at_a_for_or_with_target(tmp_path, monkeypatch):
    (tmp_path / "targets.py").write_text(
        "def loop(sections):\n"
        "    cfg = domain.config\n"
        "    for cfg in sections:\n"
        '        cfg["for_key"]\n'
        "\n"
        "def open_it(section):\n"
        "    cfg = domain.config\n"
        "    with section as cfg:\n"
        '        cfg["with_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {}


def test_scan_skips_a_comprehension_or_lambda_that_rebinds_the_alias(
    tmp_path, monkeypatch
):
    (tmp_path / "inner.py").write_text(
        "def build(sections):\n"
        "    cfg = domain.config\n"
        '    names = [cfg["comp_key"] for cfg in sections]\n'
        '    pick = lambda cfg: cfg["lambda_key"]\n'
        '    return cfg["outer_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"outer_key": [f"{tmp_path.name}/inner.py:5"]}


def test_scan_keeps_an_alias_through_an_annotation_without_a_value(
    tmp_path, monkeypatch
):
    (tmp_path / "declared.py").write_text(
        "def build():\n"
        "    cfg = domain.config\n"
        "    cfg: dict\n"
        '    return cfg["annotated_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"annotated_key": [f"{tmp_path.name}/declared.py:4"]}


def test_scan_ends_an_alias_at_an_except_target(tmp_path, monkeypatch):
    (tmp_path / "handler.py").write_text(
        "def build():\n"
        "    cfg = domain.config\n"
        "    try:\n"
        "        pass\n"
        "    except KeyError as cfg:\n"
        '        cfg["handler_key"]\n'
        '    return cfg["after_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {}


def test_scan_classifies_a_get_receiver_before_its_arguments(tmp_path, monkeypatch):
    (tmp_path / "walrus.py").write_text(
        'def build():\n    cfg = domain.config\n    return cfg.get("get_key", (cfg := {}))\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"get_key": [f"{tmp_path.name}/walrus.py:3"]}


def test_scan_reads_a_comprehension_first_iterable_in_the_enclosing_scope(
    tmp_path, monkeypatch
):
    (tmp_path / "iterable.py").write_text(
        "def build():\n"
        "    cfg = domain.config\n"
        '    return [cfg["section_key"] for cfg in cfg["alias_key"]]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"alias_key": [f"{tmp_path.name}/iterable.py:3"]}


def test_scan_keeps_class_body_aliases_in_the_class(tmp_path, monkeypatch):
    (tmp_path / "klass.py").write_text(
        "def outer(cfg):\n"
        "    class K:\n"
        "        cfg = domain.config\n"
        '        inside = cfg["inside_key"]\n'
        "\n"
        "        def method(self):\n"
        '            return cfg["method_key"]\n'
        '    return cfg["outside_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"inside_key": [f"{tmp_path.name}/klass.py:4"]}


def test_scan_follows_an_alias_into_nested_functions(tmp_path, monkeypatch):
    (tmp_path / "closure.py").write_text(
        "def outer():\n"
        "    cfg = domain.config\n"
        "\n"
        '    @register(cfg["decorator_key"])\n'
        '    def inner(flag=cfg.get("default_key")):\n'
        '        return cfg["closure_key"]\n'
        "\n"
        "    def shadow(cfg):\n"
        '        return cfg["param_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {
        "decorator_key": [f"{tmp_path.name}/closure.py:4"],
        "default_key": [f"{tmp_path.name}/closure.py:5"],
        "closure_key": [f"{tmp_path.name}/closure.py:6"],
    }


def test_scan_lists_sites_by_line(tmp_path, monkeypatch):
    # ``ast`` puts the test of a conditional expression before its body, so the
    # read on line 3 is walked before the one on line 2.
    (tmp_path / "order.py").write_text(
        "value = (\n"
        '    domain.config["k"]\n'
        '    if domain.config["k"]\n'
        "    else None\n"
        ")\n"
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {
        "k": [f"{tmp_path.name}/order.py:2", f"{tmp_path.name}/order.py:3"]
    }


def test_scan_reads_a_module_with_a_byte_order_mark(tmp_path, monkeypatch):
    (tmp_path / "bom.py").write_bytes(b'\xef\xbb\xbfvalue = domain.config["bom_key"]\n')
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"bom_key": [f"{tmp_path.name}/bom.py:1"]}


def test_scan_ends_an_alias_at_an_import_or_del(tmp_path, monkeypatch):
    (tmp_path / "unbind.py").write_text(
        "def imported():\n"
        "    cfg = domain.config\n"
        "    import cfg\n"
        '    cfg["import_key"]\n'
        "\n"
        "def deleted():\n"
        "    cfg = domain.config\n"
        "    del cfg\n"
        '    cfg["del_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {}


def test_scan_ends_an_alias_at_a_match_capture(tmp_path, monkeypatch):
    (tmp_path / "capture.py").write_text(
        "def pick(value):\n"
        "    cfg = domain.config\n"
        "    match value:\n"
        "        case cfg:\n"
        '            cfg["as_key"]\n'
        "\n"
        "def star(value):\n"
        "    cfg = domain.config\n"
        "    match value:\n"
        "        case [*cfg]:\n"
        '            cfg["star_key"]\n'
        "\n"
        "def rest(value):\n"
        "    cfg = domain.config\n"
        "    match value:\n"
        "        case {**cfg}:\n"
        '            cfg["rest_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {}


def test_scan_keeps_the_last_binding_across_if_arms(tmp_path, monkeypatch):
    (tmp_path / "arms.py").write_text(
        "def build(flag, section):\n"
        "    if flag:\n"
        "        cfg = section\n"
        "    else:\n"
        "        cfg = domain.config\n"
        '    return cfg["arm_key"]\n'
    )
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"arm_key": [f"{tmp_path.name}/arms.py:6"]}
