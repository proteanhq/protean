"""The framework operations the MCP server exposes, as plain functions.

Each function answers from the installed framework: ``validate``/``check`` run
[`Domain.check`][protean.domain.Domain.check], ``introspect`` runs
[`Domain.to_ir`][protean.domain.Domain.to_ir], ``explain`` reads the diagnostics
[`REGISTRY`][protean.ir.diagnostics.REGISTRY], and ``scaffold`` drives the
scaffold core ([`plan_add_slice`][protean.scaffold.add_plan.plan_add_slice] then
[`render_preview`][protean.scaffold.preview.render_preview] and optionally
[`apply_plan`][protean.scaffold.apply.apply_plan]).

The module imports no MCP SDK, so it is importable and unit-testable without the
``mcp`` extra. :mod:`protean.mcp.server` wraps these functions as MCP tools.

Domain resolution mirrors the CLI: read tools auto-discover the domain from the
process working directory (the ``"."`` default `protean check` uses) and accept
an optional ``domain`` path to override it. A caller-facing failure (a domain
that will not load, a bad input) raises :exc:`McpToolError` with a clear message;
:mod:`protean.mcp.server` translates it into an MCP ``ToolError`` the caller sees
as an error result.
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING, Any, TypedDict

from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain

if TYPE_CHECKING:
    from protean.domain import Domain


class McpToolError(Exception):
    """A tool could not complete: the domain would not load, an input was
    invalid, or an operation failed. The server surfaces the message to the
    caller as an error tool result.

    Deliberately a plain ``Exception`` rather than a ``ProteanException``: it is a
    boundary-translation marker, and :mod:`protean.mcp.server` keys its
    "safe to show the caller" translation off exactly this class, so it must not
    be caught by any framework-wide ``ProteanException`` handler on the way out.
    """


def _resolve_path(value: str | None, kind: str) -> str:
    """Resolve a location argument to the working directory only when it is unset.

    ``None`` means "not provided", so it falls back to the ``"."`` default
    ``protean check`` uses. An explicit empty or blank string is a caller error,
    not "use the working directory": treating it as the default would silently
    discover (or write into) the wrong place, so it is rejected instead.
    """
    if value is None:
        return "."
    if not value.strip():
        raise McpToolError(f"The {kind} path must not be empty.")
    return value


class ValidateResult(TypedDict):
    """The ``validate`` tool's result: a go/no-go verdict over a domain."""

    domain: str
    valid: bool
    status: str
    errors: list[dict[str, Any]]
    counts: dict[str, int]


class ExplainResult(TypedDict):
    """The ``explain`` tool's result: one diagnostic code's registry metadata.

    ``resolution`` is the wire form of the command that clears the diagnostic
    (``command``/``args``/``display``), or ``None`` when no command clears it.
    """

    code: str
    category: str
    level: str
    meaning: str
    rationale: str
    fix: str
    kind: str
    resolution: dict[str, Any] | None


def _derive(domain: str | None) -> Domain:
    """Discover a domain for the read-only checks that do not need ``init()``.

    [`Domain.check`][protean.domain.Domain.check] prepares the domain itself, so
    ``check``/``validate`` skip ``init()`` the same way ``protean check`` does.
    """
    path = _resolve_path(domain, "domain")
    try:
        derived = derive_domain(path)
    except NoDomainException as exc:
        raise McpToolError(f"Error loading Protean domain: {exc.args[0]}") from exc
    except Exception as exc:
        # ``derive_domain`` imports the user's domain module. A broken module
        # raises something other than ``NoDomainException`` (a ``SyntaxError``, or
        # any error at module top level); surface it so the caller sees the real
        # reason instead of a hidden server crash.
        raise McpToolError(f"Error loading Protean domain: {exc}") from exc
    assert derived is not None
    return derived


def _load(domain: str | None) -> Domain:
    """Discover and initialise a domain for ``introspect``.

    [`Domain.to_ir`][protean.domain.Domain.to_ir] requires an initialised
    domain, so this calls ``init()`` (mirroring the CLI's ``load_domain_ir``).
    """
    derived = _derive(domain)
    try:
        derived.init()
    except Exception as exc:
        raise McpToolError(f"Error initialising Protean domain: {exc}") from exc
    return derived


def check(domain: str | None = None) -> dict[str, Any]:
    """Run the full diagnostic report over the domain.

    Returns the [`Domain.check`][protean.domain.Domain.check] report verbatim:
    ``domain``, ``status``, ``errors``, ``diagnostics``, and ``counts``.
    """
    derived = _derive(domain)
    try:
        # ``check`` prepares the domain, which imports the rest of its package;
        # a broken sibling module raises here, so translate it like a load error.
        return derived.check()
    except Exception as exc:
        raise McpToolError(f"Error checking Protean domain: {exc}") from exc


def validate(domain: str | None = None) -> ValidateResult:
    """Answer whether the domain loads and passes validation.

    A pass/fail gate over the same [`Domain.check`][protean.domain.Domain.check]
    run as ``check``, narrowed to the fields an agent needs to decide go/no-go:
    ``valid`` is ``True`` when there are no errors.
    """
    report = check(domain)
    return {
        "domain": report["domain"],
        "valid": not report["errors"],
        "status": report["status"],
        "errors": report["errors"],
        "counts": report["counts"],
    }


def introspect(domain: str | None = None) -> dict[str, Any]:
    """Return the domain's Intermediate Representation.

    The IR ([`Domain.to_ir`][protean.domain.Domain.to_ir]) is the complete
    topology of the domain: its elements, their fields, and how they connect.
    """
    derived = _load(domain)
    try:
        return derived.to_ir()
    except Exception as exc:
        raise McpToolError(f"Error introspecting Protean domain: {exc}") from exc


def explain(code: str) -> ExplainResult:
    """Explain one diagnostic code from the diagnostics registry.

    Returns the registry metadata for ``code``: its ``category``, ``level``,
    ``meaning``, ``rationale``, ``fix``, ``kind``, and the ``resolution`` command
    when one clears the diagnostic. An unknown code raises :exc:`McpToolError`
    naming the closest known codes.
    """
    # Imported here so the diagnostics subsystem is pulled in only when a caller
    # actually asks to explain a code, keeping tool import cheap.
    from protean.ir.diagnostics import (  # noqa: PLC0415
        REGISTRY,
        DiagnosticCode,
        resolve,
    )

    normalized = code.strip().upper()
    try:
        resolved_code = DiagnosticCode(normalized)
    except ValueError as exc:
        known = sorted(c.value for c in REGISTRY)
        suggestions = difflib.get_close_matches(normalized, known, n=5)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise McpToolError(f"Unknown diagnostic code {code!r}.{hint}") from exc

    meta = resolve(resolved_code)
    return {
        "code": resolved_code.value,
        "category": meta.category,
        "level": meta.level,
        "meaning": meta.meaning,
        "rationale": meta.rationale,
        "fix": meta.fix,
        "kind": meta.kind,
        "resolution": dict(meta.resolution.as_wire()) if meta.resolution else None,
    }


def scaffold(
    element: str,
    name: str,
    project: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Plan a new element slice, and write it only when ``apply`` is true.

    Previews by default: it computes the create-only change plan through the
    scaffold core and returns the rendered preview plus the structured plan,
    touching nothing. The write happens only when called with ``apply=True``;
    MCP clients typically surface a tool call's arguments for the human to
    approve, so that flag is the caller's explicit consent to write.

    ``element`` is the element type (``"aggregate"`` for now), ``name`` the
    element name (e.g. ``"Order"``), and ``project`` the project root (the
    directory that holds ``src/``), defaulting to the working directory.
    """
    # Imported from the scaffold package here (matching `protean add`); the
    # package re-exports these and pulls in no `copier`, so the scaffold `[extra]`
    # is not needed to preview or apply a slice.
    from protean.scaffold import (  # noqa: PLC0415
        AddPlanError,
        ApplyError,
        ConfigOperation,
        apply_plan,
        plan_add_slice,
        render_preview,
    )

    project_path = _resolve_path(project, "project")
    try:
        plan = plan_add_slice(project_path, element, name)
    except AddPlanError as exc:
        raise McpToolError(str(exc)) from exc

    # A slice is create-only, so every op carries a file path; a config op (which
    # sets a domain.toml key, not a file) has none, so it is left out of `files`.
    files = [op.path for op in plan.operations if not isinstance(op, ConfigOperation)]
    result: dict[str, Any] = {
        "applied": False,
        "element": element,
        "name": name,
        "files": files,
        "plan": plan.to_dict(),
        "preview": render_preview(plan),
    }

    if not apply:
        return result

    try:
        written = apply_plan(project_path, plan)
    except ApplyError as exc:
        raise McpToolError(str(exc)) from exc

    result["applied"] = True
    result["written"] = list(written)
    return result
