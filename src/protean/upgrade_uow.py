"""Source-level upgrade checks for the ADR-0027 transaction change.

A Unit of Work is now one real database transaction. Two shapes that were
harmless under the old AUTOCOMMIT model are not any more, and neither shows up
in a diff of the user's own code, because the user's code did not change:

- **A nested Unit of Work joins the outermost transaction.** There are no
  savepoints, so an inner rollback dooms the whole transaction where it used to
  be contained.
- **External I/O inside a Unit of Work holds database locks** for the length of
  the call. Under AUTOCOMMIT no transaction was open, so a call out cost only
  wall-clock time.

Both are found by reading the domain's source rather than its configuration,
which is what separates these from the checks in :mod:`protean.upgrade`. They
are advisory: the output is a list of places to look.

The I/O rule is deliberately import-driven rather than name-driven. Matching
bare verb names would flag ``repository_for(Order).get(id)``, which is the most
common call there is inside a Unit of Work, and a check that fires on correct
code is one people learn to ignore.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from protean.ir.analysis.source_provider import SourceProvider

if TYPE_CHECKING:
    from protean.domain import Domain

# Libraries whose use inside a transaction is what this rule is looking for.
_HTTP_MODULES = frozenset({"httpx", "requests", "urllib", "urllib3", "aiohttp"})

# HTTP verbs, only ever matched against a receiver already known to be an HTTP
# client (see `_http_names`), never on their own.
_HTTP_VERBS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "request", "send"}
)

# Names distinctive enough to flag wherever they appear. `publish` is the broker
# API; the rest are unambiguous by construction.
_UNAMBIGUOUS_IO = frozenset(
    {"publish", "send_email", "sendmail", "send_message", "urlopen"}
)


def _is_unit_of_work(node: ast.expr) -> bool:
    """Is this the ``UnitOfWork()`` / ``protean.UnitOfWork()`` call shape?"""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "UnitOfWork"
    if isinstance(func, ast.Attribute):
        return func.attr == "UnitOfWork"
    return False


def _uow_withs(tree: ast.Module) -> list[ast.With | ast.AsyncWith]:
    """Every ``with UnitOfWork():`` block in a module."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.With | ast.AsyncWith)
        and any(_is_unit_of_work(item.context_expr) for item in node.items)
    ]


def _root_name(node: ast.expr) -> str | None:
    """The leftmost plain name of an attribute chain, if there is one.

    ``httpx.post`` gives ``"httpx"``; ``self._client.post`` gives ``"self._client"``
    so an instance attribute can be tracked; ``f().get`` gives ``None``, since
    there is no name to reason about.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = _root_name(node.value)
        return f"{inner}.{node.attr}" if inner else None
    return None


def _http_names(tree: ast.Module) -> set[str]:
    """Names in this module that refer to an HTTP client.

    Seeded from imports, then extended through assignment, so a dispatcher that
    does ``self._client = httpx.Client()`` in its constructor and
    ``self._client.post(...)`` later is matched on the second line.
    """
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _HTTP_MODULES:
                    names.add(alias.asname or alias.name.split(".")[0])
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[0] in _HTTP_MODULES
        ):
            for alias in node.names:
                names.add(alias.asname or alias.name)

    if not names:
        return names

    # Propagate through assignment until it settles: `s = requests.Session()`,
    # then `self._c = s`, then `self._c.post(...)`.
    for _ in range(3):
        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            source = node.value
            origin = (
                _root_name(source.func) if isinstance(source, ast.Call) else None
            ) or _root_name(source)
            if origin is None:
                continue
            if not any(origin == n or origin.startswith(f"{n}.") for n in names):
                continue
            for target in node.targets:
                bound = _root_name(target)
                if bound and bound not in names:
                    names.add(bound)
                    grew = True
        if not grew:
            break

    return names


def _external_io_in(block: ast.AST, http_names: set[str]) -> list[tuple[str, int]]:
    """External-I/O calls lexically inside *block*.

    A nested ``UnitOfWork`` is not descended into: its calls belong to that
    block's own report.
    """
    found: list[tuple[str, int]] = []

    def visit(node: ast.AST) -> None:
        # Only children are inspected, and *block* is never its own child, so a
        # nested Unit of Work is always skipped here without skipping the block
        # we were asked about.
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.With | ast.AsyncWith) and any(
                _is_unit_of_work(i.context_expr) for i in child.items
            ):
                continue
            if isinstance(child, ast.Call):
                label = _io_label(child, http_names)
                if label:
                    found.append((label, child.lineno))
            visit(child)

    visit(block)
    return found


def _io_label(node: ast.Call, http_names: set[str]) -> str | None:
    """Describe *node* if it is external I/O, else ``None``."""
    func = node.func
    if isinstance(func, ast.Attribute):
        receiver = _root_name(func.value)
        if (
            func.attr in _HTTP_VERBS
            and receiver
            and any(receiver == n or receiver.startswith(f"{n}.") for n in http_names)
        ):
            return f"{receiver}.{func.attr}()"
        if func.attr in _UNAMBIGUOUS_IO:
            return f"{func.attr}()"
    elif isinstance(func, ast.Name):
        if func.id in _UNAMBIGUOUS_IO:
            return f"{func.id}()"
        if func.id in http_names:
            return f"{func.id}()"
    return None


def _lexically_nested(tree: ast.Module) -> list[int]:
    """Line numbers of ``UnitOfWork`` blocks opened inside another one."""
    nested: list[int] = []
    for block in _uow_withs(tree):
        for node in ast.walk(block):
            if node is block:
                continue
            if isinstance(node, ast.With | ast.AsyncWith) and any(
                _is_unit_of_work(i.context_expr) for i in node.items
            ):
                nested.append(node.lineno)
    return nested


def scan_domain_source(domain: Domain) -> tuple[list[str], list[str], int]:
    """Walk a domain's source for the two ADR-0027 hazards.

    Returns ``(nested_sites, io_sites, total_uow_blocks)``. Reporting is the
    caller's job, which keeps this module free of any dependency on the
    diagnostics layer that consumes it.
    """
    provider = SourceProvider(domain)
    nested: list[str] = []
    io: list[str] = []
    total = 0

    for module_name, tree in provider.iter_trees():
        blocks = _uow_withs(tree)
        if not blocks:
            continue
        total += len(blocks)
        nested.extend(f"{module_name}:{line}" for line in _lexically_nested(tree))
        http_names = _http_names(tree)
        for block in blocks:
            io.extend(
                f"{module_name}:{line} ({label})"
                for label, line in _external_io_in(block, http_names)
            )

    return nested, io, total
