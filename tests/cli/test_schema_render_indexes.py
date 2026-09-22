"""Tests for ``protean schema render --indexes``."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean import Index, Q
from protean.cli.schema import app, write_index_ddl
from protean.core.aggregate import BaseAggregate
from protean.exceptions import IncorrectUsageError
from protean.fields import Integer, String

runner = CliRunner()


# A domain module written to disk for the live ``--domain`` invocation path.
_DOMAIN_MODULE = """
from protean import Domain, Index, Q

domain = Domain(name="ShopCLI")
domain.config["databases"]["default"] = {
    "provider": "sqlite",
    "database_uri": "sqlite:///:memory:",
}


@domain.aggregate(indexes=[
    Index("status", "priority", desc=("priority",),
          where=Q(status__in=["active"]), name="ix_prod_active"),
    Index("sku", unique=True),
])
class Product:
    status: str
    priority: int = 0
    sku: str
"""


# A domain whose only index covers the identity: rendering it for MySQL reads
# ``identity_type`` off ``current_domain``, which needs a pushed context.
_IDENTITY_DOMAIN_MODULE = """
from protean import Domain, Index
from protean.fields import String

domain = Domain(name="KeyedCLI")
domain.config["databases"]["default"] = {
    "provider": "sqlite",
    "database_uri": "sqlite:///:memory:",
}


@domain.aggregate(indexes=[Index("id", "slug", name="ix_keyed")])
class Article:
    slug: String(max_length=64)
"""


class TestApplyErrors:
    def test_requires_indexes_flag(self):
        result = runner.invoke(app, ["render", "--domain=x"])
        assert result.exit_code != 0
        assert "pass --indexes" in result.output

    def test_indexes_requires_domain(self):
        result = runner.invoke(app, ["render", "--indexes"])
        assert result.exit_code != 0
        assert "requires --domain" in result.output

    def test_invalid_domain_aborts(self):
        result = runner.invoke(
            app, ["render", "--indexes", "--domain=nonexistent_module_xyz"]
        )
        assert result.exit_code != 0
        assert "Error loading Protean domain" in result.output


class TestMysqlKeyWidths:
    """``write_index_ddl`` runs the MySQL key-width guard through
    ``render_index_ddl``. The guard sizes an identifier column from the
    domain's ``identity_type``, which it reads off ``current_domain``, and
    ``load_domain`` leaves no context pushed — so the writer pushes one.
    """

    @pytest.fixture
    def keyed_domain(self, test_domain):
        @test_domain.aggregate(indexes=[Index("id", "slug", name="ix_keyed")])
        class Article(BaseAggregate):
            slug = String(max_length=64)

        test_domain.init(traverse=False)
        return test_domain

    @pytest.fixture
    def wide_domain(self, test_domain):
        @test_domain.aggregate(indexes=[Index("slug", name="ix_wide")])
        class Essay(BaseAggregate):
            slug = String(max_length=769)

        test_domain.init(traverse=False)
        return test_domain

    def test_an_index_over_the_identity_renders(self, keyed_domain, tmp_path):
        written = write_index_ddl(keyed_domain, str(tmp_path), ["mysql"])

        assert [p.name for p in written] == ["article.indexes.mysql.sql"]

    def test_an_oversized_key_is_rejected_before_any_file_is_written(
        self, wide_domain, tmp_path
    ):
        with pytest.raises(IncorrectUsageError) as exc:
            write_index_ddl(wide_domain, str(tmp_path), ["mysql"])

        assert "ix_wide" in str(exc.value)
        assert list(tmp_path.iterdir()) == []


class TestWriteIndexDDL:
    """Direct coverage of the writer used by the command."""

    @pytest.fixture
    def shop_domain(self, test_domain):
        @test_domain.aggregate(
            indexes=[
                Index(
                    "status",
                    "priority",
                    desc=("priority",),
                    where=Q(status="active"),
                    name="ix_active",
                ),
                Index("sku", unique=True),
            ]
        )
        class Product(BaseAggregate):
            status = String(max_length=32)
            priority = Integer()
            sku = String(max_length=64)

        test_domain.init(traverse=False)
        return test_domain

    def test_writes_one_file_per_dialect(self, shop_domain, tmp_path):
        written = write_index_ddl(shop_domain, str(tmp_path), ["postgresql", "sqlite"])
        names = sorted(p.name for p in written)
        assert names == [
            "product.indexes.postgresql.sql",
            "product.indexes.sqlite.sql",
        ]

    def test_mysql_and_mariadb_are_renderable_dialects(self, shop_domain, tmp_path):
        written = write_index_ddl(shop_domain, str(tmp_path), ["mysql", "mariadb"])
        names = sorted(p.name for p in written)
        assert names == [
            "product.indexes.mariadb.sql",
            "product.indexes.mysql.sql",
        ]

    def test_an_unknown_dialect_is_rejected(self, shop_domain, tmp_path):
        """It used to fall through to SQLite and write DDL for the wrong
        database under the requested dialect's filename."""
        with pytest.raises(IncorrectUsageError) as exc:
            write_index_ddl(shop_domain, str(tmp_path), ["postgres"])

        assert "postgres" in str(exc.value)
        assert list(tmp_path.iterdir()) == []

    def test_an_unknown_dialect_is_rejected_with_no_indexes_declared(
        self, test_domain, tmp_path
    ):
        """A domain with no indexes never reaches the renderer, so the check
        has to happen before the registry walk or the typo goes unreported."""
        test_domain.init(traverse=False)

        with pytest.raises(IncorrectUsageError) as exc:
            write_index_ddl(test_domain, str(tmp_path), ["postgres"])

        assert "postgres" in str(exc.value)

    def test_file_contains_create_index_ddl(self, shop_domain, tmp_path):
        written = write_index_ddl(shop_domain, str(tmp_path), ["postgresql"])
        assert len(written) == 1
        content = Path(written[0]).read_text(encoding="utf-8")
        assert "CREATE INDEX ix_active" in content
        assert "WHERE status = 'active'" in content
        assert "CREATE UNIQUE INDEX uq_product_sku" in content
        assert content.startswith("-- Generated by: protean schema render --indexes")

    def test_no_indexes_writes_nothing(self, test_domain, tmp_path):
        @test_domain.aggregate
        class Plain(BaseAggregate):
            name = String(max_length=32)

        test_domain.init(traverse=False)
        assert write_index_ddl(test_domain, str(tmp_path), ["sqlite"]) == []

    def test_skips_element_with_no_statements_for_dialect(self, test_domain, tmp_path):
        # Only a postgres RawIndex: rendering for sqlite yields no statements,
        # so nothing is written for that dialect.
        @test_domain.aggregate(
            indexes=[Index.from_sql("postgresql", "CREATE INDEX x ON only_a (a)")]
        )
        class OnlyA(BaseAggregate):
            a = String(max_length=10)

        test_domain.init(traverse=False)
        assert write_index_ddl(test_domain, str(tmp_path), ["sqlite"]) == []

    def test_dedups_by_schema_name_and_dialect(self, test_domain, tmp_path):
        # Two elements sharing a schema_name (as per-provider outbox clones do)
        # produce one file per (schema_name, dialect), not duplicates.
        @test_domain.aggregate(schema_name="shared", indexes=[Index("a")])
        class One(BaseAggregate):
            a = String(max_length=10)

        @test_domain.aggregate(schema_name="shared", indexes=[Index("b")])
        class Two(BaseAggregate):
            b = String(max_length=10)

        test_domain.init(traverse=False)
        written = write_index_ddl(test_domain, str(tmp_path), ["sqlite"])
        assert len(written) == 1


@pytest.mark.no_test_domain
class TestApplyCommandLive:
    def test_apply_writes_sql_files(self, tmp_path, monkeypatch):
        module = tmp_path / "shop_cli_domain.py"
        module.write_text(_DOMAIN_MODULE, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.syspath_prepend(str(tmp_path))

        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "render",
                "--indexes",
                "--domain=shop_cli_domain",
                "--dialects=postgresql,sqlite",
                f"--output={out}",
            ],
        )
        assert result.exit_code == 0, result.output
        pg = out / "schemas" / "Product" / "product.indexes.postgresql.sql"
        assert pg.exists()
        assert "CREATE INDEX ix_prod_active" in pg.read_text(encoding="utf-8")

    def test_mysql_render_reads_identity_type_off_a_pushed_context(
        self, tmp_path, monkeypatch
    ):
        """``load_domain`` initialises the domain but pushes no context, so the
        writer pushes one for the MySQL key-width guard."""
        module = tmp_path / "keyed_cli_domain.py"
        module.write_text(_IDENTITY_DOMAIN_MODULE, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.syspath_prepend(str(tmp_path))

        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "render",
                "--indexes",
                "--domain=keyed_cli_domain",
                "--dialects=mysql",
                f"--output={out}",
            ],
        )
        assert result.exit_code == 0, result.output
        ddl = out / "schemas" / "Article" / "article.indexes.mysql.sql"
        assert "CREATE INDEX ix_keyed" in ddl.read_text(encoding="utf-8")

    def test_apply_reports_when_no_indexes(self, tmp_path, monkeypatch):
        module = tmp_path / "plain_cli_domain.py"
        module.write_text(
            "from protean import Domain\n\n"
            'domain = Domain(name="PlainCLI")\n'
            'domain.config["databases"]["default"] = {\n'
            '    "provider": "sqlite", "database_uri": "sqlite:///:memory:"}\n\n\n'
            "@domain.aggregate\n"
            "class Thing:\n"
            "    name: str\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.syspath_prepend(str(tmp_path))

        result = runner.invoke(
            app, ["render", "--indexes", "--domain=plain_cli_domain"]
        )
        assert result.exit_code == 0, result.output
        assert "No index declarations" in result.output
