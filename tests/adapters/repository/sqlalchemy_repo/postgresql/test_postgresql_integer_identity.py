"""An integer identity under the ``function`` strategy builds, saves and loads
back on PostgreSQL."""

import itertools

import pytest
from sqlalchemy import Integer

from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.fields import String
from tests.shared import POSTGRES_URI

_counter = itertools.count(1)


def next_int() -> int:
    return next(_counter)


class Counted(BaseAggregate):
    title: String(max_length=50)


@pytest.fixture
def domain():
    domain = Domain(
        name="PostgresIntegerIdentity",
        config={
            "identity_type": "integer",
            "identity_strategy": "function",
            "databases": {
                "default": {"provider": "postgresql", "database_uri": POSTGRES_URI}
            },
        },
        identity_function=next_int,
    )
    domain.register(Counted)
    domain.init(traverse=False)
    with domain.domain_context():
        domain.repository_for(Counted)._dao
        provider = domain.providers["default"]
        provider._metadata.create_all(provider._engine)
        yield domain
        provider._metadata.drop_all(provider._engine)
        domain.providers.close()


@pytest.mark.postgresql
def test_an_integer_identity_saves_and_loads_back(domain):
    repo = domain.repository_for(Counted)
    column = repo._dao.database_model_cls.__table__.columns["id"]
    assert type(column.type) is Integer

    counted = Counted(title="first")
    repo.add(counted)
    loaded = repo.get(counted.id)

    assert int(loaded.id) == int(counted.id)
    assert loaded.title == "first"
