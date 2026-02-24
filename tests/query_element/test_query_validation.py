"""Tests for Query validation.

Validates:
- Query without part_of raises IncorrectUsageError
- Abstract query without part_of is allowed
- part_of must reference a Projection (not an Aggregate)
- Unresolved string part_of raises error
- BaseQuery cannot be instantiated directly
- Association fields are rejected in queries
- Query with part_of pointing to an unregistered projection raises error
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
)
from protean.fields import HasOne, Identifier, String


class TestQueryPartOfValidation:
    def test_query_without_part_of_raises_error(self, test_domain):
        with pytest.raises(
            IncorrectUsageError,
            match="needs to be associated with a projection",
        ):

            class BadQuery(BaseQuery):
                name = String()

            test_domain.register(BadQuery)

    def test_abstract_query_without_part_of_is_allowed(self, test_domain):
        class AbstractQuery(BaseQuery):
            keyword = String()

        test_domain.register(AbstractQuery, abstract=True)
        test_domain.init(traverse=False)

        assert AbstractQuery.meta_.abstract is True

    def test_part_of_must_reference_projection(self, test_domain):
        """part_of as a string must resolve to a Projection, not an Aggregate."""

        class User(BaseAggregate):
            name = String()

        class GetUser(BaseQuery):
            user_id = Identifier(required=True)

        test_domain.register(User)
        test_domain.register(GetUser, part_of="User")

        with pytest.raises(ConfigurationError):
            test_domain.init(traverse=False)

    def test_part_of_unresolved_string_raises_error(self, test_domain):
        """String part_of that doesn't match any registered element raises error."""

        class FindItems(BaseQuery):
            keyword = String()

        test_domain.register(FindItems, part_of="NonExistentProjection")

        with pytest.raises(ConfigurationError):
            test_domain.init(traverse=False)

    def test_query_part_of_unregistered_projection(self, test_domain):
        """part_of pointing to a Projection class that is not registered
        should raise an error during domain validation."""

        class UnregisteredProjection(BaseProjection):
            item_id = Identifier(identifier=True)
            name = String()

        class FindItems(BaseQuery):
            keyword = String()

        # Register query with part_of pointing to the class directly,
        # but don't register the projection itself
        test_domain.register(FindItems, part_of=UnregisteredProjection)

        with pytest.raises(IncorrectUsageError, match="is not a Projection"):
            test_domain.init(traverse=False)


class TestBaseQueryInstantiation:
    def test_base_query_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError, match="BaseQuery cannot be instantiated"):
            BaseQuery()


class TestQueryFieldTypeRestrictions:
    def test_association_fields_rejected(self):
        with pytest.raises(
            IncorrectUsageError,
            match="Queries can only contain basic field types",
        ):
            from protean.core.entity import BaseEntity

            class Account(BaseEntity):
                password_hash = String()

            class BadQuery(BaseQuery):
                name = String()
                account = HasOne(Account)
