"""A field annotated as ``list[str]`` or ``list[int]`` is a native PostgreSQL
array of that item type, and saves and loads back."""

import pytest
from sqlalchemy.dialects import postgresql

from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.fields import String
from tests.shared import POSTGRES_URI

pytestmark = [pytest.mark.postgresql, pytest.mark.no_test_domain]


class TypedTagHolder(BaseAggregate):
    name: String(max_length=50)
    tags: list[str]


class TypedScoreHolder(BaseAggregate):
    player: String(max_length=50)
    scores: list[int]


@pytest.fixture
def domain():
    domain = Domain(
        name="PostgresTypedLists",
        config={
            "databases": {
                "default": {"provider": "postgresql", "database_uri": POSTGRES_URI}
            }
        },
    )
    domain.register(TypedTagHolder)
    domain.register(TypedScoreHolder)
    domain.init(traverse=False)

    with domain.domain_context():
        domain.setup_database()
        try:
            yield domain
        finally:
            domain.drop_database()
            domain.providers.close()


def column_type(domain, aggregate_cls, attribute):
    provider = domain.providers["default"]
    table = provider.construct_database_model_class(aggregate_cls).__table__
    return table.c[attribute].type.compile(dialect=postgresql.dialect())


class TestTypedListColumns:
    def test_a_list_of_str_is_a_varchar_array(self, domain):
        assert column_type(domain, TypedTagHolder, "tags") == "VARCHAR[]"

    def test_a_list_of_int_is_an_integer_array(self, domain):
        assert column_type(domain, TypedScoreHolder, "scores") == "INTEGER[]"

    def test_a_list_of_str_loads_back(self, domain):
        repo = domain.repository_for(TypedTagHolder)
        item = TypedTagHolder(name="Item1", tags=["a", "b", "c"])
        repo.add(item)

        assert repo.get(item.id).tags == ["a", "b", "c"]

    def test_a_list_of_int_loads_back(self, domain):
        repo = domain.repository_for(TypedScoreHolder)
        board = TypedScoreHolder(player="Alice", scores=[100, 200, 300])
        repo.add(board)

        assert repo.get(board.id).scores == [100, 200, 300]
