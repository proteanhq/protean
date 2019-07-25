# Protean
from protean.core.aggregate import AggregateMeta
from protean.core.field.basic import Auto, String

# Local/Relative Imports
from .elements import (AbstractRole, ConcreteRole, DbRole, DifferentDbRole, FurtherAbstractRole,
                       OrderedRole, OrderedRoleSubclass, Role, SqlDifferentDbRole, SqlRole, SubclassRole)


class TestAggregateMeta:
    def test_aggregate_meta_structure(self):
        assert hasattr(Role, 'meta_')
        assert type(Role.meta_) is AggregateMeta

        # Persistence attributes
        # FIXME Should these be present as part of Aggregates, or a separate Model?
        assert hasattr(Role.meta_, 'abstract')
        assert hasattr(Role.meta_, 'schema_name')
        assert hasattr(Role.meta_, 'provider')

        # Fields Meta Info
        assert hasattr(Role.meta_, 'declared_fields')
        assert hasattr(Role.meta_, 'attributes')
        assert hasattr(Role.meta_, 'id_field')

        # Domain attributes
        assert hasattr(Role.meta_, 'aggregate')
        assert hasattr(Role.meta_, 'bounded_context')

    def test_aggregate_meta_has_declared_fields_on_construction(self):
        assert Role.meta_.declared_fields is not None
        assert all(key in Role.meta_.declared_fields.keys() for key in ['created_on', 'id', 'name'])

    def test_aggregate_declared_fields_hold_correct_field_types(self):
        assert type(Role.meta_.declared_fields['name']) is String
        assert type(Role.meta_.declared_fields['id']) is Auto

    def test_default_and_overridden_abstract_flag_in_meta(self):
        assert getattr(Role.meta_, 'abstract') is False
        assert getattr(AbstractRole.meta_, 'abstract') is True

    def test_abstract_can_be_overridden_from_aggregate_abstract_class(self):
        """Test that `abstract` flag can be overridden"""

        # Test that the option in meta is overridden
        assert hasattr(ConcreteRole.meta_, 'abstract')
        assert getattr(ConcreteRole.meta_, 'abstract') is False

    def test_abstract_can_be_overridden_from_aggregate_concrete_class(self):
        """Test that `abstract` flag can be overridden"""

        # Test that the option in meta is overridden
        assert hasattr(FurtherAbstractRole.meta_, 'abstract')
        assert getattr(FurtherAbstractRole.meta_, 'abstract') is True

    def test_default_and_overridden_schema_name_in_meta(self):
        assert getattr(Role.meta_, 'schema_name') == 'role'
        assert getattr(DbRole.meta_, 'schema_name') == 'foosball'

    def test_schema_name_can_be_overridden_in_aggregate_subclass(self):
        """Test that `schema_name` can be overridden"""
        assert hasattr(SqlRole.meta_, 'schema_name')
        assert getattr(SqlRole.meta_, 'schema_name') == 'roles'

    def test_default_and_overridden_provider_in_meta(self):
        assert getattr(Role.meta_, 'provider') == 'default'
        assert getattr(DifferentDbRole.meta_, 'provider') == 'non-default'

    def test_provider_can_be_overridden_in_aggregate_subclass(self):
        """Test that `provider` can be overridden"""
        assert hasattr(SqlDifferentDbRole.meta_, 'provider')
        assert getattr(SqlDifferentDbRole.meta_, 'provider') == 'non-default-sql'

    def test_default_and_overridden_order_by_in_meta(self):
        assert getattr(Role.meta_, 'order_by') == ()
        assert getattr(OrderedRole.meta_, 'order_by') == ('bar', )

    def test_order_by_can_be_overridden_in_aggregate_subclass(self):
        """Test that `order_by` can be overridden"""
        assert hasattr(OrderedRoleSubclass.meta_, 'order_by')
        assert getattr(OrderedRoleSubclass.meta_, 'order_by') == ('bar', )

    def test_that_schema_is_not_inherited(self):
        assert Role.meta_.schema_name != SubclassRole.meta_.schema_name
