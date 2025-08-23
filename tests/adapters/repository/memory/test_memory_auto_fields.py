"""Test Memory Provider Auto field increment functionality"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Auto, String


class AutoEntity(BaseAggregate):
    name = String(max_length=100)
    sequence = Auto(increment=True)


class AutoIdentifierEntity(BaseAggregate):
    id = Auto(identifier=True, increment=True)
    name = String(max_length=100)


class NoAutoEntity(BaseAggregate):
    name = String(max_length=100)


class MultipleAutoEntity(BaseAggregate):
    name = String(max_length=100)
    seq1 = Auto(increment=True)
    seq2 = Auto(increment=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(AutoEntity)
    test_domain.register(AutoIdentifierEntity)
    test_domain.register(NoAutoEntity)
    test_domain.register(MultipleAutoEntity)


def test_auto_field_increment_starts_from_zero_and_increments(test_domain):
    """Test that Auto field with increment starts from 0 and properly increments"""
    # Create first entity
    entity1 = AutoEntity(name="First")
    test_domain.repository_for(AutoEntity).add(entity1)

    # Verify it got sequence 1 (since counter starts from 0, first next() returns 1)
    saved_entity1 = test_domain.repository_for(AutoEntity).get(entity1.id)
    assert saved_entity1.sequence == 1

    # Create second entity
    entity2 = AutoEntity(name="Second")
    test_domain.repository_for(AutoEntity).add(entity2)

    # Verify it got sequence 2
    saved_entity2 = test_domain.repository_for(AutoEntity).get(entity2.id)
    assert saved_entity2.sequence == 2


def test_auto_field_increment_with_identifier_field(test_domain):
    """Test Auto field increment when it's also the identifier"""
    # Create entities with Auto identifier field
    entity1 = AutoIdentifierEntity(name="First")
    test_domain.repository_for(AutoIdentifierEntity).add(entity1)

    # Check the stored data directly
    saved_entities = (
        test_domain.repository_for(AutoIdentifierEntity)._dao.query.all().items
    )
    assert len(saved_entities) == 1
    assert saved_entities[0].id == 1

    entity2 = AutoIdentifierEntity(name="Second")
    test_domain.repository_for(AutoIdentifierEntity).add(entity2)

    # Check all saved entities
    saved_entities = (
        test_domain.repository_for(AutoIdentifierEntity)._dao.query.all().items
    )
    assert len(saved_entities) == 2
    # Sort by id to ensure consistent order
    saved_entities.sort(key=lambda x: x.id)
    assert saved_entities[0].id == 1
    assert saved_entities[1].id == 2


def test_auto_field_not_overwritten_when_already_set(test_domain):
    """Test that Auto field is not overwritten when value is already present"""
    # Create entity with sequence already set
    entity = AutoEntity(name="PreSet")

    # Manually set the sequence field before saving
    dao = test_domain.repository_for(AutoEntity)._dao
    model_dict = dao.database_model_cls.from_entity(entity)
    model_dict["sequence"] = 999  # Pre-set the auto field

    # This should not override the existing value
    updated_model = dao._set_auto_fields(model_dict)

    # Sequence should remain as we set it
    assert updated_model["sequence"] == 999


def test_multiple_auto_fields_get_separate_counters(test_domain):
    """Test that multiple Auto fields in same entity get separate counters"""
    # Create entity with multiple auto fields
    entity1 = MultipleAutoEntity(name="First")
    test_domain.repository_for(MultipleAutoEntity).add(entity1)

    saved_entity1 = test_domain.repository_for(MultipleAutoEntity).get(entity1.id)
    assert saved_entity1.seq1 == 1
    assert saved_entity1.seq2 == 1

    # Create second entity
    entity2 = MultipleAutoEntity(name="Second")
    test_domain.repository_for(MultipleAutoEntity).add(entity2)

    saved_entity2 = test_domain.repository_for(MultipleAutoEntity).get(entity2.id)
    assert saved_entity2.seq1 == 2
    assert saved_entity2.seq2 == 2


def test_auto_field_counters_are_per_schema(test_domain):
    """Test that Auto field counters are separate for different schemas"""
    # Create entities of different types
    auto_entity = AutoEntity(name="Auto")
    test_domain.repository_for(AutoEntity).add(auto_entity)

    multi_entity = MultipleAutoEntity(name="Multi")
    test_domain.repository_for(MultipleAutoEntity).add(multi_entity)

    # Both should start from 1 despite having fields with same name
    saved_auto = test_domain.repository_for(AutoEntity).get(auto_entity.id)
    saved_multi = test_domain.repository_for(MultipleAutoEntity).get(multi_entity.id)

    assert saved_auto.sequence == 1
    assert saved_multi.seq1 == 1  # Should be independent counter


def test_auto_field_counter_handles_zero_start_correctly(test_domain):
    """Test the specific counter logic that handles starting from 0"""
    dao = test_domain.repository_for(AutoEntity)._dao
    conn = dao._get_session()

    # The counter should start from 0
    counter_key = f"{dao.schema_name}_sequence"

    # First call to next() returns 0
    first_counter = next(conn._db["counters"][counter_key])
    assert first_counter == 0

    # The code checks if counter is 0 (falsy) and calls next() again
    # Second call returns 1
    second_counter = next(conn._db["counters"][counter_key])
    assert second_counter == 1

    entity = AutoEntity(name="TestCounter")
    model_dict = dao.database_model_cls.from_entity(entity)

    # Remove sequence to trigger auto-increment
    if "sequence" in model_dict:
        del model_dict["sequence"]

    # This should trigger the counter logic
    updated_model = dao._set_auto_fields(model_dict)

    # Should get the next value (2, since we already called next twice)
    assert updated_model["sequence"] == 2
