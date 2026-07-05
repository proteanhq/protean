"""Tests for the 0.16 upgrade-readiness checks (``protean upgrade-check``)."""

import pytest

from protean.upgrade import (
    UpgradeFinding,
    _alter_statement,
    _check_elasticsearch_server,
    _check_health_port,
    _check_pool_defaults,
    _outbox_composite_index_sql,
    _outbox_set_not_null_sql,
    run_upgrade_checks,
)


def _codes(findings: list[UpgradeFinding]) -> set[str]:
    return {f.code for f in findings}


# ---------------------------------------------------------------------------
# POOL_DEFAULTS_CHANGED
# ---------------------------------------------------------------------------


class TestPoolDefaults:
    def test_flags_postgresql_without_pool_size(self, test_domain):
        test_domain.config["databases"]["secondary"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://x/y",
        }
        findings = _check_pool_defaults(test_domain)
        codes = _codes(findings)
        assert "POOL_DEFAULTS_CHANGED" in codes
        assert any(f.element == "databases.secondary" for f in findings)

    def test_no_finding_when_pool_size_set(self, test_domain):
        test_domain.config["databases"]["secondary"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://x/y",
            "pool_size": 2,
        }
        assert _check_pool_defaults(test_domain) == []

    def test_no_finding_for_memory_provider(self, test_domain):
        # The default test domain uses in-memory providers.
        assert _check_pool_defaults(test_domain) == []


# ---------------------------------------------------------------------------
# ELASTICSEARCH_SERVER_V8
# ---------------------------------------------------------------------------


class TestElasticsearchServer:
    def test_flags_elasticsearch_provider(self, test_domain):
        test_domain.config["databases"]["search"] = {
            "provider": "elasticsearch",
            "database_uri": {"hosts": ["localhost:9200"]},
        }
        findings = _check_elasticsearch_server(test_domain)
        assert "ELASTICSEARCH_SERVER_V8" in _codes(findings)

    def test_no_finding_without_elasticsearch(self, test_domain):
        assert _check_elasticsearch_server(test_domain) == []


# ---------------------------------------------------------------------------
# HEALTH_PORT_BIND
# ---------------------------------------------------------------------------


class TestHealthPort:
    def test_info_by_default(self, test_domain):
        findings = _check_health_port(test_domain)
        assert len(findings) == 1
        assert findings[0].code == "HEALTH_PORT_BIND"
        assert findings[0].level == "info"

    def test_no_finding_when_disabled(self, test_domain):
        test_domain.config["server"] = {"health": {"enabled": False}}
        assert _check_health_port(test_domain) == []


# ---------------------------------------------------------------------------
# Outbox ALTER SQL generation (per dialect)
# ---------------------------------------------------------------------------


class TestAlterStatement:
    def test_postgresql(self):
        assert (
            _alter_statement("postgresql", "status", 32, nullable=False)
            == "  ALTER COLUMN status TYPE varchar(32)"
        )

    def test_mysql_includes_nullability(self):
        assert (
            _alter_statement("mysql", "locked_by", 128, nullable=True)
            == "  MODIFY locked_by varchar(128) NULL"
        )

    def test_mssql_is_standalone_statement(self):
        out = _alter_statement("mssql", "type", 255, nullable=False)
        assert out == "ALTER TABLE outbox ALTER COLUMN type varchar(255) NOT NULL;"

    def test_unknown_dialect_falls_back_to_standard_sql(self):
        assert (
            _alter_statement("oracle", "status", 32, nullable=False)
            == "  ALTER COLUMN status TYPE varchar(32)"
        )


# ---------------------------------------------------------------------------
# Outbox schema diff against a live SQLite database (no Docker required)
# ---------------------------------------------------------------------------


@pytest.mark.sqlite
class TestOutboxSchemaSqlite:
    @pytest.fixture
    def sqlite_domain(self, tmp_path):
        from protean.domain import Domain
        from protean.upgrade import _check_outbox_schema  # noqa: F401

        domain = Domain(name="UpgradeSqlite")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": f"sqlite:///{tmp_path / 'uc.db'}",
        }
        domain.init(traverse=False)
        return domain

    def test_no_outbox_table_yields_no_finding(self, sqlite_domain):
        from protean.upgrade import _check_outbox_schema

        # has_table('outbox') is False -> nothing to report.
        assert _check_outbox_schema(sqlite_domain) == []

    def test_sqlite_with_outbox_table_is_a_noop(self, sqlite_domain):
        from sqlalchemy import text

        from protean.upgrade import _check_outbox_schema

        engine = sqlite_domain.providers["default"]._engine
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE outbox (id varchar(36), message_id text)"))
        # SQLite does not enforce VARCHAR lengths -> the check skips it.
        assert _check_outbox_schema(sqlite_domain) == []


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


class TestRunUpgradeChecks:
    def test_aggregates_findings_and_isolates_failures(self, test_domain, monkeypatch):
        # The ES + health checks read config, not live providers, so no init()
        # is required (and constructing a real ES provider would need a server).
        test_domain.config["databases"]["search"] = {"provider": "elasticsearch"}

        import protean.upgrade as up

        def _boom(domain):
            raise RuntimeError("boom")

        # One check raising must not suppress the others.
        monkeypatch.setattr(
            up,
            "_CHECKS",
            (
                _boom,
                up._check_elasticsearch_server,
                up._check_health_port,
            ),
        )

        findings = run_upgrade_checks(test_domain)
        codes = _codes(findings)
        # ES + health still reported despite the failing check...
        assert "ELASTICSEARCH_SERVER_V8" in codes
        assert "HEALTH_PORT_BIND" in codes
        # ...and the failure is surfaced (not silently swallowed) as a warning.
        failed = [f for f in findings if f.code == "CHECK_FAILED"]
        assert len(failed) == 1
        assert failed[0].level == "warning"
        assert "RuntimeError" in failed[0].detail

    def test_outbox_check_noop_on_memory_provider(self, test_domain):
        test_domain.init(traverse=False)
        from protean.upgrade import _check_outbox_schema

        # In-memory providers are not SQLAlchemy-backed -> nothing to migrate.
        assert _check_outbox_schema(test_domain) == []


# ---------------------------------------------------------------------------
# Outbox schema diff against a live PostgreSQL table (the 0.15 -> 0.16 path)
# ---------------------------------------------------------------------------

_OLD_OUTBOX_DDL = """
DROP TABLE IF EXISTS outbox;
CREATE TABLE outbox (
  id varchar(36) PRIMARY KEY,
  message_id text NOT NULL, stream_name text NOT NULL, type text NOT NULL,
  data jsonb, metadata_ jsonb, status text NOT NULL,
  locked_by text, correlation_id text, causation_id text, target_broker text,
  created_at timestamptz
);
INSERT INTO outbox (id, message_id, stream_name, type, status)
VALUES ('1', 'testdomain::order-abc-3', 'testdomain::order', 'OrderPlaced.v1', 'PENDING');
"""


@pytest.mark.postgresql
class TestOutboxSchemaPostgres:
    @pytest.fixture
    def pg_domain(self):
        from sqlalchemy import text

        from protean.domain import Domain
        from tests.shared import POSTGRES_URI

        domain = Domain(name="UpgradePG")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": POSTGRES_URI,
        }
        domain.init(traverse=False)
        engine = domain.providers["default"]._engine
        # Build a pre-0.16 (TEXT-column) outbox table with a representative row.
        with engine.begin() as conn:
            for stmt in filter(None, (s.strip() for s in _OLD_OUTBOX_DDL.split(";"))):
                conn.execute(text(stmt))
        yield domain
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS outbox"))

    def test_detects_unbounded_columns_and_generates_alter(self, pg_domain):
        from protean.upgrade import _check_outbox_schema

        findings = _check_outbox_schema(pg_domain)
        assert len(findings) == 1
        f = findings[0]
        assert f.code == "OUTBOX_NEEDS_ALTER"
        assert f.sql is not None
        # All eight bounded columns appear; unbounded JSON columns do not.
        for col, length in [
            ("message_id", 255),
            ("status", 32),
            ("locked_by", 128),
            ("target_broker", 128),
        ]:
            assert f"ALTER COLUMN {col} TYPE varchar({length})" in f.sql
        assert "data" not in f.sql and "metadata_" not in f.sql

    def test_generated_sql_applies_and_clears_the_finding(self, pg_domain):
        from sqlalchemy import text

        from protean.upgrade import _check_outbox_schema

        sql = _check_outbox_schema(pg_domain)[0].sql
        engine = pg_domain.providers["default"]._engine
        with engine.begin() as conn:
            conn.execute(text(sql))
            # The pre-existing row survives the migration.
            assert (
                conn.execute(text("SELECT message_id FROM outbox")).scalar()
                == "testdomain::order-abc-3"
            )
        # After applying, the check is clean (idempotent).
        assert _check_outbox_schema(pg_domain) == []

    def test_absent_bounded_columns_are_skipped(self, pg_domain):
        from sqlalchemy import text

        from protean.upgrade import _check_outbox_schema

        engine = pg_domain.providers["default"]._engine
        # A table missing most bounded columns: only message_id is present.
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE outbox"))
            conn.execute(text("CREATE TABLE outbox (id varchar(36), message_id text)"))

        findings = _check_outbox_schema(pg_domain)
        # The present unbounded column is migrated; absent columns are skipped
        # (no KeyError, no spurious ALTER for status/locked_by/...).
        assert len(findings) == 1
        assert "ALTER COLUMN message_id" in findings[0].sql
        assert "status" not in findings[0].sql


# ---------------------------------------------------------------------------
# Outbox structural migrations: target_broker NOT NULL (#1041) + composite
# unique index (#1009). Generated-SQL unit tests need no database.
# ---------------------------------------------------------------------------


class TestOutboxMigrationSql:
    def test_not_null_backfills_then_alters(self):
        sql = _outbox_set_not_null_sql("postgresql")
        assert sql.index("UPDATE outbox SET target_broker = 'default'") < sql.index(
            "ALTER COLUMN target_broker SET NOT NULL"
        )

    def test_not_null_is_typed_on_mysql_and_mssql(self):
        assert "MODIFY target_broker varchar(128) NOT NULL" in _outbox_set_not_null_sql(
            "mysql"
        )
        assert (
            "ALTER COLUMN target_broker varchar(128) NOT NULL"
            in _outbox_set_not_null_sql("mssql")
        )

    def test_index_backfills_then_swaps_to_composite(self):
        sql = _outbox_composite_index_sql("postgresql")
        assert (
            sql.index("UPDATE outbox")
            < sql.index("DROP INDEX")
            < sql.index("CREATE UNIQUE INDEX uq_outbox_message_id_target_broker")
        )

    def test_index_drop_syntax_differs_by_dialect(self):
        assert (
            "DROP INDEX IF EXISTS uq_outbox_message_id;"
            in _outbox_composite_index_sql("postgresql")
        )
        assert (
            "DROP INDEX uq_outbox_message_id ON outbox;"
            in _outbox_composite_index_sql("mysql")
        )


@pytest.mark.sqlite
class TestOutboxMigrationsSqlite:
    @pytest.fixture
    def sqlite_domain(self, tmp_path):
        from protean.domain import Domain

        domain = Domain(name="UpgradeMigrationsSqlite")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": f"sqlite:///{tmp_path / 'um.db'}",
        }
        domain.init(traverse=False)
        return domain

    def _create_outbox(self, domain, *, index_sql=None):
        from sqlalchemy import text

        engine = domain.providers["default"]._engine
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE outbox (id varchar(36), message_id varchar(255), "
                    "target_broker varchar(128))"
                )
            )
            if index_sql:
                conn.execute(text(index_sql))

    def test_no_outbox_table_yields_no_finding(self, sqlite_domain):
        from protean.upgrade import _check_outbox_migrations

        assert _check_outbox_migrations(sqlite_domain) == []

    def test_legacy_message_id_index_is_flagged(self, sqlite_domain):
        from protean.upgrade import _check_outbox_migrations

        self._create_outbox(
            sqlite_domain,
            index_sql="CREATE UNIQUE INDEX uq_outbox_message_id ON outbox (message_id)",
        )
        codes = _codes(_check_outbox_migrations(sqlite_domain))
        assert "OUTBOX_UNIQUE_INDEX_LEGACY" in codes
        # SQLite cannot ALTER-add NOT NULL in place, so that finding is skipped.
        assert "OUTBOX_TARGET_BROKER_NULLABLE" not in codes

    def test_index_migration_sql_applies_and_clears(self, sqlite_domain):
        from sqlalchemy import text

        from protean.upgrade import _check_outbox_migrations

        self._create_outbox(
            sqlite_domain,
            index_sql="CREATE UNIQUE INDEX uq_outbox_message_id ON outbox (message_id)",
        )
        finding = next(
            f
            for f in _check_outbox_migrations(sqlite_domain)
            if f.code == "OUTBOX_UNIQUE_INDEX_LEGACY"
        )
        engine = sqlite_domain.providers["default"]._engine
        with engine.begin() as conn:
            for stmt in filter(None, (s.strip() for s in finding.sql.split(";"))):
                conn.execute(text(stmt))
        assert _check_outbox_migrations(sqlite_domain) == []

    def test_composite_index_is_not_flagged(self, sqlite_domain):
        from protean.upgrade import _check_outbox_migrations

        self._create_outbox(
            sqlite_domain,
            index_sql=(
                "CREATE UNIQUE INDEX uq_outbox_message_id_target_broker "
                "ON outbox (message_id, target_broker)"
            ),
        )
        assert _check_outbox_migrations(sqlite_domain) == []

    def test_no_unique_index_is_not_flagged(self, sqlite_domain):
        from protean.upgrade import _check_outbox_migrations

        self._create_outbox(sqlite_domain)
        assert _check_outbox_migrations(sqlite_domain) == []


_LEGACY_OUTBOX_DDL = """
DROP TABLE IF EXISTS outbox;
CREATE TABLE outbox (
  id varchar(36) PRIMARY KEY,
  message_id varchar(255) NOT NULL,
  target_broker varchar(128),
  created_at timestamptz
);
CREATE UNIQUE INDEX uq_outbox_message_id ON outbox (message_id)
"""


@pytest.mark.postgresql
class TestOutboxMigrationsPostgres:
    @pytest.fixture
    def pg_domain(self):
        from sqlalchemy import text

        from protean.domain import Domain
        from tests.shared import POSTGRES_URI

        domain = Domain(name="UpgradeMigrationsPG")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": POSTGRES_URI,
        }
        domain.init(traverse=False)
        engine = domain.providers["default"]._engine
        # A nullable target_broker and the legacy message_id-only unique index.
        with engine.begin() as conn:
            for stmt in filter(
                None, (s.strip() for s in _LEGACY_OUTBOX_DDL.split(";"))
            ):
                conn.execute(text(stmt))
        yield domain
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS outbox"))

    def test_flags_both_nullable_target_broker_and_legacy_index(self, pg_domain):
        from protean.upgrade import _check_outbox_migrations

        codes = _codes(_check_outbox_migrations(pg_domain))
        assert codes == {"OUTBOX_TARGET_BROKER_NULLABLE", "OUTBOX_UNIQUE_INDEX_LEGACY"}

    def test_generated_sql_applies_and_clears_both_findings(self, pg_domain):
        from sqlalchemy import text

        from protean.upgrade import _check_outbox_migrations

        engine = pg_domain.providers["default"]._engine
        for finding in _check_outbox_migrations(pg_domain):
            with engine.begin() as conn:
                for stmt in filter(None, (s.strip() for s in finding.sql.split(";"))):
                    conn.execute(text(stmt))
        # Both migrations applied -> the check is clean and idempotent.
        assert _check_outbox_migrations(pg_domain) == []
