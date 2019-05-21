import pytest

from collections import OrderedDict
from datetime import datetime
from uuid import UUID

from protean.core.aggregate import _AggregateMetaclass
from protean.utils import fully_qualified_name

from .elements import Role, SubclassRole


class TestAggregateStructure:
    def test_aggregate_inheritance(self):
        assert isinstance(Role, _AggregateMetaclass)

    def test_successful_aggregate_registration(self, test_domain):
        test_domain.register(Role)
        assert fully_qualified_name(Role) in test_domain.aggregates

    def test_aggregate_field_definitions(self):
        declared_fields_keys = list(OrderedDict(sorted(Role.meta_.declared_fields.items())).keys())
        assert declared_fields_keys == ['created_on', 'id', 'name']


class TestSubclassedAggregateStructure:
    def test_subclass_aggregate_field_definitions(self):
        declared_fields_keys = list(OrderedDict(sorted(SubclassRole.meta_.declared_fields.items())).keys())
        assert declared_fields_keys == ['created_on', 'id', 'name']


class TestAggregateInitialization:
    def test_successful_aggregate_initialization(self):
        role = Role(name='ADMIN')
        assert role is not None
        assert role.name == 'ADMIN'
        assert type(role.created_on) is datetime
