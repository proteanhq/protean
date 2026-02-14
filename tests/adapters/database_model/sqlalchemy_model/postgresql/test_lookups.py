import pytest

from protean.adapters.repository.sqlalchemy import Any, Contains, In, Overlap
from protean.core.aggregate import BaseAggregate


class GenericPostgres(BaseAggregate):
    ids: list[str] = []
    role: str | None = None


@pytest.mark.postgresql
class TestLookups:
    def test_any_lookup(self, test_domain):
        database_model_cls = test_domain.repository_for(GenericPostgres)._database_model

        identifier = "foobar"
        lookup = Any("ids", identifier, database_model_cls)
        expr = lookup.as_expression()

        assert str(expr.compile()) in [
            ":param_1 = ANY (public.generic_postgres.ids)",
            ":ids_1 = ANY (public.generic_postgres.ids)",
        ]
        assert expr.compile().params in [
            {"param_1": "foobar"},
            {"ids_1": "foobar"},
        ]

    def test_contains_lookup_with_array(self, test_domain):
        database_model_cls = test_domain.repository_for(GenericPostgres)._database_model

        identifier = ["foo", "bar"]
        lookup = Contains("ids", identifier, database_model_cls)
        expr = lookup.as_expression()

        assert str(expr.compile()) == "public.generic_postgres.ids @> :ids_1"
        assert expr.compile().params == {"ids_1": ["foo", "bar"]}

    def test_overlap_lookup_with_array(self, test_domain):
        database_model_cls = test_domain.repository_for(GenericPostgres)._database_model

        identifier = ["foo", "bar"]
        lookup = Overlap("ids", identifier, database_model_cls)
        expr = lookup.as_expression()

        assert str(expr.compile()) == "public.generic_postgres.ids && :ids_1"
        assert expr.compile().params == {"ids_1": ["foo", "bar"]}

    def test_in_lookup(self, test_domain):
        database_model_cls = test_domain.repository_for(GenericPostgres)._database_model

        target_roles = ["foo", "bar", "baz"]
        lookup = In("role", target_roles, database_model_cls)
        expr = lookup.as_expression()

        assert (
            str(expr.compile())
            == "public.generic_postgres.role IN (__[POSTCOMPILE_role_1])"
        )
        assert expr.compile().params == {"role_1": ["foo", "bar", "baz"]}
