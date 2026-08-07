"""Helpers for Protean's optional runtime dependencies.

Several runtime concerns are install-time optional and live behind extras so a
plain ``pip install protean`` stays lean (see ADR-0029): the web/observatory
stack (``protean[server]``), the interactive shell (``protean[shell]``), and the
project scaffolder (``protean[scaffold]``).

When a feature is used without its extra installed, the code that reaches for
the missing package should fail with a message that names the extra to install,
rather than letting a bare ``ModuleNotFoundError`` surface. This module holds the
single place that builds that message, so the wording stays identical across the
CLI and the FastAPI integration.
"""


def missing_dependency_message(package: str, extra: str, feature: str) -> str:
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
