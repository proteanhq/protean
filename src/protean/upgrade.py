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

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from protean.upgrade_uow import scan_domain_source
from protean.utils.outbox import Outbox

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

    def as_dict(self) -> dict[str, str | None]:
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
# Config checks
# ---------------------------------------------------------------------------


def _databases(domain: Domain) -> dict[str, dict[str, Any]]:
    cfg = domain.config.get("databases", {})
    return {k: v for k, v in cfg.items() if isinstance(v, dict)}


def _check_pool_defaults(domain: Domain) -> list[UpgradeFinding]:
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


def _check_elasticsearch_server(domain: Domain) -> list[UpgradeFinding]:
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


def _check_health_port(domain: Domain) -> list[UpgradeFinding]:
    """Note the new default health-check port binding for ``protean server``."""
    server_cfg = domain.config.get("server", {})
    health = server_cfg.get("health", {}) if isinstance(server_cfg, dict) else {}
    if isinstance(health, dict) and health.get("enabled") is False:
        return []
    return [
        UpgradeFinding(
            code="HEALTH_PORT_BIND",
            # Advisory: fires for every engine (host is always present in the
            # merged config defaults, so affected users cannot be isolated), so
            # keep it at "info" rather than tripping upgrade-check's exit code 2.
            level="info",
            title="`protean server` health-check server now binds loopback by default",
            detail=(
                "0.16 starts a health-check HTTP server on port 8080 by default "
                "(/healthz, /livez, /readyz). 0.17 changes its default bind host "
                "from 0.0.0.0 to 127.0.0.1, so probes are no longer reachable "
                "off-host unless you opt back in."
            ),
            remediation=(
                "For off-host probes (a load balancer or out-of-pod checker), set "
                '[server.health] host = "0.0.0.0". To run several engines on one '
                "host, give each a distinct port or set port_auto_increment = true. "
                "Set enabled = false to turn the server off."
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


def _check_outbox_schema(domain: Domain) -> list[UpgradeFinding]:
    """Diff each live outbox table against the bounded Outbox model.

    For SQL providers whose ``outbox`` table still has unbounded string columns
    (the pre-0.16 ``TEXT`` shape), generate the exact backend ``ALTER`` to apply
    the new ``VARCHAR(N)`` bounds. SQLite enforces no lengths, so it is a no-op.
    """
    try:
        from sqlalchemy import inspect as sa_inspect  # noqa: PLC0415
        from sqlalchemy.types import String as SAString  # noqa: PLC0415
    except ImportError:  # pragma: no cover - sqlalchemy backs every SAProvider
        return []

    from protean.adapters.repository.sqlalchemy import SAProvider  # noqa: PLC0415

    bounds = _outbox_string_bounds()
    findings: list[UpgradeFinding] = []

    for name, provider in domain.providers.items():
        if not isinstance(provider, SAProvider):
            continue
        engine = getattr(provider, "_engine", None)
        if engine is None:  # pragma: no cover - an initialized SAProvider has one
            continue
        dialect = engine.dialect.name
        # Honor a non-default provider schema so the right outbox table is found.
        schema = getattr(getattr(provider, "_metadata", None), "schema", None)
        try:
            inspector = sa_inspect(engine)
            if not inspector.has_table("outbox", schema=schema):
                continue
            columns = {
                c["name"]: c for c in inspector.get_columns("outbox", schema=schema)
            }
        except Exception as exc:
            # Reported rather than swallowed. The command documents CHECK_FAILED
            # as "a check could not complete; the report may be incomplete for
            # that area", and silently skipping a database would leave a clean
            # report meaning two different things.
            findings.append(
                UpgradeFinding(
                    code="CHECK_FAILED",
                    level="warning",
                    title=f"Could not inspect the outbox table on `{name}`",
                    detail=(
                        f"Reading the schema raised {type(exc).__name__}: {exc}. "
                        "The outbox migration checks did not run for this database, "
                        "so this report says nothing about its schema."
                    ),
                    remediation=(
                        "Check the database is reachable and the credentials can read "
                        "table metadata, then run `protean upgrade-check` again."
                    ),
                    element=f"databases.{name}",
                )
            )
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
# ---------------------------------------------------------------------------
# Source checks (ADR-0027: the Unit of Work is a real transaction)
# ---------------------------------------------------------------------------


def _summarise(sites: list[str], limit: int = 10) -> str:
    shown = ", ".join(sorted(sites)[:limit])
    extra = len(sites) - limit
    return f"{shown} (and {extra} more)" if extra > 0 else shown


def _check_unit_of_work_transaction(domain: Domain) -> list[UpgradeFinding]:
    """Report the two shapes ADR-0027 makes newly consequential.

    A Unit of Work is now one real database transaction, so a nested block joins
    the outer transaction (an inner rollback dooms it all) and external I/O
    inside a block holds row locks for the length of the call. Neither shows up
    in a diff of the user's code, because the user's code did not change.
    """
    nested, io_sites, total_blocks = scan_domain_source(domain)
    findings: list[UpgradeFinding] = []

    if nested:
        findings.append(
            UpgradeFinding(
                code="NESTED_UNIT_OF_WORK",
                level="warning",
                title=f"{len(nested)} nested Unit of Work block(s)",
                detail=(
                    "A Unit of Work opened while another is active now joins the "
                    "outermost transaction instead of running independently "
                    "(ADR-0027). There are no savepoints, so a rollback in the "
                    "inner block rolls back the outer one too. Found at: "
                    f"{_summarise(nested)}."
                ),
                remediation=(
                    "Check each site for an inner rollback (an explicit "
                    "`uow.rollback()`, or an exception caught outside the inner "
                    "block) that previously left the outer work intact. If the "
                    "inner block must be able to fail on its own, give it its "
                    "own use case rather than nesting it."
                ),
            )
        )
    elif total_blocks:
        findings.append(
            UpgradeFinding(
                code="UNIT_OF_WORK_NESTING_REVIEW",
                level="info",
                title=f"{total_blocks} Unit of Work block(s) to review for nesting",
                detail=(
                    "No Unit of Work is opened inside another in the same "
                    "function. Nesting through a call, where a handler's Unit of "
                    "Work invokes a service method that opens its own, cannot be "
                    "seen statically, and after ADR-0027 a nested rollback dooms "
                    "the whole transaction."
                ),
                remediation=(
                    "Walk the call graph under these blocks looking for another "
                    "`UnitOfWork()`. Nesting is safe as long as nothing inside "
                    "relies on rolling back independently."
                ),
            )
        )

    if io_sites:
        findings.append(
            UpgradeFinding(
                code="IO_INSIDE_UNIT_OF_WORK",
                level="warning",
                title=f"{len(io_sites)} external call(s) inside a Unit of Work",
                detail=(
                    "A Unit of Work is now one real database transaction "
                    "(ADR-0027), so it holds its row locks and its pooled "
                    "connection for as long as the block runs. Under the "
                    "previous AUTOCOMMIT model no transaction was open, so a "
                    "call out cost only wall-clock time. Found at: "
                    f"{_summarise(io_sites)}."
                ),
                remediation=(
                    "Move the call outside the Unit of Work: commit the domain "
                    "change first and then do the external work, or raise an "
                    "event and let the outbox publish it after the transaction "
                    "commits."
                ),
            )
        )

    return findings


# Forward-ported from `release/0.16.x` (#1093). These shipped in 0.16.2 but
# the prep commit never reached `main`, so 0.17 would have offered fewer
# migration checks than the patch release before it.
# The framework backfills a NULL ``target_broker`` to the configured internal
# broker; ``'default'`` is the out-of-the-box name. Both migrations below share
# this preamble — a NULL ``target_broker`` would violate the NOT NULL constraint
# and, because NULLs compare as distinct in a UNIQUE index, defeat the
# composite idempotency index.
def _backfill_sql(schema: str | None = None) -> str:
    return (
        f"UPDATE {_qualified('outbox', schema)} SET target_broker = 'default' "
        "WHERE target_broker IS NULL;"
    )


def _qualified(table: str, schema: str | None) -> str:
    """``schema.table`` when the provider puts the outbox outside the default schema.

    The check introspects with an explicit ``schema=``, so it finds the table
    wherever it lives. The generated SQL has to reach the same one: an
    unqualified name resolves against the session's search path and can name a
    different table, or none.
    """
    return f"{schema}.{table}" if schema else table


def _outbox_set_not_null_sql(dialect: str, schema: str | None = None) -> str:
    """Per-dialect SQL to backfill NULLs and add ``NOT NULL`` on ``target_broker``."""
    table = _qualified("outbox", schema)
    if dialect == "mysql":
        alter = f"ALTER TABLE {table} MODIFY target_broker varchar(128) NOT NULL;"
    elif dialect in ("mssql", "mssql+pyodbc"):
        alter = f"ALTER TABLE {table} ALTER COLUMN target_broker varchar(128) NOT NULL;"
    else:  # postgresql / standard
        alter = f"ALTER TABLE {table} ALTER COLUMN target_broker SET NOT NULL;"
    return f"{_backfill_sql(schema)}\n{alter}"


def _outbox_composite_index_sql(dialect: str, schema: str | None = None) -> str:
    """Per-dialect SQL to replace ``uq_outbox_message_id`` with the composite index."""
    table = _qualified("outbox", schema)
    if dialect in ("mysql", "mssql", "mssql+pyodbc"):
        drop = f"DROP INDEX uq_outbox_message_id ON {table};"
    else:  # postgresql / sqlite / standard
        drop = f"DROP INDEX IF EXISTS {_qualified('uq_outbox_message_id', schema)};"
    create = (
        "CREATE UNIQUE INDEX uq_outbox_message_id_target_broker\n"
        f"  ON {table} (message_id, target_broker);"
    )
    return f"{_backfill_sql(schema)}\n{drop}\n{create}"


def _check_outbox_migrations(domain: Domain) -> list[UpgradeFinding]:
    """Flag the intra-0.16 outbox structural migrations on each live outbox table.

    Two changes landed after the initial VARCHAR bounds: the recommended unique
    index became composite over (``message_id``, ``target_broker``) in 0.16.1,
    and ``target_broker`` became ``NOT NULL`` in 0.16.2. Protean never alters a
    populated table, so an outbox created on an earlier 0.16 release keeps the
    old shape; generate the SQL to bring it in line. Complements
    :func:`_check_outbox_schema`, which covers the column-length bounds.
    """
    try:
        from sqlalchemy import inspect as sa_inspect  # noqa: PLC0415
    except ImportError:  # pragma: no cover - sqlalchemy backs every SAProvider
        return []

    from protean.adapters.repository.sqlalchemy import SAProvider  # noqa: PLC0415

    findings: list[UpgradeFinding] = []
    for name, provider in domain.providers.items():
        if not isinstance(provider, SAProvider):
            continue
        engine = getattr(provider, "_engine", None)
        if engine is None:  # pragma: no cover - an initialized SAProvider has one
            continue
        dialect = engine.dialect.name
        schema = getattr(getattr(provider, "_metadata", None), "schema", None)
        try:
            inspector = sa_inspect(engine)
            if not inspector.has_table("outbox", schema=schema):
                continue
            columns = {
                c["name"]: c for c in inspector.get_columns("outbox", schema=schema)
            }
            indexes = inspector.get_indexes("outbox", schema=schema)
        except Exception:
            # Introspection is best-effort; never fail the upgrade check on it.
            continue

        # (0.16.2) target_broker NOT NULL. SQLite cannot add the constraint in
        # place — it needs a full table rebuild — so only the enforcing backends
        # get generated SQL here; the migration guide covers the SQLite rebuild.
        target_broker = columns.get("target_broker")
        if (
            target_broker is not None
            and target_broker.get("nullable", True)
            and dialect != "sqlite"
        ):
            findings.append(
                UpgradeFinding(
                    code="OUTBOX_TARGET_BROKER_NULLABLE",
                    level="warning",
                    title=f"Outbox `target_broker` on `{name}` is still nullable",
                    detail=(
                        "0.16.2 makes `Outbox.target_broker` NOT NULL. A NULL row "
                        "bypasses the (message_id, target_broker) idempotency index "
                        "(NULLs compare as distinct), silently reopening the "
                        "duplicate-publish window. The existing column keeps working; "
                        "backfill and add the constraint to match the new schema."
                    ),
                    remediation=(
                        "Confirm the backfill value matches your configured internal "
                        "broker (`[outbox] broker`, default `default`), then run the SQL."
                    ),
                    element=f"databases.{name}",
                    sql=_outbox_set_not_null_sql(dialect, schema),
                )
            )

        # (0.16.1) composite unique index. Only flag when the legacy single-column
        # unique index exists and the composite one does not — the index is
        # recommended, not framework-created, so its absence means nothing to do.
        # Compared as sets, not tuples: an index over (target_broker, message_id)
        # is as composite as (message_id, target_broker) for idempotency, and
        # flagging it would tell someone to drop a working index.
        unique_index_cols = [
            frozenset(ix.get("column_names") or [])
            for ix in indexes
            if ix.get("unique")
        ]
        if frozenset({"message_id"}) in unique_index_cols and (
            frozenset({"message_id", "target_broker"}) not in unique_index_cols
        ):
            findings.append(
                UpgradeFinding(
                    code="OUTBOX_UNIQUE_INDEX_LEGACY",
                    level="warning",
                    title=f"Outbox unique index on `{name}` is `message_id`-only",
                    detail=(
                        "0.16.1 changed the recommended outbox unique index from "
                        "`message_id` alone to a composite over (message_id, "
                        "target_broker). A single event is dual-written once per "
                        "target broker (all rows sharing one message_id), so the "
                        "single-column index rejects the framework's own dual-write "
                        "with a UniqueViolation."
                    ),
                    remediation=(
                        "Confirm the backfill value matches your configured internal "
                        "broker (`[outbox] broker`, default `default`), then run the SQL."
                    ),
                    element=f"databases.{name}",
                    sql=_outbox_composite_index_sql(dialect, schema),
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

# All checks, in report order. Each takes the domain and returns findings.


_CHECKS: tuple[Callable[[Domain], list[UpgradeFinding]], ...] = (
    _check_pool_defaults,
    _check_elasticsearch_server,
    _check_health_port,
    _check_outbox_schema,
    _check_outbox_migrations,
    _check_unit_of_work_transaction,
)


def run_upgrade_checks(domain: Domain) -> list[UpgradeFinding]:
    """Run every upgrade-readiness check against an initialized domain.

    Returns a flat, ordered list of findings. Each check is isolated: if one
    raises, the others still run and the failure is surfaced as a
    ``CHECK_FAILED`` warning so the report is never silently incomplete.
    """
    findings: list[UpgradeFinding] = []
    for check in _CHECKS:
        try:
            findings.extend(check(domain))
        except Exception as exc:
            findings.append(
                UpgradeFinding(
                    code="CHECK_FAILED",
                    level="warning",
                    title=f"Upgrade check `{check.__name__}` did not complete",
                    detail=(
                        f"The check raised {type(exc).__name__}: {exc}. The report "
                        "may be incomplete for this area."
                    ),
                    remediation=(
                        "Re-run with the database reachable and the domain fully "
                        "configured; report the error if it persists."
                    ),
                )
            )
    return findings
