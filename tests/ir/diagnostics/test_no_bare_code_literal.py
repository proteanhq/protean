"""No diagnostic-code string literal may live outside ``ir/diagnostics.py``.

The code registry is the single place a code string is written. Every producer
references a :class:`DiagnosticCode` member instead. This source-scan enforces
that: if any ``.py`` under ``protean`` (other than the registry itself) contains
a bare string literal equal to a known code, this test fails and names the file
and line, so a new rule that hard-codes ``"UNHANDLED_EVENT"`` is caught in
review rather than drifting from the registry.

Modelled on ``tests/ir/test_deprecation_coverage_audit.py``'s AST-scan
precedent.
"""

import ast
from pathlib import Path

import protean
from protean.ir.diagnostics import DiagnosticCode

# The registry module is where the code strings are DEFINED; it is exempt.
REGISTRY_MODULE = "ir/diagnostics.py"


def _code_values() -> set[str]:
    return {code.value for code in DiagnosticCode}


def find_bare_code_literals(source: str, codes: set[str]) -> list[tuple[int, str]]:
    """Return ``(lineno, code)`` for every string literal in ``source`` whose
    value is exactly one of ``codes``.

    Membership is exact, so a docstring or comment that merely mentions a code
    inside a longer sentence never matches — only a literal that IS the code,
    which is how a code is spelled at a producer site (``"code": "..."`` /
    ``check_code="..."``).
    """
    tree = ast.parse(source)
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in codes
    ]


def _src_root() -> Path:
    return Path(protean.__file__).parent


def test_no_source_file_hardcodes_a_diagnostic_code():
    codes = _code_values()
    root = _src_root()
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel == REGISTRY_MODULE:
            continue
        for lineno, code in find_bare_code_literals(
            path.read_text(encoding="utf-8"), codes
        ):
            offenders.append(f"{rel}:{lineno} -> {code!r}")
    assert not offenders, (
        "Diagnostic-code string literals found outside the registry; reference "
        "DiagnosticCode.<NAME> instead:\n" + "\n".join(offenders)
    )


def test_scanner_flags_a_planted_bare_literal():
    # The matcher must actually catch a bare code, not just pass because the
    # tree happens to be clean.
    codes = _code_values()
    planted = 'diagnostic = {"code": "UNHANDLED_EVENT", "level": "warning"}\n'
    hits = find_bare_code_literals(planted, codes)
    assert hits == [(1, "UNHANDLED_EVENT")]


def test_scanner_ignores_a_mention_inside_prose():
    # A docstring/message that names a code inside a longer string is not a bare
    # code literal and must not be flagged.
    codes = _code_values()
    prose = '"""This mirrors the UNHANDLED_EVENT diagnostic for reference."""\n'
    assert find_bare_code_literals(prose, codes) == []
