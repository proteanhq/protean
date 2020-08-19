# Protean
import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import List, String
from protean.impl.repository.sqlalchemy_repo import Any, Contains, In, Overlap


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

        assert str(expr.compile()) == ":param_1 = ANY (public.generic_postgres.ids)"
        assert expr.compile().params == {"param_1": "foobar"}

    def test_contains_lookup_with_array(self, test_domain):
        model_cls = test_domain.get_model(GenericPostgres)

        identifier = ["foo", "bar"]
        lookup = Contains("ids", identifier, model_cls)
        expr = lookup.as_expression()

        assert str(expr.compile()) == "public.generic_postgres.ids @> :ids_1"
        assert expr.compile().params == {"ids_1": ["foo", "bar"]}

    def test_overlap_lookup_with_array(self, test_domain):
        model_cls = test_domain.get_model(GenericPostgres)

        identifier = ["foo", "bar"]
        lookup = Overlap("ids", identifier, model_cls)
        expr = lookup.as_expression()

        assert str(expr.compile()) == "public.generic_postgres.ids && :ids_1"
        assert expr.compile().params == {"ids_1": ["foo", "bar"]}

    def test_in_lookup(self, test_domain):
        model_cls = test_domain.get_model(GenericPostgres)

        target_roles = ["foo", "bar", "baz"]
        lookup = In("role", target_roles, model_cls)
        expr = lookup.as_expression()

        assert (
            str(expr.compile())
            == "public.generic_postgres.role IN (:role_1, :role_2, :role_3)"
        )
        assert expr.compile().params == {
            "role_1": "foo",
            "role_2": "bar",
            "role_3": "baz",
        }
