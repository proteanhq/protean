"""The DDL the SQLAlchemy providers emit, pinned against a committed golden file.

Each case registers a set of elements in a memory-backed domain. For every
SQLAlchemy dialect, a provider built on its own (no liveness check, so no
server) constructs the model class of each element, and the test records the
``CREATE TABLE``, every ``CREATE INDEX`` and every raw ``after_create`` DDL the
table would emit, compiled for that dialect. Where building the model raises,
the test records the exception type and message instead, so the key-column
guards are pinned too.

The golden file was generated from the model builder before its column-mapping
code was split into helpers, so any change to the emitted schema shows up as a
diff. To regenerate it after a deliberate schema change, run this module with
``PROTEAN_REGEN_DDL_GOLDEN=1`` and review the diff of ``ddl_golden.json``.
"""

import importlib.util
import itertools
import json
import os
from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy import Column, create_mock_engine
from sqlalchemy import Integer as SAInteger
from sqlalchemy import String as SAString

from protean import Domain, Index, Q
from protean.adapters.repository.sqlalchemy import (
    MssqlProvider,
    MysqlProvider,
    PostgresqlProvider,
    SqliteProvider,
    render_index_ddl,
)
from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.exceptions import ConfigurationError, IncorrectUsageError
from protean.fields import (
    Auto,
    Boolean,
    Date,
    DateTime,
    Dict,
    Float,
    HasMany,
    HasOne,
    Identifier,
    Integer,
    List,
    String,
    Text,
    ValueObject,
    ValueObjectList,
)
from protean.fields import Decimal as ProteanDecimal
from tests.shared import MARIADB_URI, MSSQL_URI, MYSQL_URI, POSTGRES_URI

from .mssql import elements as mssql_elements
from .postgresql import elements as postgresql_elements

pytestmark = pytest.mark.no_test_domain

GOLDEN_FILE = Path(__file__).with_name("ddl_golden.json")
REGENERATE = os.environ.get("PROTEAN_REGEN_DDL_GOLDEN") == "1"

# Dialect name, provider class, URI, and the DBAPI module the provider imports.
DIALECTS = [
    ("sqlite", SqliteProvider, "sqlite://", "sqlite3"),
    ("postgresql", PostgresqlProvider, POSTGRES_URI, "psycopg2"),
    ("mssql", MssqlProvider, MSSQL_URI, "pyodbc"),
    ("mysql", MysqlProvider, MYSQL_URI, "pymysql"),
    ("mariadb", MysqlProvider, MARIADB_URI, "pymysql"),
]


_counter = itertools.count(1)


def next_int():
    return next(_counter)


class Measure(BaseValueObject):
    amount: Float()
    unit: String(max_length=10)


class Address(BaseValueObject):
    street: String(max_length=100)
    city: String(max_length=50)


class Catalogue(BaseAggregate):
    """One column of every kind the model builder maps."""

    title: String(max_length=100, required=True)
    slug: String(max_length=60, unique=True)
    summary: Text()
    unbounded: String(max_length=None)
    pages: Integer()
    rating: Float()
    active: Boolean(default=True)
    published_on: Date()
    published_at: DateTime()
    price: ProteanDecimal(precision=10, scale=2)
    loose_price: ProteanDecimal()
    attributes: Dict()
    tags: List()
    labels: List(content_type=String(max_length=20))
    counts: List(content_type=Integer())
    plain_counts: List(content_type=int)
    blobs: List(content_type=Dict())
    measures: List(content_type=ValueObject(Measure))
    address = ValueObject(Address)
    legacy_measures = ValueObjectList(content_type=ValueObject(Measure))
    pickled_measures = ValueObjectList(content_type=ValueObject(Measure), pickled=True)
    legacy_names = ValueObjectList(content_type=str)
    sequence: Auto(increment=True)
    external_id: Identifier()
    status: String(max_length=10, choices=("open", "closed"))
    level: Integer(choices=(1, 2, 3))
    bare_list: list | None = None
    mixed_choice: Literal["a", 1] | None = None
    measure_obj: Measure | None = None


class Shelf(BaseAggregate):
    """An aggregate whose entities carry reference columns."""

    name: String(max_length=50)
    books = HasMany("Book")
    label = HasOne("Label")


class Book(BaseEntity):
    title: String(max_length=100)
    published_at: DateTime(required=True)


class Label(BaseEntity):
    text: String(max_length=30)


class KeyedByString(BaseAggregate):
    code: String(identifier=True, max_length=20)
    name: String(max_length=50)


class UnboundedUnique(BaseAggregate):
    handle: Text(unique=True)


class WideUnique(BaseAggregate):
    handle: String(max_length=1000, unique=True)


class UniqueAttributes(BaseAggregate):
    attributes: Dict(unique=True)


class PickledKey(BaseAggregate):
    measures = ValueObjectList(
        content_type=ValueObject(Measure), pickled=True, unique=True
    )


class IndexedJob(BaseAggregate):
    status: String(max_length=32, default="pending")
    priority: Integer(default=0)
    message_id: String(max_length=64)
    correlation_id: String(max_length=64)
    note: String(max_length=200)


INDEXED_JOB_INDEXES = [
    Index(
        "status",
        "priority",
        desc=("priority",),
        where=Q(status__in=["pending", "failed"]),
        name="ix_job_active",
    ),
    Index(
        "status",
        where=Q(status="failed") | ~Q(priority__gt=3),
        name="ix_job_failed_or_low",
    ),
    Index("message_id", unique=True),
    Index("correlation_id", include=("note",)),
    Index.from_sql("postgresql", "CREATE INDEX ix_job_pg ON indexed_job (note)"),
    Index.from_sql("sqlite", "CREATE INDEX ix_job_lite ON indexed_job (note)"),
    Index.from_sql("mssql", "CREATE INDEX ix_job_ms ON indexed_job (note)"),
    Index.from_sql("mysql", "CREATE INDEX ix_job_my ON indexed_job (note)"),
]


class SizedKeys(BaseAggregate):
    """Fixed-width and bounded columns, which fit InnoDB's key cap."""

    flag: Boolean()
    count: Integer()
    ratio: Float()
    day: Date()
    at: DateTime()
    amount: ProteanDecimal(precision=12, scale=3)
    loose_amount: ProteanDecimal()
    code: String(max_length=100)
    address = ValueObject(Address)


SIZED_KEYS_INDEXES = [
    Index("flag", "count", "ratio", "day", "at", "amount", "loose_amount", "code"),
    Index("id", "code"),
    Index("address_city"),
]


class JsonKey(BaseAggregate):
    tags: List()


class TextKey(BaseAggregate):
    body: Text()


class WideKey(BaseAggregate):
    first: String(max_length=700)
    second: String(max_length=100)


class VOListKey(BaseAggregate):
    measures = ValueObjectList(content_type=ValueObject(Measure))


class PickledVOListKey(BaseAggregate):
    measures = ValueObjectList(content_type=ValueObject(Measure), pickled=True)


class Ticket(BaseAggregate):
    subject: String(max_length=100)
    body: String(max_length=500)


class TicketModel(BaseDatabaseModel):
    subject = Column(SAString(80))
    __table_args__ = {"comment": "tickets"}


class Counter(BaseAggregate):
    """Takes its identity from the domain's ``identity_type``."""

    total: Integer()


class CounterItem(BaseEntity):
    amount: Integer()


class CounterWithItems(BaseAggregate):
    items = HasMany(CounterItem)


class Incremented(BaseAggregate):
    seq: Auto(identifier=True, increment=True)


class IntegerKeyed(BaseAggregate):
    code: Integer(identifier=True)


class ModelledCounter(BaseAggregate):
    total: Integer()


class ModelledCounterModel(BaseDatabaseModel):
    id = Column(SAInteger, primary_key=True)


class StringIdInIntegerDomain(BaseAggregate):
    ref: Auto(identifier=True, identity_type="string")


UUID_DOMAIN = {"identity_type": "uuid"}
STRING_DOMAIN = {"identity_type": "string"}

# Each case: (name, domain config, [(element, register kwargs)], {element: model}).
CASES = [
    ("fields", UUID_DOMAIN, [(Catalogue, {})], {}),
    (
        "associations",
        UUID_DOMAIN,
        [
            (Shelf, {}),
            (Book, {"part_of": Shelf, "indexes": [Index("shelf_id")]}),
            (Label, {"part_of": Shelf}),
        ],
        {},
    ),
    (
        "string_associations",
        STRING_DOMAIN,
        [
            (Shelf, {}),
            (Book, {"part_of": Shelf, "indexes": [Index("shelf_id")]}),
            (Label, {"part_of": Shelf}),
        ],
        {},
    ),
    (
        "keys",
        UUID_DOMAIN,
        [
            (KeyedByString, {}),
            (UnboundedUnique, {}),
            (WideUnique, {}),
            (UniqueAttributes, {}),
            (PickledKey, {}),
        ],
        {},
    ),
    ("indexes", UUID_DOMAIN, [(IndexedJob, {"indexes": INDEXED_JOB_INDEXES})], {}),
    (
        "index_widths",
        UUID_DOMAIN,
        [
            (SizedKeys, {"indexes": SIZED_KEYS_INDEXES}),
            (JsonKey, {"indexes": [Index("tags")]}),
            (TextKey, {"indexes": [Index("body")]}),
            (WideKey, {"indexes": [Index("first", "second")]}),
            (VOListKey, {"indexes": [Index("measures")]}),
            (PickledVOListKey, {"indexes": [Index("measures")]}),
        ],
        {},
    ),
    (
        "string_index_widths",
        STRING_DOMAIN,
        [(SizedKeys, {"indexes": SIZED_KEYS_INDEXES})],
        {},
    ),
    (
        "custom_model",
        UUID_DOMAIN,
        [(Ticket, {"indexes": [Index("subject", "body")]})],
        {Ticket: TicketModel},
    ),
    (
        "integer_identity_uuid_strategy",
        {"identity_type": "integer"},
        [
            (Counter, {}),
            (CounterWithItems, {}),
            (CounterItem, {"part_of": CounterWithItems}),
            (Incremented, {}),
            (IntegerKeyed, {}),
            (ModelledCounter, {}),
        ],
        {ModelledCounter: ModelledCounterModel},
    ),
    (
        "integer_identity_function_strategy",
        {"identity_type": "integer", "identity_strategy": "function"},
        [
            (Counter, {"indexes": [Index("id", "total")]}),
            (CounterWithItems, {}),
            (CounterItem, {"part_of": CounterWithItems}),
            (StringIdInIntegerDomain, {}),
        ],
        {},
    ),
    (
        "postgresql_elements",
        UUID_DOMAIN,
        [
            (postgresql_elements.Person, {}),
            (postgresql_elements.Alien, {}),
            (postgresql_elements.User, {}),
            (postgresql_elements.ComplexUser, {}),
        ],
        {},
    ),
    (
        "mssql_elements",
        UUID_DOMAIN,
        [
            (mssql_elements.MssqlTestEntity, {}),
            (mssql_elements.MssqlTimestampedEntity, {}),
        ],
        {},
    ),
]


def build_domain(name, config, registrations, models):
    domain = Domain(
        name=f"DDL golden {name}",
        config={**config, "databases": {"default": {"provider": "memory"}}},
        identity_function=next_int,
    )
    for element, kwargs in registrations:
        domain.register(element, **kwargs)
    for element, model in models.items():
        domain.register(model, part_of=element)
    domain.init(traverse=False)
    return domain


def error_entry(exc):
    """A guard's refusal, recorded in place of the DDL it prevented."""
    return {"error": type(exc).__name__, "message": str(exc)}


def emitted_ddl(model_cls, dialect):
    """The table, index and raw DDL that creating the model's table emits."""
    statements = []

    def capture(sql, *multiparams, **params):
        statements.append(str(sql.compile(dialect=dialect)).strip())

    engine = create_mock_engine(f"{dialect.name}://", capture)
    model_cls.__table__.create(engine, checkfirst=False)
    version_col = getattr(model_cls, "__mapper_args__", {}).get("version_id_col")
    return {
        "table": statements[0],
        # Index creation follows the order of a set, so sort it.
        "indexes": sorted(statements[1:]),
        "version_id_col": None if version_col is None else version_col.name,
    }


def model_entry(provider, element, model):
    try:
        if model is None:
            model_cls = provider.construct_database_model_class(element)
        else:
            model_cls = provider.decorate_database_model_class(element, model)
    except (ConfigurationError, IncorrectUsageError) as exc:
        return error_entry(exc)
    return emitted_ddl(model_cls, provider._engine.dialect)


def rendered_entry(element, dialect_name):
    try:
        return render_index_ddl(element, dialect_name)
    except (ConfigurationError, IncorrectUsageError) as exc:
        return error_entry(exc)


def generate_ddl():
    ddl = {}
    for case_name, config, registrations, models in CASES:
        domain = build_domain(case_name, config, registrations, models)
        with domain.domain_context():
            for dialect_name, provider_cls, uri, _ in DIALECTS:
                provider = provider_cls(
                    name=dialect_name,
                    domain=domain,
                    conn_info={"provider": dialect_name, "database_uri": uri},
                )
                for element, kwargs in registrations:
                    entry = {
                        "model": model_entry(provider, element, models.get(element))
                    }
                    if kwargs.get("indexes"):
                        entry["rendered"] = rendered_entry(element, dialect_name)
                    ddl[f"{dialect_name}/{case_name}/{element.__name__}"] = entry
    return ddl


def test_emitted_ddl_matches_the_golden_file():
    for _, _, _, module in DIALECTS:
        if importlib.util.find_spec(module) is None:
            pytest.skip(f"DBAPI module {module} is not installed")

    ddl = generate_ddl()
    assert ddl, "no DDL was generated"

    if REGENERATE:
        GOLDEN_FILE.write_text(json.dumps(ddl, indent=2, sort_keys=True) + "\n")

    golden = json.loads(GOLDEN_FILE.read_text())
    assert sorted(ddl) == sorted(golden)
    for key in sorted(golden):
        assert ddl[key] == golden[key], key
