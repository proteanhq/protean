"""Tests for the typed _temp_cache classes in protean.fields.tempdata."""

from protean.fields.tempdata import AssociationCache, HasManyChanges, HasOneChanges


class TestHasManyChanges:
    def test_initial_state(self):
        cache = HasManyChanges()
        assert cache.added == {}
        assert cache.updated == {}
        assert cache.removed == {}

    def test_add_item(self):
        cache = HasManyChanges()
        cache.added["id-1"] = "entity-1"
        assert "id-1" in cache.added
        assert cache.added["id-1"] == "entity-1"

    def test_update_item(self):
        cache = HasManyChanges()
        cache.updated["id-2"] = "entity-2"
        assert "id-2" in cache.updated

    def test_remove_item(self):
        cache = HasManyChanges()
        cache.removed["id-3"] = "entity-3"
        assert "id-3" in cache.removed

    def test_multiple_items(self):
        cache = HasManyChanges()
        cache.added["a"] = 1
        cache.added["b"] = 2
        cache.updated["c"] = 3
        cache.removed["d"] = 4
        assert len(cache.added) == 2
        assert len(cache.updated) == 1
        assert len(cache.removed) == 1

    def test_clear(self):
        cache = HasManyChanges()
        cache.added["a"] = 1
        cache.updated["b"] = 2
        cache.removed["c"] = 3

        cache.clear()

        assert cache.added == {}
        assert cache.updated == {}
        assert cache.removed == {}

    def test_clear_is_idempotent(self):
        cache = HasManyChanges()
        cache.clear()
        assert cache.added == {}
        assert cache.updated == {}
        assert cache.removed == {}

    def test_in_operator_checks_keys(self):
        """Verify that `item not in cache.updated` checks dict keys,
        preserving behavior from the old defaultdict."""
        cache = HasManyChanges()
        cache.updated["uuid-1"] = "entity-obj"
        assert "uuid-1" in cache.updated
        assert "uuid-2" not in cache.updated

    def test_overwrite_same_key(self):
        cache = HasManyChanges()
        cache.added["id-1"] = "first"
        cache.added["id-1"] = "second"
        assert cache.added["id-1"] == "second"
        assert len(cache.added) == 1


class TestHasOneChanges:
    def test_initial_state(self):
        cache = HasOneChanges()
        assert cache.change is None
        assert cache.old_value is None

    def test_set_added(self):
        cache = HasOneChanges()
        cache.change = "ADDED"
        assert cache.change == "ADDED"
        assert cache.old_value is None

    def test_set_updated_with_old_value(self):
        cache = HasOneChanges()
        cache.change = "UPDATED"
        cache.old_value = "old-entity"
        assert cache.change == "UPDATED"
        assert cache.old_value == "old-entity"

    def test_set_updated_without_old_value(self):
        """When the same entity is modified (not replaced), old_value stays None."""
        cache = HasOneChanges()
        cache.change = "UPDATED"
        assert cache.change == "UPDATED"
        assert cache.old_value is None

    def test_set_deleted(self):
        cache = HasOneChanges()
        cache.change = "DELETED"
        cache.old_value = "old-entity"
        assert cache.change == "DELETED"
        assert cache.old_value == "old-entity"

    def test_set_noop(self):
        cache = HasOneChanges()
        cache.change = None
        assert cache.change is None

    def test_clear(self):
        cache = HasOneChanges()
        cache.change = "UPDATED"
        cache.old_value = "old-entity"

        cache.clear()

        assert cache.change is None
        assert cache.old_value is None

    def test_clear_is_idempotent(self):
        cache = HasOneChanges()
        cache.clear()
        assert cache.change is None
        assert cache.old_value is None

    def test_truthiness_of_change(self):
        """Verify that `if cache.change:` works for detecting pending changes."""
        cache = HasOneChanges()
        assert not cache.change  # None is falsy

        cache.change = "ADDED"
        assert cache.change  # Non-empty string is truthy

        cache.change = None
        assert not cache.change


class TestAssociationCache:
    def test_initial_state(self):
        cache = AssociationCache()
        assert len(cache) == 0
        assert isinstance(cache, dict)

    def test_setdefault_has_many(self):
        cache = AssociationCache()
        result = cache.setdefault("items", HasManyChanges())
        assert isinstance(result, HasManyChanges)
        assert "items" in cache

    def test_setdefault_has_one(self):
        cache = AssociationCache()
        result = cache.setdefault("meta", HasOneChanges())
        assert isinstance(result, HasOneChanges)
        assert "meta" in cache

    def test_setdefault_returns_existing(self):
        """setdefault should return the existing entry, not create a new one."""
        cache = AssociationCache()
        first = cache.setdefault("items", HasManyChanges())
        first.added["id-1"] = "entity-1"

        second = cache.setdefault("items", HasManyChanges())
        assert second is first
        assert "id-1" in second.added

    def test_get_missing_returns_none(self):
        cache = AssociationCache()
        assert cache.get("nonexistent") is None

    def test_get_existing(self):
        cache = AssociationCache()
        changes = HasManyChanges()
        cache["items"] = changes
        assert cache.get("items") is changes

    def test_contains(self):
        cache = AssociationCache()
        assert "items" not in cache
        cache.setdefault("items", HasManyChanges())
        assert "items" in cache

    def test_pop(self):
        """AssociationCache supports pop() since it's a dict subclass."""
        cache = AssociationCache()
        cache.setdefault("items", HasManyChanges())
        removed = cache.pop("items", None)
        assert isinstance(removed, HasManyChanges)
        assert "items" not in cache

    def test_pop_missing(self):
        cache = AssociationCache()
        assert cache.pop("items", None) is None

    def test_mixed_field_types(self):
        """An aggregate can have both HasMany and HasOne fields."""
        cache = AssociationCache()
        cache.setdefault("items", HasManyChanges())
        cache.setdefault("meta", HasOneChanges())

        assert isinstance(cache["items"], HasManyChanges)
        assert isinstance(cache["meta"], HasOneChanges)
        assert len(cache) == 2
