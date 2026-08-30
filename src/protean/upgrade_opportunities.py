"""Opportunity detectors for ``protean upgrade-check --opportunities``.

Where :mod:`protean.upgrade` reports what needs attention when you move *up* a
release, this module reports the other direction: capability the framework has
shipped that the domain still appears to hand-roll. The issue's phrase for it is
"paying for capability they already own".

Every detector here is **deterministic**. It reads the domain's source through
:class:`~protean.ir.analysis.source_provider.SourceProvider` and matches on
imports and structure, never on bare names, so it gives the same verdict every
run and does not fire on correct code. Judgment-heavy advice ("this orchestration
is really a process manager") stays out of OSS; that lives in the commercial
Domain Assessment surface, on the non-deterministic side of the open-core
boundary.

Each detector declares the release its capability arrived in as a module
constant. A detector reports an opportunity only when that release is at or below
the *pinned* version, i.e. the domain already has the capability installed but
still hand-rolls it. The pinned version defaults to the installed Protean
(``protean.__version__``); the CLI's ``--pinned-version`` overrides it. Pinning
below a capability's release suppresses that capability's finding, because you do
not own it yet.

The entry point is :func:`run_opportunity_checks`; the ``protean upgrade-check``
CLI command renders the findings the same way it renders the readiness checks.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import TYPE_CHECKING

from protean.ir.analysis.source_provider import SourceProvider
from protean.upgrade import UpgradeFinding, _summarise
from protean.upgrade_uow import _root_name

if TYPE_CHECKING:
    from protean.domain import Domain

# A parsed module, as yielded by SourceProvider.iter_trees().
Tree = tuple[str, ast.Module]
Version = tuple[int, int, int]
Detector = Callable[[list[Tree], Version], list[UpgradeFinding]]

# ---------------------------------------------------------------------------
# Release catalog
# ---------------------------------------------------------------------------
# The release each shipped capability arrived in, sourced from CHANGELOG.md.
# Kept as constants so a detector's verdict is reproducible: the version gate
# reads these, never a live import.

# The query-API primitives that let a domain drop raw SQL: Q(field__isnull=),
# F() column comparisons, QuerySet.count()/.only()/.all(with_total=False). All
# landed in 0.16.0. (Query handlers and domain.dispatch() are older, 0.15.0, but
# the raw-SQL-avoidance primitives are the 0.16.0 set.)
_QUERY_API_RELEASE = "0.16.0"
# DomainContextMiddleware (domain-context + correlation wiring for FastAPI).
_MIDDLEWARE_RELEASE = "0.15.0"
# The outbox processor (retry, backoff, DLQ).
_OUTBOX_RELEASE = "0.14.0"


# ---------------------------------------------------------------------------
# Version parsing and the pinned-version gate
# ---------------------------------------------------------------------------


def parse_version(version: str) -> Version:
    """Parse a ``MAJOR.MINOR.PATCH`` string to a tuple of ints for comparison.

    Only the leading digits of each of the first three dot-separated components
    are read, so a pre-release suffix (``0.15.0rc1``) compares by its numeric
    core and a missing component reads as ``0``. Protean version strings are
    clean semver, so this stays deterministic without pulling in ``packaging``.
    """
    numbers: list[int] = []
    for part in version.strip().split(".")[:3]:
        digits = ""
        for char in part:
            if char.isdigit():
                digits += char
            else:
                break
        numbers.append(int(digits) if digits else 0)
    while len(numbers) < 3:
        numbers.append(0)
    return (numbers[0], numbers[1], numbers[2])


def _owned(release: str, pinned: Version) -> bool:
    """Is the capability that shipped in *release* installed at *pinned*?"""
    return parse_version(release) <= pinned


# ---------------------------------------------------------------------------
# Detector 1: raw sqlalchemy.text() SQL sites
# ---------------------------------------------------------------------------


def _sqlalchemy_text_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Names in a module that reach ``sqlalchemy.text``.

    Returns ``(direct, module_aliases)``: ``direct`` are bare names bound to
    ``sqlalchemy.text`` (``from sqlalchemy import text [as t]``); ``module_aliases``
    are names bound to the ``sqlalchemy`` module itself (``import sqlalchemy [as
    sa]``), so ``sa.text(...)`` can be matched as an attribute call. Import-gating
    is what keeps this from flagging every unrelated ``text(`` call.
    """
    direct: set[str] = set()
    module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sqlalchemy" or alias.name.startswith("sqlalchemy."):
                    module_aliases.add(alias.asname or alias.name.split(".")[0])
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[0] == "sqlalchemy"
        ):
            for alias in node.names:
                if alias.name == "text":
                    direct.add(alias.asname or "text")
    return direct, module_aliases


def _is_text_call(node: ast.Call, direct: set[str], module_aliases: set[str]) -> bool:
    """Is *node* a call to the sqlalchemy ``text`` bound in this module?"""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in direct
    if isinstance(func, ast.Attribute) and func.attr == "text":
        return _root_name(func.value) in module_aliases
    return False


def _raw_sql_sites(trees: list[Tree]) -> list[str]:
    """``module:line`` for every sqlalchemy ``text(...)`` call across the domain."""
    sites: list[str] = []
    for module_name, tree in trees:
        direct, module_aliases = _sqlalchemy_text_names(tree)
        if not direct and not module_aliases:
            continue
        sites.extend(
            f"{module_name}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _is_text_call(node, direct, module_aliases)
        )
    return sites


def _detect_raw_sql(trees: list[Tree], pinned: Version) -> list[UpgradeFinding]:
    if not _owned(_QUERY_API_RELEASE, pinned):
        return []
    sites = _raw_sql_sites(trees)
    if not sites:
        return []
    return [
        UpgradeFinding(
            code="OPPORTUNITY_QUERY_API",
            level="info",
            title=f"{len(sites)} raw `sqlalchemy.text()` SQL site(s)",
            detail=(
                f"The query API shipped in {_QUERY_API_RELEASE} covers most of "
                "what raw SQL is reached for: `Q(field__isnull=)`, `F()` column "
                "comparisons, `QuerySet.count()`, `.only()`, and "
                "`.all(with_total=False)`, dispatched through `@domain.query_handler` "
                "and `domain.dispatch()`. Found at: "
                f"{_summarise(sorted(sites))}."
            ),
            remediation=(
                "Review each site: where it is a filter, count, or projection, "
                "the query API expresses it without hand-written SQL and stays "
                "portable across adapters."
            ),
        )
    ]


# ---------------------------------------------------------------------------
# Detector 2: a custom ASGI middleware beside DomainContextMiddleware
# ---------------------------------------------------------------------------

# Middlewares the framework or its ASGI stack already ships. Registering one of
# these is not hand-rolled capability, so an `add_middleware(...)` of any of them
# is not an opportunity. `DomainContextMiddleware` is Protean's own; the rest are
# the standard Starlette/FastAPI/uvicorn middlewares, which cover CORS, gzip,
# host allow-listing, sessions, and the like, none of which
# `DomainContextMiddleware` replaces. Without this allow-list the detector fires
# on a correct `app.add_middleware(CORSMiddleware)`.
_FRAMEWORK_MIDDLEWARES = frozenset(
    {
        "DomainContextMiddleware",
        "CORSMiddleware",
        "GZipMiddleware",
        "TrustedHostMiddleware",
        "SessionMiddleware",
        "HTTPSRedirectMiddleware",
        "WSGIMiddleware",
        "AuthenticationMiddleware",
        "ServerErrorMiddleware",
        "ExceptionMiddleware",
        "ProxyHeadersMiddleware",
    }
)


def _is_custom_middleware_class(node: ast.ClassDef) -> bool:
    """A user-defined ASGI middleware: a ``BaseHTTPMiddleware`` subclass, or a
    class defining ``async def dispatch(self, request, call_next)``."""
    for base in node.bases:
        if _root_name(base) == "BaseHTTPMiddleware":
            return True
    for item in node.body:
        if (
            isinstance(item, ast.AsyncFunctionDef)
            and item.name == "dispatch"
            and any(arg.arg == "call_next" for arg in item.args.args)
        ):
            return True
    return False


def _custom_middleware_sites(trees: list[Tree]) -> list[str]:
    """``module:line`` for each custom middleware definition or registration.

    Registrations name the middleware they add; the framework's own middlewares
    (``DomainContextMiddleware`` and the standard Starlette/FastAPI ones in
    :data:`_FRAMEWORK_MIDDLEWARES`) are not opportunities and are skipped.
    """
    sites: list[str] = []
    for module_name, tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _is_custom_middleware_class(node):
                sites.append(f"{module_name}:{node.lineno}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_middleware"
                and node.args
            ):
                added = _root_name(node.args[0])
                if added is not None and added not in _FRAMEWORK_MIDDLEWARES:
                    sites.append(f"{module_name}:{node.lineno}")
    return sites


def _detect_custom_middleware(
    trees: list[Tree], pinned: Version
) -> list[UpgradeFinding]:
    if not _owned(_MIDDLEWARE_RELEASE, pinned):
        return []
    sites = _custom_middleware_sites(trees)
    if not sites:
        return []
    return [
        UpgradeFinding(
            code="OPPORTUNITY_DOMAIN_CONTEXT_MIDDLEWARE",
            level="info",
            title=f"{len(sites)} custom ASGI middleware definition(s)",
            detail=(
                f"`DomainContextMiddleware` shipped in {_MIDDLEWARE_RELEASE} and "
                "wires the domain context plus correlation-id propagation "
                "(X-Correlation-ID in and out) for FastAPI apps. Found at: "
                f"{_summarise(sorted(sites))}."
            ),
            remediation=(
                "Where the custom middleware exists to set up domain context or "
                "correlation wiring, `DomainContextMiddleware` covers it. Register "
                "it with `app.add_middleware(DomainContextMiddleware, domain=...)`."
            ),
        )
    ]


# ---------------------------------------------------------------------------
# Detector 3: a queue-like status table with no outbox
# ---------------------------------------------------------------------------

# A status field whose choices span this vocabulary is a hand-rolled work queue.
# Kept tight (a match needs at least two of these) so a plain `status` field with
# domain choices like {active, inactive} does not fire.
_QUEUE_CHOICE_VOCAB = frozenset(
    {
        "pending",
        "queued",
        "processing",
        "in_progress",
        "inprogress",
        "done",
        "completed",
        "complete",
        "succeeded",
        "success",
        "failed",
        "failure",
        "error",
        "errored",
        "retry",
        "retrying",
        "dead",
        "dlq",
        "abandoned",
        "sent",
        "published",
    }
)


def _string_choices(call: ast.Call) -> set[str]:
    """The lowercased string choices literally passed to a field, if any.

    Reads a ``choices=[...]`` / ``choices=(...)`` keyword whose members are string
    constants. An enum reference (``choices=Status``) has no readable members, so
    it yields nothing and the detector stays silent on it.
    """
    for keyword in call.keywords:
        if keyword.arg != "choices":
            continue
        if not isinstance(keyword.value, ast.List | ast.Tuple):
            continue
        values: set[str] = set()
        for element in keyword.value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                values.add(element.value.strip().lower())
        return values
    return set()


def _is_status_target(targets: list[str]) -> bool:
    return any(name in ("status", "state") or "status" in name for name in targets)


def _assignment_targets(node: ast.Assign | ast.AnnAssign) -> list[str]:
    raw = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [name for name in (_root_name(t) for t in raw) if name is not None]


def _queue_status_sites(trees: list[Tree]) -> list[str]:
    """``module:line`` for each queue-like status field declaration."""
    sites: list[str] = []
    for module_name, tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign | ast.AnnAssign):
                continue
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            if not _is_status_target(_assignment_targets(node)):
                continue
            choices = _string_choices(value)
            if len(choices & _QUEUE_CHOICE_VOCAB) >= 2:
                sites.append(f"{module_name}:{node.lineno}")
    return sites


def _detect_queue_status(trees: list[Tree], pinned: Version) -> list[UpgradeFinding]:
    if not _owned(_OUTBOX_RELEASE, pinned):
        return []
    sites = _queue_status_sites(trees)
    if not sites:
        return []
    return [
        UpgradeFinding(
            code="OPPORTUNITY_OUTBOX",
            level="info",
            title=f"{len(sites)} queue-like status field(s)",
            detail=(
                f"The outbox shipped in {_OUTBOX_RELEASE} and handles reliable "
                "delivery with retry, backoff, and a dead-letter queue. A "
                "status field cycling through queue states (pending / processing "
                "/ done / failed) is usually a hand-rolled queue the outbox now "
                f"covers. Found at: {_summarise(sorted(sites))}."
            ),
            remediation=(
                "Where the status field tracks work to be swept, raise a domain "
                "event and let the outbox deliver it, rather than polling the "
                "table yourself."
            ),
        )
    ]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

_DETECTORS: tuple[Detector, ...] = (
    _detect_raw_sql,
    _detect_custom_middleware,
    _detect_queue_status,
)


def run_opportunity_checks(domain: Domain, pinned_version: str) -> list[UpgradeFinding]:
    """Run every opportunity detector against a domain's source.

    Reads the domain's source once through a shared
    :class:`~protean.ir.analysis.source_provider.SourceProvider` and hands the
    parsed trees to each detector. Detectors are isolated the same way the
    readiness checks are: if one raises, the others still run and the failure
    surfaces as a ``CHECK_FAILED`` finding, so the report is never silently
    incomplete.

    *pinned_version* gates each detector: an opportunity is reported only when
    the capability's release is at or below it. Findings come back in detector
    order, so the same input gives an identical report every run.
    """
    trees = list(SourceProvider(domain).iter_trees())
    pinned = parse_version(pinned_version)

    findings: list[UpgradeFinding] = []
    for detector in _DETECTORS:
        try:
            findings.extend(detector(trees, pinned))
        except Exception as exc:
            findings.append(
                UpgradeFinding(
                    code="CHECK_FAILED",
                    level="warning",
                    title=f"Opportunity check `{detector.__name__}` did not complete",
                    detail=(
                        f"The check raised {type(exc).__name__}: {exc}. The report "
                        "may be incomplete for this area."
                    ),
                    remediation=(
                        "Re-run with the domain fully configured; report the error "
                        "if it persists."
                    ),
                )
            )
    return findings
