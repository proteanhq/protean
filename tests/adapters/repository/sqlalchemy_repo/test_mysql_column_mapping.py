"""Column mapping, DDL and dialect handling for the MySQL provider.

Nothing here opens a connection. ``create_engine`` resolves a dialect from the
URI without talking to a server, and a provider constructed on its own (rather
than through ``domain.init()``) skips the liveness check, so every mapping
decision the adapter makes at model-construction time is pinned in the core
suite. The tests that need a live MySQL or MariaDB live in ``mysql/``.

Most of what is checked here fails silently on MySQL — a truncated timestamp, a
case-insensitive match, index DDL compiled for the wrong database — so the
assertion is the only thing standing between the adapter and a wrong answer.
"""

import logging

import pytest
from sqlalchemy import types as sa_types
from sqlalchemy.dialects import mysql as mysql_dialect
from sqlalchemy.schema import CreateTable

from protean import Domain, Index, Q
from protean.adapters.repository.sqlalchemy import (
    _MYSQL_DEFAULT_COLLATION,
    _MYSQL_DIALECTS,
    SADAO,
    MysqlProvider,
    PostgresqlProvider,
    SqliteProvider,
    _check_mysql_index_key_widths,
    _mysql_table_kwargs,
    render_index_ddl,
)
from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.exceptions import ConfigurationError, IncorrectUsageError
from protean.fields import DateTime, Dict, Integer, List, String, Text, ValueObject
from protean.port.provider import DatabaseCapabilities
from protean.utils import Database
from tests.shared import MARIADB_URI, MYSQL_URI, POSTGRES_URI

pytestmark = pytest.mark.no_test_domain


def host_domain(aggregates, indexes=None, identity_type="uuid"):
    """A memory-backed domain that owns the registered aggregates.

    The MySQL provider is built separately against this domain, so nothing in
    this module needs a running server. Column mapping reads ``identity_type``
    off the active domain, hence the explicit ``uuid`` setting.
    """
    domain = Domain(
        name="MySQL mapping",
        config={
            "identity_type": identity_type,
            "databases": {"default": {"provider": "memory"}},
        },
    )
    for aggregate in aggregates:
        domain.register(aggregate, **({"indexes": indexes} if indexes else {}))
    domain.init(traverse=False)
    return domain


def mysql_provider(domain, uri=MYSQL_URI, **config):
    return MysqlProvider(
        name="mysql",
        domain=domain,
        conn_info={"provider": "mysql", "database_uri": uri, **config},
    )


def table_for(
    aggregate_cls, uri=MYSQL_URI, indexes=None, identity_type="uuid", **config
):
    """The SQLAlchemy ``Table`` the MySQL provider builds for ``aggregate_cls``."""
    domain = host_domain([aggregate_cls], indexes=indexes, identity_type=identity_type)
    provider = mysql_provider(domain, uri, **config)
    with domain.domain_context():
        return provider.construct_database_model_class(aggregate_cls).__table__


class Article(BaseAggregate):
    title: String(max_length=50)
    body: Text()
    unbounded: String(max_length=None)
    published_at: DateTime()
    tags: List()
    extra: Dict()
    views: Integer()


class TestDialectNames:
    """SQLAlchemy names the same provider two ways, so both have to be handled."""

    def test_the_dialect_set_covers_both_names(self):
        assert sorted(_MYSQL_DIALECTS) == ["mariadb", "mysql"]

    @pytest.mark.parametrize(
        ("uri", "expected"),
        [(MYSQL_URI, "mysql"), (MARIADB_URI, "mariadb")],
        ids=["mysql-uri", "mariadb-uri"],
    )
    def test_dialect_name_for_each_uri_scheme(self, uri, expected):
        provider = mysql_provider(host_domain([]), uri)

        assert provider._engine.dialect.name == expected


class TestProviderConfiguration:
    def test_capabilities_include_json_and_exclude_array(self):
        capabilities = mysql_provider(host_domain([])).capabilities

        assert DatabaseCapabilities.RELATIONAL in capabilities
        assert DatabaseCapabilities.NATIVE_JSON in capabilities
        assert DatabaseCapabilities.NATIVE_ARRAY not in capabilities

    def test_engine_runs_at_read_committed(self):
        """InnoDB's REPEATABLE READ default breaks the ADR-0027 UoW contract."""
        args = mysql_provider(host_domain([]))._get_database_specific_engine_args()

        assert args["isolation_level"] == "READ COMMITTED"

    def test_connection_charset_is_pinned(self):
        args = mysql_provider(host_domain([]))._get_database_specific_engine_args()

        assert args["connect_args"]["charset"] == "utf8mb4"

    def test_caller_connect_args_cannot_drop_the_charset(self):
        """``_additional_engine_args`` overlays every unrecognised conn_info key
        onto the defaults, so a caller's own ``connect_args`` replaced this
        provider's dict wholesale and took ``charset`` with it — silently
        restoring the 4-byte-character failure the pin exists to prevent."""
        provider = mysql_provider(
            host_domain([]), connect_args={"read_timeout": 5, "charset": "latin1"}
        )
        connect_args = provider._additional_engine_args()["connect_args"]

        assert connect_args["charset"] == "utf8mb4"
        # The caller's other keys survive; only charset is reasserted.
        assert connect_args["read_timeout"] == 5

    def test_collation_is_not_forwarded_to_create_engine(self):
        """It is provider config, not a SQLAlchemy engine argument.

        ``_additional_engine_args`` forwards every unrecognised ``conn_info``
        key to ``create_engine``, which rejects an unknown keyword, so a
        provider adding a config key has to exclude it explicitly.
        """
        provider = mysql_provider(host_domain([]), collation="utf8mb4_bin")
        args = provider._additional_engine_args()

        assert "collation" not in args
        assert args["connect_args"]["charset"] == "utf8mb4"

    def test_collation_default_and_override(self):
        assert mysql_provider(host_domain([])).collation == _MYSQL_DEFAULT_COLLATION
        assert (
            mysql_provider(host_domain([]), collation="utf8mb4_bin").collation
            == "utf8mb4_bin"
        )

    def test_the_charset_is_pinned(self):
        """A narrower charset cannot hold the 4-byte characters Protean stores,
        so it is not a config key."""
        assert mysql_provider(host_domain([])).charset == "utf8mb4"

    @pytest.mark.parametrize("value", ["", "   ", False, 0, 123, None])
    def test_a_falsy_or_non_string_collation_is_rejected(self, value):
        """A plain ``or`` default would let every falsy value through in
        silence, so a config wrong in a falsy way would be accepted while the
        same mistake spelled truthily raised."""
        with pytest.raises(ConfigurationError) as exc:
            mysql_provider(host_domain([]), collation=value)

        assert "collation" in str(exc.value)

    def test_an_absent_collation_takes_the_default(self):
        """Absence is the only thing that falls back."""
        assert mysql_provider(host_domain([])).collation == _MYSQL_DEFAULT_COLLATION

    def test_a_collation_from_another_charset_is_rejected(self):
        """MySQL rejects the pair at CREATE TABLE with "COLLATION ... is not
        valid for CHARACTER SET ..."; this names the config key instead."""
        with pytest.raises(ConfigurationError) as exc:
            mysql_provider(host_domain([]), collation="latin1_general_cs")

        assert "latin1_general_cs" in str(exc.value)
        assert "utf8mb4" in str(exc.value)


class TestColumnTypes:
    def test_string_with_max_length_is_a_varchar(self):
        column = table_for(Article).c["title"]

        assert isinstance(column.type, sa_types.String)
        assert column.type.length == 50

    @pytest.mark.parametrize("attribute", ["body", "unbounded"])
    def test_a_string_with_no_length_becomes_text(self, attribute):
        """MySQL cannot create a VARCHAR with no length.

        Every other provider accepts the field, so the column is widened rather
        than the domain rejected.
        """
        column = table_for(Article).c[attribute]

        assert isinstance(column.type, sa_types.Text)
        assert column.type.length is None

    def test_datetime_keeps_microseconds(self):
        """A plain DATETIME has zero fractional-second digits and drops them."""
        column = table_for(Article).c["published_at"]

        assert isinstance(column.type, mysql_dialect.DATETIME)
        assert column.type.fsp == 6

    @pytest.mark.parametrize("attribute", ["tags", "extra"])
    def test_dict_and_list_map_to_json(self, attribute):
        """MySQL has a JSON type and no array type, so a list goes to JSON too."""
        column = table_for(Article).c[attribute]

        assert isinstance(column.type, mysql_dialect.JSON)

    def test_uuid_identifier_compiles_to_char_32(self):
        column = table_for(Article).c["id"]
        dialect = mysql_provider(host_domain([]))._engine.dialect

        assert column.type.compile(dialect=dialect) == "CHAR(32)"

    def test_integer_is_left_alone(self):
        column = table_for(Article).c["views"]

        assert isinstance(column.type, sa_types.Integer)
        assert not isinstance(column.type, mysql_dialect.DATETIME)


class TestKeyColumnGuards:
    """InnoDB caps an index key at 3072 bytes, which is 768 utf8mb4 characters."""

    def test_unique_string_with_no_length_is_rejected(self):
        class Unbounded(BaseAggregate):
            slug: String(max_length=None, unique=True)

        domain = host_domain([Unbounded])
        provider = mysql_provider(domain)
        with domain.domain_context(), pytest.raises(IncorrectUsageError) as exc:
            provider.construct_database_model_class(Unbounded)

        assert "slug" in str(exc.value)
        assert "max_length" in str(exc.value)

    def test_unique_string_longer_than_the_key_limit_is_rejected(self):
        class TooWide(BaseAggregate):
            slug: String(max_length=769, unique=True)

        domain = host_domain([TooWide])
        provider = mysql_provider(domain)
        with domain.domain_context(), pytest.raises(IncorrectUsageError) as exc:
            provider.construct_database_model_class(TooWide)

        assert "slug" in str(exc.value)
        assert "768" in str(exc.value)

    def test_a_string_at_the_key_limit_is_accepted(self):
        class AtLimit(BaseAggregate):
            slug: String(max_length=768, unique=True)

        assert table_for(AtLimit).c["slug"].type.length == 768

    def test_a_long_string_that_is_not_a_key_is_accepted(self):
        """The cap is an index limit, so an unindexed column is unaffected."""

        class LongProse(BaseAggregate):
            essay: String(max_length=4000)

        assert table_for(LongProse).c["essay"].type.length == 4000


class TestDeclaredIndexKeyWidths:
    """InnoDB caps the whole index key at 3072 bytes. The column-level guard
    only sees a field's own identifier/unique flags, so an index declared
    through the public ``Index(...)`` API used to reach ``create_all()`` and
    fail there with MySQL's own message."""

    def test_a_single_wide_field_is_rejected(self):
        class WideIndexed(BaseAggregate):
            slug: String(max_length=769)

        with pytest.raises(IncorrectUsageError) as exc:
            table_for(WideIndexed, indexes=[Index("slug", name="ix_wide")])

        assert "ix_wide" in str(exc.value)
        assert "slug" in str(exc.value)
        assert "3072" in str(exc.value)

    def test_a_composite_index_sums_its_fields(self):
        """Each field fits on its own; together they overrun the key."""

        class Composite(BaseAggregate):
            first: String(max_length=500)
            second: String(max_length=500)

        with pytest.raises(IncorrectUsageError) as exc:
            table_for(Composite, indexes=[Index("first", "second", name="ix_both")])

        assert "first, second" in str(exc.value)
        assert "4000 bytes" in str(exc.value)

    def test_a_text_field_cannot_be_indexed(self):
        """An unbounded string maps to TEXT, which InnoDB cannot index without
        a prefix length."""

        class Prose(BaseAggregate):
            essay: Text()

        with pytest.raises(IncorrectUsageError) as exc:
            table_for(Prose, indexes=[Index("essay", name="ix_essay")])

        assert "essay" in str(exc.value)

    def test_an_index_within_the_cap_is_accepted(self):
        class Fits(BaseAggregate):
            slug: String(max_length=768)

        table = table_for(Fits, indexes=[Index("slug", name="ix_fits")])

        assert "ix_fits" in {index.name for index in table.indexes}

    def test_non_string_columns_do_not_count_against_the_cap(self):
        """A UUID identity is CHAR(32) and an Integer is 4 bytes; neither can
        approach the cap, so only string widths are summed."""

        class Mixed(BaseAggregate):
            slug: String(max_length=700)
            rank: Integer()

        table = table_for(Mixed, indexes=[Index("slug", "rank", "id", name="ix_mix")])

        assert "ix_mix" in {index.name for index in table.indexes}

    def test_a_string_identity_counts_toward_the_key(self):
        """An identifier is sized by the domain's identity_type, not by its own
        max_length: a string identity is VARCHAR(255), 1020 bytes."""

        class KeyedByString(BaseAggregate):
            slug: String(max_length=600)

        with pytest.raises(IncorrectUsageError) as exc:
            table_for(
                KeyedByString,
                indexes=[Index("id", "slug", name="ix_str_id")],
                identity_type="string",
            )

        assert "3420 bytes" in str(exc.value)

    def test_a_uuid_identity_is_char_32_not_varchar_255(self):
        """The same index fits when the identity is a UUID, because CHAR(32) is
        128 bytes rather than 1020."""

        class KeyedByUuid(BaseAggregate):
            slug: String(max_length=600)

        table = table_for(KeyedByUuid, indexes=[Index("id", "slug", name="ix_uuid_id")])

        assert "ix_uuid_id" in {index.name for index in table.indexes}

    def test_a_value_object_field_is_not_measured(self):
        """A value object flattens into shadow columns and is not a
        ``ResolvedField``, so it contributes no width of its own.

        Checked against the helper rather than a built model: indexing a value
        object by its logical name fails later in the index builder, which
        resolves `price` against the model's `price_amount` / `price_currency`
        shadow columns. That is a pre-existing limitation shared by every SQL
        provider, so it is not what this test is about.
        """

        class Money(BaseValueObject):
            amount: Integer()
            currency: String(max_length=3)

        class Priced(BaseAggregate):
            price: ValueObject(Money)
            slug: String(max_length=700)

        domain = host_domain([])
        domain.register(Money)
        domain.register(Priced)
        domain.init(traverse=False)

        # 700 chars is 2800 bytes; the value object adds nothing, so this is
        # under the cap and must not raise.
        _check_mysql_index_key_widths(
            [Index("price", "slug", name="ix_priced")], Priced
        )

    def test_a_non_field_index_entry_is_skipped(self):
        """``Index.from_sql`` produces a RawIndex, whose verbatim DDL the
        framework does not measure."""

        class Raw(BaseAggregate):
            slug: String(max_length=769)

        table = table_for(
            Raw,
            indexes=[
                Index.from_sql(
                    "mysql", "CREATE INDEX ix_raw ON raw (slug(50))", name="ix_raw"
                )
            ],
        )

        assert table is not None

    def test_a_value_object_shadow_column_is_measured(self):
        """``validate_indexes`` accepts an index over a value object's shadow
        column, so the guard has to resolve one. A ``_ShadowField`` carries no
        ``max_length`` of its own, so the width comes from the value object's
        field underneath it.
        """

        class Profile(BaseValueObject):
            bio: String(max_length=900)

        class Author(BaseAggregate):
            profile: ValueObject(Profile)

        domain = host_domain([])
        domain.register(Profile)
        domain.register(Author, indexes=[Index("profile_bio", name="ix_bio")])
        domain.init(traverse=False)

        with pytest.raises(IncorrectUsageError) as exc:
            _check_mysql_index_key_widths([Index("profile_bio", name="ix_bio")], Author)

        assert "profile_bio" in str(exc.value)
        assert "3600 bytes" in str(exc.value)

    def test_an_unbounded_value_object_shadow_column_is_rejected(self):
        """The case that used to reach ``create_all()`` and fail with MySQL's
        own 1071, which is the error this guard exists to replace."""

        class Handle(BaseValueObject):
            nickname: String(max_length=None)

        class Member(BaseAggregate):
            handle: ValueObject(Handle)

        domain = host_domain([])
        domain.register(Handle)
        domain.register(Member, indexes=[Index("handle_nickname", name="ix_nick")])
        domain.init(traverse=False)

        with pytest.raises(IncorrectUsageError) as exc:
            _check_mysql_index_key_widths(
                [Index("handle_nickname", name="ix_nick")], Member
            )

        assert "handle_nickname" in str(exc.value)
        assert "no max_length" in str(exc.value)

    def test_a_shadow_column_within_the_cap_is_accepted(self):
        class Address(BaseValueObject):
            city: String(max_length=100)

        class Store(BaseAggregate):
            address: ValueObject(Address)

        domain = host_domain([])
        domain.register(Address)
        domain.register(Store, indexes=[Index("address_city", name="ix_city")])
        domain.init(traverse=False)

        _check_mysql_index_key_widths([Index("address_city", name="ix_city")], Store)

    def test_the_guard_is_mysql_only(self):
        """PostgreSQL has no such cap, so the same declaration is fine there."""

        class WideElsewhere(BaseAggregate):
            slug: String(max_length=769)

        domain = host_domain([WideElsewhere], indexes=[Index("slug", name="ix_pg")])
        provider = PostgresqlProvider(
            name="postgresql",
            domain=domain,
            conn_info={"provider": "postgresql", "database_uri": POSTGRES_URI},
        )
        with domain.domain_context():
            table = provider.construct_database_model_class(WideElsewhere).__table__

        assert "ix_pg" in {index.name for index in table.indexes}


class TestTableArgs:
    """SQLAlchemy ignores a dialect table-kwarg prefix that does not match the
    dialect — ``mysql_charset`` on the ``mariadb`` dialect emits no CHARSET
    clause and raises nothing — so the prefix comes from the live dialect name.
    """

    @pytest.mark.parametrize(
        ("uri", "dialect"),
        [(MYSQL_URI, "mysql"), (MARIADB_URI, "mariadb")],
        ids=["mysql-uri", "mariadb-uri"],
    )
    def test_table_declares_charset_and_collation(self, uri, dialect):
        domain = host_domain([Article])
        provider = mysql_provider(domain, uri)
        with domain.domain_context():
            table = provider.construct_database_model_class(Article).__table__
        ddl = str(CreateTable(table).compile(provider._engine))

        assert table.kwargs[f"{dialect}_charset"] == "utf8mb4"
        assert table.kwargs[f"{dialect}_collate"] == _MYSQL_DEFAULT_COLLATION
        assert "CHARSET=utf8mb4" in ddl
        assert f"COLLATE {_MYSQL_DEFAULT_COLLATION}" in ddl

    def test_no_kwargs_for_a_dialect_that_is_not_mysql(self):
        """The helper runs for every dialect; only MySQL gets table kwargs."""
        assert _mysql_table_kwargs("postgresql", {}) == {}
        assert _mysql_table_kwargs("sqlite", {"collation": "utf8mb4_bin"}) == {}

    def test_a_non_mysql_provider_carries_no_type_options(self):
        """`_type_options` is the seam the MySQL provider fills; the base
        provider leaves it empty, so nothing else changes shape."""
        provider = SqliteProvider(
            name="sqlite",
            domain=host_domain([]),
            conn_info={"provider": "sqlite", "database_uri": "sqlite:///:memory:"},
        )

        assert provider._model_type_options() == {}

    def test_a_collation_override_reaches_the_table(self):
        domain = host_domain([Article])
        provider = mysql_provider(domain, collation="utf8mb4_bin")
        with domain.domain_context():
            table = provider.construct_database_model_class(Article).__table__

        assert table.kwargs["mysql_charset"] == "utf8mb4"
        assert table.kwargs["mysql_collate"] == "utf8mb4_bin"


class IndexedJob(BaseAggregate):
    owner: String(max_length=50)
    status: String(max_length=20)


class TestIndexDdl:
    @pytest.mark.parametrize(
        "dialect", ["mysql", "mariadb"], ids=["mysql-dialect", "mariadb-dialect"]
    )
    def test_index_ddl_renders_for_both_dialect_names(self, dialect):
        host_domain([IndexedJob], indexes=[Index("owner", "status", name="ix_owner")])

        assert render_index_ddl(IndexedJob, dialect) == [
            "CREATE INDEX ix_owner ON indexed_job (owner, status)"
        ]

    def test_an_unknown_dialect_is_rejected(self):
        """It used to fall through to SQLite and emit DDL for the wrong database."""
        host_domain([IndexedJob], indexes=[Index("owner", name="ix_owner")])

        with pytest.raises(IncorrectUsageError) as exc:
            render_index_ddl(IndexedJob, "orcale")

        assert "orcale" in str(exc.value)
        assert "mysql" in str(exc.value)


class WideSlug(BaseAggregate):
    slug: String(max_length=769)


class TestRenderPathKeyWidths:
    """The rendered ``.sql`` artifact is meant to be applied, so the offline
    renderer runs the same key-width guard the live model builder runs. It used
    to emit DDL InnoDB rejects at apply time.
    """

    @pytest.mark.parametrize(
        "dialect", ["mysql", "mariadb"], ids=["mysql-dialect", "mariadb-dialect"]
    )
    def test_an_oversized_key_is_rejected_on_the_render_path(self, dialect):
        host_domain([WideSlug], indexes=[Index("slug", name="ix_wide")])

        with pytest.raises(IncorrectUsageError) as exc:
            render_index_ddl(WideSlug, dialect)

        assert "ix_wide" in str(exc.value)
        assert "3076 bytes" in str(exc.value)

    def test_other_dialects_still_render_the_same_declaration(self):
        """PostgreSQL has no such cap, so nothing changes there."""
        host_domain([WideSlug], indexes=[Index("slug", name="ix_wide")])

        assert render_index_ddl(WideSlug, "postgresql") == [
            "CREATE INDEX ix_wide ON wide_slug (slug)"
        ]


class PartialJob(BaseAggregate):
    owner: String(max_length=50)
    status: String(max_length=20)


class TestUnsupportedIndexFeatures:
    """MySQL has neither partial nor covering indexes; both degrade to a full
    index with a warning, which is behaviour the adapter already had for any
    unlisted dialect. These pin that it holds for MySQL."""

    def test_partial_index_warns_and_emits_a_full_index(self, caplog):
        host_domain(
            [PartialJob],
            indexes=[Index("status", name="ix_partial", where=Q(status="open"))],
        )

        with caplog.at_level(logging.WARNING):
            ddl = render_index_ddl(PartialJob, "mysql")

        assert ddl == ["CREATE INDEX ix_partial ON partial_job (status)"]
        assert "does not support" in caplog.text

    def test_covering_index_warns_and_drops_the_included_columns(self, caplog):
        host_domain(
            [PartialJob],
            indexes=[Index("status", name="ix_covering", include=["owner"])],
        )

        with caplog.at_level(logging.WARNING):
            ddl = render_index_ddl(PartialJob, "mysql")

        assert ddl == ["CREATE INDEX ix_covering ON partial_job (status)"]
        assert "does not support" in caplog.text


class TestPortableStatementPaths:
    """Two single-statement fast paths are PostgreSQL-shaped; MySQL takes neither."""

    @pytest.mark.parametrize(
        "dialect", ["mysql", "mariadb"], ids=["mysql-dialect", "mariadb-dialect"]
    )
    def test_claim_falls_back_to_the_portable_path(self, dialect):
        """MySQL has SKIP LOCKED but no UPDATE ... RETURNING."""
        assert dialect not in SADAO._SKIP_LOCKED_DIALECTS

    @pytest.mark.parametrize(
        "dialect", ["mysql", "mariadb"], ids=["mysql-dialect", "mariadb-dialect"]
    )
    def test_bounded_delete_falls_back_to_the_portable_path(self, dialect):
        """MySQL rejects a subquery that reads the table being deleted from."""
        assert dialect not in SADAO._BOUNDED_DELETE_DIALECTS


class TestRepositoryBinding:
    """``@domain.repository(database=...)`` validates against this enum, so a
    provider missing from it cannot be named even when it is registered."""

    def test_enum_lists_every_sql_provider(self):
        names = {member.value for member in Database}

        assert {"mysql", "mssql", "postgresql", "sqlite"} <= names
