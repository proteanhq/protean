"""The shared CLI result envelope, its versioned schema, and the exit-code convention.

A Protean command that emits machine-readable output under ``--json`` (or
``--format json``) wraps its result in one stable envelope::

    {
      "version": "0.1.0",
      "status": "pass" | "fail" | "error",
      "data": { ... command-specific detail ... },
      "diagnostics": [ ... diagnostic records ... ]
    }

so an agent can consume it uniformly. ``status`` is the coarse verdict that maps
to the exit-code class: ``"pass"`` (exit ``0``), ``"fail"`` (a failure the
command is designed to detect), ``"error"`` (a usage or environment error it
could not run past). The fine-grained detail — a command's own status, counts,
or stage tree — lives under ``data``; ``diagnostics`` carries the diagnostic
records (the :mod:`protean.ir.diagnostics` shape, plain dicts at runtime).

``check``, ``verify``, ``events catalog``, ``subscriptions status``, and
``projection status`` emit this envelope today. The other commands that print
``--json``/``--format json`` (``upgrade-check``, ``ir diff``, ``ir check``) are
not yet converged onto it — that is a separate follow-on. Do not read this module
as a claim that they already conform.

The envelope is a guarded contract, not just a shape: it ships a pinned,
versioned JSON Schema at :data:`SCHEMA_PATH`, mirroring the IR precedent at
``src/protean/ir/schema/v0.1.0/schema.json``. Conformance tests assert each
converged command's ``--json`` output validates against it.

The exit-code convention ``check`` and ``verify`` follow (and the shape a new
command should adopt when it converges), with command-specific classes
documented per command:

    0 — success.
    1 — the command ran and reports a failure it is designed to detect (the
        severity/stage detail is in the envelope, not the code).
    2 — a usage or environment error it could not run past (a bad option, no or
        unloadable domain, malformed config, IO). This is Click's own default
        for a bad command line, so untouched commands inherit it for free.
    >=3 — command-specific failure classes, documented per command (``verify``
        pins ``3`` init, ``4`` check, ``5`` tests).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, NoReturn

import typer
from rich.console import Console
from rich.markup import escape

ENVELOPE_VERSION = "0.1.0"

_CLI_DIR = Path(__file__).parent
SCHEMA_PATH = _CLI_DIR / "schema" / f"v{ENVELOPE_VERSION}" / "envelope.schema.json"

# The CLI-wide exit-code convention (see the module docstring). The
# command-specific classes (``verify``'s 3/4/5) are named in that command.
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

# The envelope's coarse verdict — the exit-code class, not the fine-grained
# severity (which lives under ``data``).
EnvelopeStatus = Literal["pass", "fail", "error"]

# Usage/environment errors write to stderr so ``--json`` keeps stdout to the
# envelope alone.
_ERR_CONSOLE = Console(stderr=True)


def emit_usage_error(*, as_json: bool, message: str) -> NoReturn:
    """Emit a usage/environment error and exit :data:`EXIT_USAGE` with clean stdout.

    Under ``--json`` the error is the shared envelope (``status="error"``, the
    message under ``data.error``) on stdout and nothing else, so a ``| jq`` stays
    parseable; otherwise a red line goes to stderr. ``escape`` keeps a bracketed
    token in the message (``[lint]``) from being parsed as rich markup and
    dropped. Shared by every command that emits the envelope.
    """
    if as_json:
        typer.echo(
            json.dumps(
                build_envelope(status="error", data={"error": message}, diagnostics=[]),
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _ERR_CONSOLE.print(f"[red]{escape(message)}[/red]")
    raise typer.Exit(code=EXIT_USAGE)


def route_logs_to_stderr(log_already_configured: bool = False) -> None:
    """Route all Protean logging to stderr, before the domain is imported.

    A command that emits a machine payload on stdout must call this first. Until
    :func:`protean.utils.logging.configure_logging` runs, ``structlog`` is at its
    unconfigured default, which prints to **stdout** — so any log line a domain
    module emits *at import time* (which ``derive_domain`` triggers) would land on
    stdout and corrupt the envelope (the #1010 leak, generalized). Configuring
    logging up front installs the stderr console handler and switches structlog
    onto the stdlib bridge, so every subsequent log (import-time or during
    ``check``/``init``) goes to stderr and stdout stays the sole envelope.

    ``Domain.init`` also auto-configures logging, but only after the import has
    already happened; it then sees the root handler this installed and skips,
    so calling both is safe and idempotent.

    ``log_already_configured`` is a no-op guard: pass ``True`` when the CLI's
    ``--log-config``/``--log-level``/``--log-format`` callback already
    configured logging (the caller reads this off the ``CTX_LOG_CONFIGURED``
    flag on ``ctx.obj``) — ``configure_logging()`` unconditionally rebuilds
    the root logger's handlers, so calling it again here would silently
    discard that configuration, the same guard ``server`` and ``observatory``
    apply.
    """
    if log_already_configured:
        return
    # Local import: keep ``protean --help`` from eagerly pulling in the
    # logging subsystem for commands that never emit a machine payload.
    from protean.utils.logging import configure_logging  # noqa: PLC0415

    configure_logging()


def load_envelope_schema() -> dict[str, Any]:
    """Load and return the CLI result-envelope JSON Schema as a Python dict."""
    # json.loads is untyped (returns Any); annotate the local to hold the
    # declared return type.
    schema: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return schema


def build_envelope(
    *,
    status: EnvelopeStatus,
    data: dict[str, Any],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build one result envelope from a command's status, detail, and diagnostics.

    ``status`` is the coarse verdict (``"pass"``/``"fail"``/``"error"``);
    ``data`` is the command's own detail; ``diagnostics`` is the diagnostic list
    (empty when the command has none). The returned dict carries exactly the four
    contract keys and validates against :data:`SCHEMA_PATH`. The caller's
    ``diagnostics`` *list* is copied (shallow) so appending to or clearing it
    does not reach into the envelope; the diagnostic dicts and ``data`` are stored
    by reference. Every caller serializes the envelope immediately, so the shared
    references are never mutated in practice.
    """
    return {
        "version": ENVELOPE_VERSION,
        "status": status,
        "data": data,
        "diagnostics": list(diagnostics),
    }
