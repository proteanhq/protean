# Test that limit provided in Projection options is respected

import pytest

from protean.core.projection import _LegacyBaseProjection as BaseProjection
from protean.fields import Identifier, Integer, String


class Person(BaseProjection):
    person_id = Identifier(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)


def test_entity_query_limit_is_100_by_default(test_domain):
    test_domain.register(Person)

    assert Person.meta_.limit == 100


def test_entity_query_limit_can_be_explicitly_set_in_entity_config(test_domain):
    test_domain.register(Person, limit=500)

    assert Person.meta_.limit == 500


def test_entity_query_limit_can_be_unlimited(test_domain):
    test_domain.register(Person, limit=None)

    assert Person.meta_.limit is None


def test_entity_query_limit_is_unlimited_when_limit_is_set_to_negative_value(
    test_domain,
):
    test_domain.register(Person, limit=-1)

    assert Person.meta_.limit is None
