"""Column mapping for fields declared with ``choices``.

A field with ``choices`` resolves to a ``Literal`` of its values, so the adapter
has to read the column type off those values. Nothing here opens a connection:
each provider is built on its own against a memory-backed domain, and the DDL
is compiled offline. The live round trips sit in ``sqlite/`` and
``postgresql/``, and the SQL Server key-column check in ``mssql/``.
"""

import decimal
import enum

import pytest
from sqlalchemy import types as sa_types
from sqlalchemy.schema import CreateTable

from protean import Domain, Index
from protean.adapters.repository.sqlalchemy import (
    MysqlProvider,
    PostgresqlProvider,
    SqliteProvider,
    _check_mysql_index_key_widths,
    _resolve_python_type,
)
from protean.core.aggregate import BaseAggregate
from protean.exceptions import IncorrectUsageError
from protean.fields import Boolean, Float, Integer, String
from protean.fields import Decimal as ProteanDecimal
from protean.utils.reflection import attributes
from tests.shared import MARIADB_URI, MYSQL_URI, POSTGRES_URI

pytestmark = pytest.mark.no_test_domain


class Status(enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"


class MixedEnum(enum.Enum):
    NAMED = "named"
    NUMBERED = 1


class Graded(BaseAggregate):
    status: String(max_length=20, choices=["draft", "published"])
    required_status: String(
        max_length=20, choices=["draft", "published"], required=True
    )
    enum_status: String(max_length=20, choices=Status)
    level: Integer(choices=[1, 2, 3])
    required_level: Integer(choices=[1, 2, 3], required=True)
    ratio: Float(choices=[1.5, 2.5])
    flag: Boolean(choices=[True, False])
    price: ProteanDecimal(
        choices=[decimal.Decimal("1.50"), decimal.Decimal("2.50")],
        precision=5,
        scale=2,
    )
    mixed: String(max_length=20, choices=["a", 1])
    bool_and_int: String(max_length=20, choices=[True, 1])
    mixed_enum: String(max_length=20, choices=MixedEnum)


def host_domain(aggregates):
    domain = Domain(
        name="Choices mapping",
        config={
            "identity_type": "uuid",
            "databases": {"default": {"provider": "memory"}},
        },
    )
    for aggregate in aggregates:
        domain.register(aggregate)
    domain.init(traverse=False)
    return domain


def provider_for(dialect, domain):
    if dialect == "sqlite":
        return SqliteProvider(
            name="sqlite",
            domain=domain,
            conn_info={"provider": "sqlite", "database_uri": "sqlite:///:memory:"},
        )
    if dialect == "postgresql":
        return PostgresqlProvider(
            name="postgresql",
            domain=domain,
            conn_info={"provider": "postgresql", "database_uri": POSTGRES_URI},
        )
    uri = MARIADB_URI if dialect == "mariadb" else MYSQL_URI
    return MysqlProvider(
        name="mysql",
        domain=domain,
        conn_info={"provider": "mysql", "database_uri": uri},
    )


def table_and_engine(aggregate_cls, dialect):
    domain = host_domain([aggregate_cls])
    provider = provider_for(dialect, domain)
    with domain.domain_context():
        table = provider.construct_database_model_class(aggregate_cls).__table__
    return table, provider._engine


def on(dialects):
    """Parametrize over ``dialects`` with ids that are not test markers.

    The suite skips any test whose keywords include ``sqlite``, ``mysql`` and
    the like, and a bare dialect name as a parameter id is such a keyword.
    """
    return pytest.mark.parametrize(
        "dialect", dialects, ids=[f"on-{dialect}" for dialect in dialects]
    )


def compiled_type(aggregate_cls, dialect, attribute):
    table, engine = table_and_engine(aggregate_cls, dialect)
    return table.c[attribute].type.compile(dialect=engine.dialect)


class TestResolvedType:
    @pytest.mark.parametrize(
        ("attribute", "expected"),
        [
            ("status", str),
            ("required_status", str),
            ("enum_status", str),
            ("level", int),
            ("required_level", int),
            ("ratio", float),
            ("flag", bool),
            ("price", decimal.Decimal),
        ],
    )
    def test_choices_sharing_one_type_resolve_to_it(self, attribute, expected):
        assert _resolve_python_type(attributes(Graded)[attribute]) is expected

    @pytest.mark.parametrize("attribute", ["mixed", "bool_and_int", "mixed_enum"])
    def test_choices_of_mixed_types_stay_unresolved(self, attribute):
        """``True`` is an ``int`` to ``isinstance``, so ``[True, 1]`` is checked
        by exact type and counts as mixed."""
        assert _resolve_python_type(attributes(Graded)[attribute]) is None


class TestColumnDdl:
    @on(["sqlite", "postgresql", "mysql", "mariadb"])
    @pytest.mark.parametrize("attribute", ["status", "required_status", "enum_status"])
    def test_a_string_with_choices_keeps_its_max_length(self, dialect, attribute):
        assert compiled_type(Graded, dialect, attribute) == "VARCHAR(20)"

    @on(["sqlite", "postgresql", "mysql", "mariadb"])
    @pytest.mark.parametrize("attribute", ["level", "required_level"])
    def test_an_integer_with_choices_is_an_integer_column(self, dialect, attribute):
        assert compiled_type(Graded, dialect, attribute) == "INTEGER"

    @on(["sqlite", "postgresql"])
    def test_a_boolean_with_choices_is_a_boolean_column(self, dialect):
        assert compiled_type(Graded, dialect, "flag") == "BOOLEAN"

    @on(["sqlite", "postgresql", "mysql"])
    def test_a_decimal_with_choices_keeps_precision_and_scale(self, dialect):
        assert compiled_type(Graded, dialect, "price") == "NUMERIC(5, 2)"

    @pytest.mark.parametrize("attribute", ["mixed", "bool_and_int", "mixed_enum"])
    def test_mixed_choices_keep_an_unsized_string_column(self, attribute):
        table, _ = table_and_engine(Graded, "sqlite")
        column_type = table.c[attribute].type

        assert type(column_type) is sa_types.String
        assert column_type.length is None

    @on(["mysql", "mariadb"])
    def test_the_whole_create_table_has_no_text_for_a_sized_choice(self, dialect):
        table, engine = table_and_engine(Graded, dialect)
        ddl = str(CreateTable(table).compile(engine))

        assert "status VARCHAR(20)" in ddl
        assert "status TEXT" not in ddl


class TestMysqlKeyWidths:
    def test_a_unique_string_with_choices_and_a_max_length_builds(self):
        class UniqueStatus(BaseAggregate):
            status: String(max_length=20, choices=["draft", "published"], unique=True)

        table, _ = table_and_engine(UniqueStatus, "mysql")

        assert table.c["status"].type.length == 20
        assert table.c["status"].unique is True

    def test_a_unique_string_with_choices_and_no_max_length_is_rejected(self):
        """MySQL cannot index TEXT, so an unbounded key column still fails."""

        class UnboundedStatus(BaseAggregate):
            status: String(max_length=None, choices=["draft", "published"], unique=True)

        with pytest.raises(IncorrectUsageError) as exc:
            table_and_engine(UnboundedStatus, "mysql")

        assert "status" in str(exc.value)
        assert "max_length" in str(exc.value)

    def test_a_string_with_choices_counts_its_max_length(self):
        """700 characters is 2800 bytes and 70 more is 280: 3080 overruns the
        3072-byte cap only if the choices field is counted."""

        class WideChoices(BaseAggregate):
            slug: String(max_length=700)
            status: String(max_length=70, choices=["draft", "published"])

        index = Index("slug", "status", name="ix_slug_status")
        domain = host_domain([WideChoices])
        with domain.domain_context(), pytest.raises(IncorrectUsageError) as exc:
            _check_mysql_index_key_widths([index], WideChoices)

        assert "ix_slug_status" in str(exc.value)
        assert "3080 bytes" in str(exc.value)

    def test_an_integer_with_choices_counts_four_bytes(self):
        """A VARCHAR(768) fills the key exactly, so the four bytes of the
        Integer column put it over."""

        class FullKey(BaseAggregate):
            slug: String(max_length=768)
            level: Integer(choices=[1, 2, 3])

        index = Index("slug", "level", name="ix_slug_level")
        domain = host_domain([FullKey])
        with domain.domain_context(), pytest.raises(IncorrectUsageError) as exc:
            _check_mysql_index_key_widths([index], FullKey)

        assert "3076 bytes" in str(exc.value)
