"""Generator for the project ``AGENTS.md`` negative-constraint pack.

Renders one hard rule for every error-level diagnostic code in
:data:`protean.ir.diagnostics.REGISTRY`. Each rule is a prohibition: Protean
raises an error when the rule is broken, so an agent working on a Protean
project must not write code that breaks it. The rule text is built only from
the registry's ``meaning``, ``rationale``, and ``fix`` fields, never from
hand-authored per-code prose, so the file stays correct as the registry
evolves.

The output is deterministic by construction: a fixed header stamped with the
Protean version, then the error-level codes sorted by code name, each rendered
from static registry fields. It reads no timestamp and no IR, so generating
twice for the same version yields byte-identical output.

Usage::

    from protean.ir.generators.agents import generate_agents_md

    md = generate_agents_md(version="0.18.0")
"""

from __future__ import annotations

from protean.ir.diagnostics import REGISTRY, CodeMeta, DiagnosticCode

_SUMMARY = (
    "Hard rules for writing code in a Protean project. Protean raises an error "
    "when a rule below is broken, so do not write code that breaks one. Each "
    "rule ends with the diagnostic code Protean reports, in parentheses."
)


def _constraint_line(code: DiagnosticCode, meta: CodeMeta) -> str:
    """Render one error-level code as a single negative-constraint bullet.

    The text derives only from the code's registry fields: ``meaning`` states
    the error condition, ``rationale`` says why it is an error, and ``fix`` says
    how to comply. The code is kept as an anchor so a reader can trace the rule
    back to the registry.
    """
    return (
        f"- **Do not** write code that causes this error: {meta.meaning} "
        f"{meta.rationale} To comply: {meta.fix} (`{code.value}`)"
    )


def generate_agents_md(*, version: str) -> str:
    """Build the ``AGENTS.md`` negative-constraint pack for *version*.

    Filters :data:`REGISTRY` to the error-level codes, sorts them by code name
    for stability, and renders each as one "do not" constraint built from the
    code's ``meaning``/``rationale``/``fix``. Advisory (``warning``/``info``)
    codes are excluded: only an error-level code is a hard rule.

    The output is deterministic: the header is fixed and version-stamped, the
    single registry traversal is sorted, and nothing here reads a timestamp or
    the IR, so generating twice for the same *version* yields byte-identical
    output.

    Args:
        version: The Protean version string to stamp into the header.

    Returns:
        The ``AGENTS.md`` content as a single string.
    """
    error_codes = sorted(
        (code for code, meta in REGISTRY.items() if meta.level == "error"),
        key=lambda code: code.value,
    )
    lines: list[str] = [
        f"# Protean {version}",
        "",
        f"> {_SUMMARY}",
        "",
        "## Do not break these rules",
        "",
    ]
    lines.extend(_constraint_line(code, REGISTRY[code]) for code in error_codes)
    return "\n".join(lines) + "\n"
