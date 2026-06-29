"""Upgrade-readiness diagnostics for moving a domain to a newer Protean release.

These checks are **read-only**. Each inspects the loaded domain (and, where a
live database connection is available, its schema) and reports changes that may
need operator attention when upgrading, with concrete remediation. Schema
changes are *generated* as SQL for the operator to review and run — nothing is
applied automatically, in keeping with Protean's stance that migrations are an
adapter/operator concern, not a framework one.

The entry point is :func:`run_upgrade_checks`; the ``protean upgrade-check`` CLI
command renders the findings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from protean.utils import DomainObjects

if TYPE_CHECKING:
    from protean.domain import Domain


@dataclass
class UpgradeFinding:
    """A single upgrade-readiness finding."""

    code: str
    level: str  # "warning" | "info"
    title: str
    detail: str
    remediation: str
    element: str | None = None
    sql: str | None = None  # generated migration SQL, when applicable

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "level": self.level,
            "title": self.title,
            "detail": self.detail,
            "remediation": self.remediation,
            "element": self.element,
            "sql": self.sql,
        }


# ---------------------------------------------------------------------------
# Element checks
# ---------------------------------------------------------------------------


def _check_status_self_transitions(domain: "Domain") -> list[UpgradeFinding]:
    """Flag status fields whose transition maps omit self-loops.

    0.16 validates status self-transitions against the transition map: assigning
    a status to its current value is rejected unless the state lists itself as a
    target. This is advisory — only the application knows whether it relies on
    silent self-assignment (e.g. idempotent updates).
    """
    findings: list[UpgradeFinding] = []
    registry = domain.registry
    for element_type in (DomainObjects.AGGREGATE, DomainObjects.ENTITY):
        for _, record in registry._elements[element_type.value].items():
            cls = record.cls
            field_meta = getattr(cls, "__protean_field_meta__", {})
            for fname, spec in field_meta.items():
                if getattr(spec, "field_kind", None) != "status":
                    continue
                transitions = getattr(spec, "transitions", None)
                if not transitions:
                    continue
                missing = [
                    state
                    for state, targets in transitions.items()
                    if state not in targets
                ]
                if missing:
                    findings.append(
                        UpgradeFinding(
                            code="STATUS_SELF_TRANSITION",
                            level="info",
                            title=(
                                f"Status field `{cls.__name__}.{fname}` may now "
                                f"reject self-transitions"
                            ),
                            detail=(
                                "0.16 rejects assigning a status to its current value "
                                "unless the state lists itself as a target. States "
                                f"without a self-loop: {', '.join(sorted(missing))}."
                            ),
                            remediation=(
                                "If your code ever re-assigns one of these states to "
                                "itself (idempotent updates), add the state to its own "
                                "target list, e.g. `{State.X: [State.X, ...]}`."
                            ),
                            element=f"{cls.__name__}.{fname}",
                        )
                    )
    return findings


# ---------------------------------------------------------------------------
# Config checks
# ---------------------------------------------------------------------------


def _databases(domain: "Domain") -> dict:
    cfg = domain.config.get("databases", {})
    return {k: v for k, v in cfg.items() if isinstance(v, dict)}


def _check_pool_defaults(domain: "Domain") -> list[UpgradeFinding]:
    """Warn when a SQL database relies on the raised default pool size."""
    findings: list[UpgradeFinding] = []
    for name, cfg in _databases(domain).items():
        if cfg.get("provider") in ("postgresql", "mssql") and "pool_size" not in cfg:
            findings.append(
                UpgradeFinding(
                    code="POOL_DEFAULTS_CHANGED",
                    level="warning",
                    title=(
                        f"Database `{name}` uses the new default connection-pool size"
                    ),
                    detail=(
                        "0.16 raised the SQLAlchemy pool defaults to pool_size=5, "
                        "max_overflow=10 (from 2/5). With pool settings unset, each "
                        "worker may open up to 15 connections (was 7)."
                    ),
                    remediation=(
                        "Verify the database's max_connections has headroom "
                        f"(workers x 15). To keep the previous behavior, set "
                        f"pool_size=2 and max_overflow=5 on [databases.{name}]."
                    ),
                    element=f"databases.{name}",
                )
            )
    return findings


def _check_elasticsearch_server(domain: "Domain") -> list[UpgradeFinding]:
    """Warn that the Elasticsearch provider now defaults to the v8 client."""
    findings: list[UpgradeFinding] = []
    for name, cfg in _databases(domain).items():
        if cfg.get("provider") == "elasticsearch":
            findings.append(
                UpgradeFinding(
                    code="ELASTICSEARCH_SERVER_V8",
                    level="warning",
                    title=(
                        f"Elasticsearch provider `{name}` now defaults to the v8 client"
                    ),
                    detail=(
                        "0.16 installs resolve to the Elasticsearch 8.x client, which "
                        "only connects to an Elasticsearch 8.x server."
                    ),
                    remediation=(
                        "Upgrade the Elasticsearch server to 8.x, or pin "
                        "`elasticsearch<8` to keep the 7.17 client (which connects to "
                        "both 7.x and 8.x servers)."
                    ),
                    element=f"databases.{name}",
                )
            )
    return findings


def _check_health_port(domain: "Domain") -> list[UpgradeFinding]:
    """Note the new default health-check port binding for ``protean server``."""
    server_cfg = domain.config.get("server", {})
    health = server_cfg.get("health", {}) if isinstance(server_cfg, dict) else {}
    if isinstance(health, dict) and health.get("enabled") is False:
        return []
    return [
        UpgradeFinding(
            code="HEALTH_PORT_BIND",
            level="info",
            title="`protean server` now binds a health-check port (8080)",
            detail=(
                "0.16 starts a health-check HTTP server on port 8080 by default "
                "(/healthz, /livez, /readyz)."
            ),
            remediation=(
                "Ensure port 8080 is free, or set [server.health] port = ... / "
                "enabled = false. The engine logs a warning and continues if the "
                "port is already in use."
            ),
            element="server.health",
        )
    ]


# ---------------------------------------------------------------------------
# Schema check (live database introspection -> generated SQL)
# ---------------------------------------------------------------------------


def _outbox_string_bounds() -> dict[str, int]:
    """Read the declared ``max_length`` of the Outbox string fields.

    The Outbox bounds are declared with ``Annotated[str, Field(max_length=N)]``,
    so they surface as ``MaxLen`` constraints in the pydantic field metadata.
    """
    from protean.utils.outbox import Outbox

    bounds: dict[str, int] = {}
    for fname, field_info in Outbox.model_fields.items():
        for meta in getattr(field_info, "metadata", []):
            max_length = getattr(meta, "max_length", None)
            if max_length is not None:
                bounds[fname] = max_length
                break
    return bounds


def _alter_statement(dialect: str, column: str, length: int, nullable: bool) -> str:
    """Render a single per-dialect ALTER for one outbox column."""
    if dialect == "postgresql":
        return f"  ALTER COLUMN {column} TYPE varchar({length})"
    if dialect == "mysql":
        null_sql = "NULL" if nullable else "NOT NULL"
        return f"  MODIFY {column} varchar({length}) {null_sql}"
    if dialect in ("mssql", "mssql+pyodbc"):
        null_sql = "NULL" if nullable else "NOT NULL"
        return f"ALTER TABLE outbox ALTER COLUMN {column} varchar({length}) {null_sql};"
    # Fallback to standard SQL
    return f"  ALTER COLUMN {column} TYPE varchar({length})"


def _check_outbox_schema(domain: "Domain") -> list[UpgradeFinding]:
    """Diff each live outbox table against the bounded Outbox model.

    For SQL providers whose ``outbox`` table still has unbounded string columns
    (the pre-0.16 ``TEXT`` shape), generate the exact backend ``ALTER`` to apply
    the new ``VARCHAR(N)`` bounds. SQLite enforces no lengths, so it is a no-op.
    """
    try:
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.types import String as SAString
    except ImportError:
        return []

    from protean.adapters.repository.sqlalchemy import SAProvider

    bounds = _outbox_string_bounds()
    findings: list[UpgradeFinding] = []

    for name, provider in domain.providers.items():
        if not isinstance(provider, SAProvider):
            continue
        engine = getattr(provider, "_engine", None)
        if engine is None:
            continue
        dialect = engine.dialect.name
        try:
            inspector = sa_inspect(engine)
            if not inspector.has_table("outbox"):
                continue
            columns = {c["name"]: c for c in inspector.get_columns("outbox")}
        except Exception:
            # Introspection is best-effort; never fail the upgrade check on it.
            continue

        if dialect == "sqlite":
            # SQLite does not enforce VARCHAR lengths; nothing to migrate.
            continue

        alters: list[str] = []
        for column, target_len in bounds.items():
            col = columns.get(column)
            if col is None:
                continue
            col_type = col.get("type")
            current_len = getattr(col_type, "length", None)
            is_string = isinstance(col_type, SAString)
            # Needs migration when the column is unbounded (TEXT / no length) or
            # bounded wider than the new target.
            if (not is_string) or current_len is None or current_len > target_len:
                alters.append(
                    _alter_statement(
                        dialect, column, target_len, bool(col.get("nullable", True))
                    )
                )

        if not alters:
            continue

        if dialect in ("mssql", "mssql+pyodbc"):
            sql = "\n".join(alters)
        else:
            sql = "ALTER TABLE outbox\n" + ",\n".join(alters) + ";"

        findings.append(
            UpgradeFinding(
                code="OUTBOX_NEEDS_ALTER",
                level="warning",
                title=(f"Outbox table on `{name}` still has unbounded string columns"),
                detail=(
                    "0.16 bounds the Outbox string columns with VARCHAR(N) to unblock "
                    "indexing and reduce storage. The existing table keeps working "
                    "as-is; apply the migration below to match the new schema."
                ),
                remediation=(
                    "Review the generated SQL, confirm no existing value exceeds the "
                    "new bounds, then run it against this database."
                ),
                element=f"databases.{name}",
                sql=sql,
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

# All checks, in report order. Each takes the domain and returns findings.
_CHECKS: tuple[Callable[["Domain"], list[UpgradeFinding]], ...] = (
    _check_status_self_transitions,
    _check_pool_defaults,
    _check_elasticsearch_server,
    _check_health_port,
    _check_outbox_schema,
)


def run_upgrade_checks(domain: "Domain") -> list[UpgradeFinding]:
    """Run every upgrade-readiness check against an initialized domain.

    Returns a flat, ordered list of findings. Each check is isolated, so a
    failure in one never suppresses the others.
    """
    findings: list[UpgradeFinding] = []
    for check in _CHECKS:
        try:
            findings.extend(check(domain))
        except Exception:  # a check must never break the whole report
            continue
    return findings
