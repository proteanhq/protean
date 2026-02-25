"""Generic complex field persistence tests that run against all database providers.

Covers List and Dict field persistence, retrieval, and update operations.
Uses separate aggregates per field type to isolate List and Dict behavior.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Dict, List, String


class TaggedItem(BaseAggregate):
    name: String(max_length=100, required=True)
    tags: List(content_type=String)


class MetadataHolder(BaseAggregate):
    name: String(max_length=100, required=True)
    metadata_field: Dict()


class Config(BaseAggregate):
    name: String(max_length=100, required=True)
    tags: List(content_type=String)
    metadata_field: Dict()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(TaggedItem)
    test_domain.register(MetadataHolder)
    test_domain.register(Config)
    test_domain.init(traverse=False)


@pytest.mark.basic_storage
class TestListFieldPersistence:
    """Persist aggregates with List fields and verify retrieval."""

    def test_persist_with_populated_list(self, test_domain):
        item = TaggedItem(
            name="app-config",
            tags=["web", "production", "v2"],
        )
        test_domain.repository_for(TaggedItem).add(item)

        retrieved = test_domain.repository_for(TaggedItem).get(item.id)
        assert retrieved.name == "app-config"
        assert retrieved.tags == ["web", "production", "v2"]

    def test_persist_single_item_list(self, test_domain):
        item = TaggedItem(name="single-config", tags=["only"])
        test_domain.repository_for(TaggedItem).add(item)

        retrieved = test_domain.repository_for(TaggedItem).get(item.id)
        assert retrieved.tags == ["only"]
        assert len(retrieved.tags) == 1

    def test_list_preserves_order(self, test_domain):
        item = TaggedItem(
            name="ordered",
            tags=["z", "a", "m", "b"],
        )
        test_domain.repository_for(TaggedItem).add(item)

        retrieved = test_domain.repository_for(TaggedItem).get(item.id)
        assert retrieved.tags == ["z", "a", "m", "b"]


@pytest.mark.basic_storage
class TestDictFieldPersistence:
    """Persist aggregates with Dict fields and verify retrieval."""

    def test_persist_with_populated_dict(self, test_domain):
        holder = MetadataHolder(
            name="dict-config",
            metadata_field={"env": "production", "version": "2.0"},
        )
        test_domain.repository_for(MetadataHolder).add(holder)

        retrieved = test_domain.repository_for(MetadataHolder).get(holder.id)
        assert retrieved.metadata_field == {"env": "production", "version": "2.0"}

    def test_persist_with_nested_dict(self, test_domain):
        holder = MetadataHolder(
            name="nested-config",
            metadata_field={
                "database": {"host": "localhost", "port": 5432},
                "cache": {"ttl": 300},
            },
        )
        test_domain.repository_for(MetadataHolder).add(holder)

        retrieved = test_domain.repository_for(MetadataHolder).get(holder.id)
        assert retrieved.metadata_field["database"]["host"] == "localhost"
        assert retrieved.metadata_field["database"]["port"] == 5432
        assert retrieved.metadata_field["cache"]["ttl"] == 300

    def test_persist_dict_with_list_values(self, test_domain):
        holder = MetadataHolder(
            name="list-values",
            metadata_field={"tags": ["a", "b"], "scores": [1, 2, 3]},
        )
        test_domain.repository_for(MetadataHolder).add(holder)

        retrieved = test_domain.repository_for(MetadataHolder).get(holder.id)
        assert retrieved.metadata_field["tags"] == ["a", "b"]
        assert retrieved.metadata_field["scores"] == [1, 2, 3]


@pytest.mark.basic_storage
class TestComplexFieldUpdate:
    """Update List and Dict fields on persisted aggregates."""

    def test_update_list_field(self, test_domain):
        item = TaggedItem(name="update-list", tags=["alpha"])
        test_domain.repository_for(TaggedItem).add(item)

        retrieved = test_domain.repository_for(TaggedItem).get(item.id)
        retrieved.tags = ["alpha", "beta", "gamma"]
        test_domain.repository_for(TaggedItem).add(retrieved)

        updated = test_domain.repository_for(TaggedItem).get(item.id)
        assert updated.tags == ["alpha", "beta", "gamma"]

    def test_update_dict_field(self, test_domain):
        holder = MetadataHolder(
            name="update-dict",
            metadata_field={"key": "old_value"},
        )
        test_domain.repository_for(MetadataHolder).add(holder)

        retrieved = test_domain.repository_for(MetadataHolder).get(holder.id)
        retrieved.metadata_field = {"key": "new_value", "added_key": "extra"}
        test_domain.repository_for(MetadataHolder).add(retrieved)

        updated = test_domain.repository_for(MetadataHolder).get(holder.id)
        assert updated.metadata_field == {"key": "new_value", "added_key": "extra"}

    def test_update_list_and_dict_together(self, test_domain):
        config = Config(
            name="update-both",
            tags=["old"],
            metadata_field={"old_key": "old_value"},
        )
        test_domain.repository_for(Config).add(config)

        retrieved = test_domain.repository_for(Config).get(config.id)
        retrieved.tags = ["new"]
        retrieved.metadata_field = {"new_key": "new_value"}
        test_domain.repository_for(Config).add(retrieved)

        updated = test_domain.repository_for(Config).get(config.id)
        assert updated.tags == ["new"]
        assert updated.metadata_field == {"new_key": "new_value"}
