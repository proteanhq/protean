"""Test Memory Provider update_all functionality"""

import pytest

from protean import UnitOfWork
from protean.core.aggregate import BaseAggregate
from protean.fields import String, Integer, Boolean
from protean.utils.query import Q


class UpdateTestEntity(BaseAggregate):
    name: String(max_length=100, required=True)
    category: String(max_length=50)
    value: Integer()
    active: Boolean(default=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(UpdateTestEntity)


def test_update_all_returns_count_outside_uow(test_domain):
    """Test that update_all returns correct count when not in UoW"""
    # Create test entities
    entity1 = UpdateTestEntity(name="Test1", category="A", value=10)
    entity2 = UpdateTestEntity(name="Test2", category="A", value=20)
    entity3 = UpdateTestEntity(name="Test3", category="B", value=30)

    test_domain.repository_for(UpdateTestEntity).add(entity1)
    test_domain.repository_for(UpdateTestEntity).add(entity2)
    test_domain.repository_for(UpdateTestEntity).add(entity3)

    dao = test_domain.repository_for(UpdateTestEntity)._dao

    # Update all entities in category A
    update_count = dao._update_all(Q(category="A"), value=999)

    # Should return count of 2
    assert update_count == 2

    # Verify the updates were applied
    updated_entities = dao.query.filter(category="A").all().items
    assert len(updated_entities) == 2
    for entity in updated_entities:
        assert entity.value == 999


def test_update_all_with_empty_criteria_updates_nothing(test_domain):
    """Test update_all with criteria that matches nothing"""
    # Create test entities
    entity1 = UpdateTestEntity(name="Test1", category="A", value=10)
    entity2 = UpdateTestEntity(name="Test2", category="B", value=20)

    test_domain.repository_for(UpdateTestEntity).add(entity1)
    test_domain.repository_for(UpdateTestEntity).add(entity2)

    dao = test_domain.repository_for(UpdateTestEntity)._dao

    # Update entities with non-existent category
    update_count = dao._update_all(Q(category="NonExistent"), value=999)

    # Should return count of 0
    assert update_count == 0

    # Verify no entities were updated
    all_entities = dao.query.all().items
    assert all_entities[0].value == 10
    assert all_entities[1].value == 20


def test_update_all_with_multiple_field_updates(test_domain):
    """Test update_all with multiple field updates using *args and **kwargs"""
    # Create test entities
    entity1 = UpdateTestEntity(name="Test1", category="A", value=10)
    entity2 = UpdateTestEntity(name="Test2", category="A", value=20)

    test_domain.repository_for(UpdateTestEntity).add(entity1)
    test_domain.repository_for(UpdateTestEntity).add(entity2)

    dao = test_domain.repository_for(UpdateTestEntity)._dao

    # Update using both *args and **kwargs
    update_dict = {"category": "Updated"}
    update_count = dao._update_all(
        Q(category="A"),
        update_dict,  # *args
        value=999,  # **kwargs
        name="NewName",
    )

    # Should return count of 2
    assert update_count == 2

    # Verify all updates were applied
    updated_entities = dao.query.filter(value=999).all().items
    assert len(updated_entities) == 2
    for entity in updated_entities:
        assert entity.category == "Updated"
        assert entity.value == 999
        assert entity.name == "NewName"


def test_update_all_within_uow_does_not_commit(test_domain):
    """Test that update_all within UoW does not auto-commit"""
    # Create test entities
    entity1 = UpdateTestEntity(name="Test1", category="A", value=10)
    entity2 = UpdateTestEntity(name="Test2", category="A", value=20)

    test_domain.repository_for(UpdateTestEntity).add(entity1)
    test_domain.repository_for(UpdateTestEntity).add(entity2)

    with UnitOfWork():
        dao = test_domain.repository_for(UpdateTestEntity)._dao

        # Update within UoW
        update_count = dao._update_all(Q(category="A"), value=999)

        # Should still return correct count
        assert update_count == 2

        # Changes should be visible within the UoW session
        updated_entities = dao.query.filter(category="A").all().items
        assert len(updated_entities) == 2
        for entity in updated_entities:
            assert entity.value == 999


def test_update_all_updates_items_in_correct_order(test_domain):
    """Test that update_all processes items in the order returned by _filter_items"""
    # Create entities with specific order
    entities = []
    for i in range(5):
        entity = UpdateTestEntity(name=f"Test{i}", category="batch", value=i)
        test_domain.repository_for(UpdateTestEntity).add(entity)
        entities.append(entity)

    dao = test_domain.repository_for(UpdateTestEntity)._dao

    # Update all entities in the batch
    update_count = dao._update_all(Q(category="batch"), value=100, name="Updated")

    # Should return count of 5
    assert update_count == 5

    # Verify all entities were updated
    updated_entities = dao.query.filter(category="batch").all().items
    assert len(updated_entities) == 5
    for entity in updated_entities:
        assert entity.value == 100
        assert entity.name == "Updated"


def test_update_all_handles_complex_criteria(test_domain):
    """Test update_all with complex query criteria"""
    # Create entities with various values
    entity1 = UpdateTestEntity(name="Test1", category="A", value=10)
    entity2 = UpdateTestEntity(name="Test2", category="A", value=30)
    entity3 = UpdateTestEntity(name="Test3", category="B", value=20)
    entity4 = UpdateTestEntity(name="Test4", category="A", value=40)

    test_domain.repository_for(UpdateTestEntity).add(entity1)
    test_domain.repository_for(UpdateTestEntity).add(entity2)
    test_domain.repository_for(UpdateTestEntity).add(entity3)
    test_domain.repository_for(UpdateTestEntity).add(entity4)

    dao = test_domain.repository_for(UpdateTestEntity)._dao

    # Update entities in category A with value >= 30
    complex_criteria = Q(category="A") & Q(value__gte=30)
    update_count = dao._update_all(complex_criteria, category="Updated")

    # Should update 2 entities (Test2 and Test4)
    assert update_count == 2

    # Verify correct entities were updated
    updated_entities = dao.query.filter(category="Updated").all().items
    assert len(updated_entities) == 2
    updated_names = {entity.name for entity in updated_entities}
    assert updated_names == {"Test2", "Test4"}

    # Verify other entities were not affected
    unchanged_entities = dao.query.filter(category="A").all().items
    assert len(unchanged_entities) == 1
    assert unchanged_entities[0].name == "Test1"
