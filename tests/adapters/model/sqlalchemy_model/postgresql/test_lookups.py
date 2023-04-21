import pytest

from protean import BaseAggregate
from protean.adapters.repository.sqlalchemy import Any, Contains, In, Overlap
from protean.fields import List, String


class GenericPostgres(BaseAggregate):
    ids = List()
    role = String()


@pytest.mark.postgresql
class TestLookups:
    def test_any_lookup(self, test_domain):
        model_cls = test_domain.get_model(GenericPostgres)

        identifier = "foobar"
        lookup = Any("ids", identifier, model_cls)
        expr = lookup.as_expression()

        assert str(expr.compile()) == ":param_1 = ANY (generic_postgres.ids)"
        assert expr.compile().params == {"param_1": "foobar"}

    def test_contains_lookup_with_array(self, test_domain):
        model_cls = test_domain.get_model(GenericPostgres)

        identifier = ["foo", "bar"]
        lookup = Contains("ids", identifier, model_cls)
        expr = lookup.as_expression()

        assert str(expr.compile()) == "generic_postgres.ids @> :ids_1"
        assert expr.compile().params == {"ids_1": ["foo", "bar"]}

    def test_overlap_lookup_with_array(self, test_domain):
        model_cls = test_domain.get_model(GenericPostgres)

        identifier = ["foo", "bar"]
        lookup = Overlap("ids", identifier, model_cls)
        expr = lookup.as_expression()

        assert str(expr.compile()) == "generic_postgres.ids && :ids_1"
        assert expr.compile().params == {"ids_1": ["foo", "bar"]}

    def test_in_lookup(self, test_domain):
        model_cls = test_domain.get_model(GenericPostgres)

        target_roles = ["foo", "bar", "baz"]
        lookup = In("role", target_roles, model_cls)
        expr = lookup.as_expression()

        assert (
            str(expr.compile()) == "generic_postgres.role IN (__[POSTCOMPILE_role_1])"
        )
        assert expr.compile().params == {"role_1": ["foo", "bar", "baz"]}
