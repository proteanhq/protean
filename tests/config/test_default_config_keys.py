"""Every top-level config key the framework reads is in ``_default_config()``.

``Config2._normalize_config`` keeps only the top-level keys listed in
``_default_config()`` and drops the rest without a warning. A key read by the
framework but missing from the defaults cannot be set at the top level of
``domain.toml``, ``pyproject.toml`` or a ``config=`` dict. This test parses each
module in ``src/protean`` and checks the key of every read on a domain's config
against the defaults.

A read is ``<config>["key"]`` or ``<config>.get("key", ...)`` with a string
literal key. ``<config>`` is ``<receiver>.config``, or a local name bound to
one earlier in the same function, such as ``cfg = self._domain.config``. The
receiver is ``domain``, ``derived_domain``, ``current_domain``, any attribute
named ``domain`` or ``_domain``, and ``self`` inside the domain package. A
bare ``config`` that no assignment binds is often a nested section
(``telemetry``, a subscription config), whose keys are not top-level, so the
scan skips it. Docstrings and comments hold no reads.
"""

import ast
from collections.abc import Iterator
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

_Function = ast.FunctionDef | ast.AsyncFunctionDef


def _is_domain(node: ast.expr, in_domain_package: bool) -> bool:
    """Return whether ``node`` is an expression for a domain."""
    if isinstance(node, ast.Name):
        if node.id == "self":
            return in_domain_package
        return node.id in _DOMAIN_NAMES
    return isinstance(node, ast.Attribute) and node.attr in _DOMAIN_ATTRIBUTES


def _is_domain_config(node: ast.expr, in_domain_package: bool) -> bool:
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


def _read(node: ast.AST) -> tuple[ast.expr, str] | None:
    """Return the config expression and key of a read, or ``None``."""
    if isinstance(node, ast.Subscript):
        key = _string(node.slice)
        return (node.value, key) if key is not None else None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
    ):
        key = _string(node.args[0])
        return (node.func.value, key) if key is not None else None
    return None


def _scope_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """Yield the nodes under ``node`` in source order, stopping at nested functions."""
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, _Function):
            yield from _scope_nodes(child)


def _bind(node: ast.AST, aliases: set[str], in_domain_package: bool) -> None:
    """Record or end an alias when ``node`` assigns a single name."""
    if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
        return
    target = node.targets[0]
    if not isinstance(target, ast.Name):
        return
    # A rebinding to anything else ends the alias.
    if _is_domain_config(node.value, in_domain_package):
        aliases.add(target.id)
    else:
        aliases.discard(target.id)


def _scope_reads(scope: ast.AST, in_domain_package: bool) -> Iterator[tuple[int, str]]:
    """Yield ``(line, key)`` for each read in one function or module scope.

    Aliases bound in the scope are visible only inside it, so a parameter
    named ``config`` in another function is not taken for the domain's config.
    """
    aliases: set[str] = set()
    for node in _scope_nodes(scope):
        _bind(node, aliases, in_domain_package)
        read = _read(node)
        if read is None:
            continue
        config, key = read
        if isinstance(config, ast.Name):
            is_config = config.id in aliases
        else:
            is_config = _is_domain_config(config, in_domain_package)
        if is_config:
            yield node.lineno, key


def _file_reads(path: Path) -> list[tuple[int, str]]:
    """Return ``(line, key)`` for each read in the module at ``path``, by line."""
    tree = ast.parse(path.read_text(), filename=str(path))
    in_domain_package = path.is_relative_to(_DOMAIN_PACKAGE)
    scopes = [tree, *(n for n in ast.walk(tree) if isinstance(n, _Function))]
    return sorted(
        read for scope in scopes for read in _scope_reads(scope, in_domain_package)
    )


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
    # branch of the scan.
    assert {"lint", "observatory", "databases", "snapshot_threshold"} <= found.keys()
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
