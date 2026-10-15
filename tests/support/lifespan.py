"""Check that a FastAPI lifespan recipe closes its domain on shutdown.

A lifespan with a bare ``yield`` leaves the provider, broker, cache and event
store connections open when the app stops. Each ``yield`` must sit inside a
``try`` whose ``finally`` calls ``.close()``.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence


def _closes_in_finally(node: ast.Try) -> bool:
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "close"
        for stmt in node.finalbody
        for call in ast.walk(stmt)
    )


def _yields_in(body: Sequence[ast.AST], closed: bool) -> list[tuple[int, bool]]:
    found: list[tuple[int, bool]] = []
    for stmt in body:
        found.extend(_yields_under(stmt, closed))
    return found


def _yields_under(node: ast.AST, closed: bool) -> list[tuple[int, bool]]:
    if isinstance(node, ast.Yield):
        return [(node.lineno, closed)]
    if isinstance(node, ast.Try):
        inner = closed or _closes_in_finally(node)
        return (
            _yields_in(node.body, inner)
            + _yields_in(node.handlers, closed)
            + _yields_in(node.orelse, inner)
            + _yields_in(node.finalbody, closed)
        )
    found: list[tuple[int, bool]] = []
    for child in ast.iter_child_nodes(node):
        found.extend(_yields_under(child, closed))
    return found


def lifespan_yields(source: str) -> list[tuple[int, bool]]:
    """Return ``(line, closed)`` for each ``yield`` in an ``async def lifespan``.

    ``closed`` is true when the ``yield`` sits in the body of a ``try`` whose
    ``finally`` calls ``.close()``.
    """
    found: list[tuple[int, bool]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan":
            found.extend(_yields_in(node.body, closed=False))
    return found
