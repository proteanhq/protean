"""An integer identity builds, saves and loads back on PostgreSQL.

psycopg 3 binds a Python ``str`` as text, and PostgreSQL has no
``integer = text`` operator, so a declared ``Auto`` or ``Identifier``, which
holds its value as a string, is the case these tests exist for.
"""

import itertools

import pytest

from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.fields import Auto, Identifier, Integer, String
from protean.utils.query import Q
from protean.utils.reflection import id_field
from tests.shared import POSTGRES_URI

_counter = itertools.count(1)


def next_int() -> int:
    return next(_counter)


class Counted(BaseAggregate):
    title: String(max_length=50)


class DeclaredAuto(BaseAggregate):
    ticket_id: Auto(identifier=True)
    title: String(max_length=50)


class FieldFunction(BaseAggregate):
    ticket_id: Auto(
        identifier=True, identity_strategy="function", identity_function=next_int
    )
    title: String(max_length=50)


class IdentifierDefault(BaseAggregate):
    ticket_id: Identifier(identifier=True, default="7")
    title: String(max_length=50)


class CallerFilled(BaseAggregate):
    code: String(identifier=True, max_length=20)
    title: String(max_length=50)


def postgres_domain(aggregate_cls, **config) -> Domain:
    domain = Domain(
        name="PostgresIntegerIdentity",
        config={
            "identity_type": "integer",
            "databases": {
                "default": {"provider": "postgresql", "database_uri": POSTGRES_URI}
            },
            **config,
        },
        identity_function=next_int,
    )
    domain.register(aggregate_cls)
    domain.init(traverse=False)
    return domain


@pytest.mark.postgresql
@pytest.mark.parametrize(
    ("aggregate_cls", "config", "values"),
    [
        (Counted, {"identity_strategy": "function"}, {}),
        (DeclaredAuto, {"identity_strategy": "function"}, {}),
        (FieldFunction, {}, {}),
        (IdentifierDefault, {}, {}),
        (CallerFilled, {}, {"code": "42"}),
    ],
)
def test_an_integer_identity_saves_and_loads_back(aggregate_cls, config, values):
    domain = postgres_domain(aggregate_cls, **config)
    with domain.domain_context():
        repo = domain.repository_for(aggregate_cls)
        provider = domain.providers["default"]
        table = repo._dao.database_model_cls.__table__
        id_name = id_field(aggregate_cls).field_name
        column_type = table.columns[id_name].type
        assert column_type.compile(dialect=provider._engine.dialect) == "INTEGER"

        provider._metadata.create_all(provider._engine)
        try:
            saved = aggregate_cls(title="first", **values)
            repo.add(saved)
            loaded = repo.get(getattr(saved, id_name))
        finally:
            provider._metadata.drop_all(provider._engine)
            domain.providers.close()

    assert getattr(loaded, id_name) == getattr(saved, id_name)
    assert loaded.title == "first"


class TiedJob(BaseAggregate):
    job_id: Auto(identifier=True)
    status: String(max_length=20, default="ready")
    seq: Integer(required=True)


@pytest.mark.postgresql
def test_a_claim_breaks_order_ties_by_the_integer_id_value():
    # ``Auto`` holds the id as a ``str``, and "10" sorts before "2", so the
    # claim must order its rows by the column's integer values.
    ids = iter([10, 2])
    domain = Domain(
        name="PostgresIntegerIdentityClaim",
        config={
            "identity_type": "integer",
            "identity_strategy": "function",
            "databases": {
                "default": {"provider": "postgresql", "database_uri": POSTGRES_URI}
            },
        },
        identity_function=lambda: next(ids),
    )
    domain.register(TiedJob)
    domain.init(traverse=False)
    with domain.domain_context():
        repo = domain.repository_for(TiedJob)
        # Reading the DAO registers the table in the provider's metadata.
        dao = repo._dao
        provider = domain.providers["default"]
        provider._metadata.create_all(provider._engine)
        try:
            repo.add(TiedJob(seq=0))
            repo.add(TiedJob(seq=0))
            claimed = dao._claim(
                Q(status="ready"),
                {"status": "claimed"},
                limit=10,
                order_by=["seq", "job_id"],
            )
        finally:
            provider._metadata.drop_all(provider._engine)
            domain.providers.close()

    assert [job.job_id for job in claimed] == ["2", "10"]
