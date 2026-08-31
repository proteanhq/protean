"""Helpers for Protean's optional runtime dependencies.

Several runtime concerns are install-time optional and live behind extras so a
plain ``pip install protean`` stays lean (see ADR-0029): the web/observatory
stack (``protean[server]``), the interactive shell (``protean[shell]``), the
project scaffolder (``protean[scaffold]``), and the agent-facing MCP server
(``protean[mcp]``).

When a feature is used without its extra installed, the code that reaches for
the missing package should fail with a message that names the extra to install,
rather than letting a bare ``ModuleNotFoundError`` surface. This module holds the
single place that builds that message, so the wording stays identical across the
CLI and the FastAPI integration.
"""

from typing import Literal

FeatureExtra = Literal["server", "shell", "scaffold", "mcp"]

# Each optional feature extra and the top-level import packages it provides. This
# is the single source of truth for the "which extra is missing" checks: the CLI
# abort helper and the FastAPI integration both derive their guard from it, so an
# extra's package set is defined in exactly one place. Casing matches what
# ``ImportError.name`` reports (e.g. ``IPython``, not ``ipython``).
FEATURE_EXTRA_MODULES: dict[FeatureExtra, tuple[str, ...]] = {
    "server": ("fastapi", "uvicorn", "jinja2"),
    "shell": ("IPython",),
    "scaffold": ("copier",),
    "mcp": ("mcp",),
}


def missing_dependency_message(package: str, extra: FeatureExtra, feature: str) -> str:
    """Build the standard actionable message for an absent optional dependency.

    ``feature`` names what the caller was trying to do (e.g. ``"'protean new'"``
    or ``"'protean observatory'"``); ``package`` is the import that failed;
    ``extra`` is the install extra that provides it. The phrasing matches the
    existing ``--reload``/watchfiles hint so every "install the extra" message
    reads the same way.
    """
    return (
        f"{feature} requires the '{package}' package. "
        f"Install it with 'pip install \"protean[{extra}]\"'."
    )
