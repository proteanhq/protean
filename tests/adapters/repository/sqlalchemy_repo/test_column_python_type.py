"""The column type the SQLAlchemy adapter picks from a field's Python type.

Fields declared with ``choices`` resolve through a ``Literal`` and are covered
in ``test_choices_column_mapping.py``. Nothing here opens a connection: the
providers are built against a memory-backed domain and the DDL is compiled
offline.
"""

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from protean import Domain
from protean.adapters.repository.sqlalchemy import PostgresqlProvider, SqliteProvider
from protean.core.aggregate import BaseAggregate
from protean.fields import Dict, String
from tests.shared import POSTGRES_URI

pytestmark = pytest.mark.no_test_domain


class Profile(BaseAggregate):
    name: String(max_length=50, required=True)
    nickname: String(max_length=50)
    tags: list[str]
    settings: Dict()
    counts: dict[str, int]


PROVIDERS = {
    "sqlite": (SqliteProvider, "sqlite:///:memory:", sqlite.dialect()),
    "postgresql": (PostgresqlProvider, POSTGRES_URI, postgresql.dialect()),
}


def column_type(dialect_name, attribute):
    domain = Domain(
        name="Column types", config={"databases": {"default": {"provider": "memory"}}}
    )
    domain.register(Profile)
    domain.init(traverse=False)
    provider_cls, uri, dialect = PROVIDERS[dialect_name]
    provider = provider_cls(
        name=dialect_name,
        domain=domain,
        conn_info={"provider": dialect_name, "database_uri": uri},
    )
    with domain.domain_context():
        table = provider.construct_database_model_class(Profile).__table__
    return table.c[attribute].type.compile(dialect=dialect)


# A bare dialect name as a parameter id is a test marker the suite skips on.
on_both = pytest.mark.parametrize(
    "dialect_name", ["sqlite", "postgresql"], ids=["on-sqlite", "on-postgresql"]
)


class TestColumnTypeFromPythonType:
    @on_both
    def test_a_required_string_is_a_sized_varchar(self, dialect_name):
        assert column_type(dialect_name, "name") == "VARCHAR(50)"

    @on_both
    def test_an_optional_string_is_a_sized_varchar(self, dialect_name):
        """An optional field is ``str | None``; the ``None`` arm is dropped."""
        assert column_type(dialect_name, "nickname") == "VARCHAR(50)"

    @pytest.mark.parametrize(
        ("dialect_name", "expected"),
        [("sqlite", "JSON"), ("postgresql", "VARCHAR[]")],
        ids=["on-sqlite", "on-postgresql"],
    )
    def test_a_typed_list_is_a_list_column(self, dialect_name, expected):
        assert column_type(dialect_name, "tags") == expected

    @on_both
    @pytest.mark.parametrize("attribute", ["settings", "counts"])
    def test_a_dict_field_is_a_json_column(self, dialect_name, attribute):
        """``Dict()`` is ``dict | list`` and maps by its first arm.
        ``dict[str, int]`` maps without its type arguments."""
        assert column_type(dialect_name, attribute) == "JSON"
