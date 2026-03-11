"""Tests for ``assert_snapshot`` in ``protean.testing``.

Exercises the snapshot testing helper across domain objects, plain dicts,
and the ``--update-snapshots`` regeneration flow.
"""

import json
import shutil
from pathlib import Path

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.fields import Float, HasMany, Identifier, Integer, String, ValueObject
from protean.testing import assert_snapshot

# ---------------------------------------------------------------------------
# Snapshot directory for *this* test module
# ---------------------------------------------------------------------------
SNAPSHOT_DIR = Path(__file__).parent / "__snapshots__" / "test_snapshot"


# ---------------------------------------------------------------------------
# Domain elements used in tests
# ---------------------------------------------------------------------------
class Address(BaseValueObject):
    street = String()
    city = String()


class LineItem(BaseEntity):
    product_id = Identifier(required=True)
    quantity = Integer()
    price = Float()


class Invoice(BaseAggregate):
    customer_id = Identifier(required=True)
    items = HasMany("LineItem")
    status = String(default="DRAFT")
    billing_address = ValueObject(Address)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Address)
    test_domain.register(LineItem, part_of=Invoice)
    test_domain.register(Invoice)
    test_domain.init(traverse=False)


@pytest.fixture(autouse=True)
def clean_snapshots():
    """Remove snapshot dir and reset update flag for isolation."""
    import protean.testing as testing_mod

    if SNAPSHOT_DIR.exists():
        shutil.rmtree(SNAPSHOT_DIR)
    original_flag = testing_mod._update_snapshots
    testing_mod._update_snapshots = False
    yield
    testing_mod._update_snapshots = original_flag
    if SNAPSHOT_DIR.exists():
        shutil.rmtree(SNAPSHOT_DIR)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAssertSnapshotCreation:
    """First-run behaviour — snapshots are created automatically."""

    def test_creates_snapshot_file_on_first_run(self):
        data = {"name": "Alice", "balance": 100}
        assert_snapshot(data, "simple_dict")

        snapshot_file = SNAPSHOT_DIR / "simple_dict.json"
        assert snapshot_file.exists()

        stored = json.loads(snapshot_file.read_text("utf-8"))
        assert stored == {"balance": 100, "name": "Alice"}

    def test_creates_directory_structure(self):
        assert_snapshot({"x": 1}, "nested_dir_test")
        assert SNAPSHOT_DIR.is_dir()

    def test_snapshot_from_domain_object(self):
        invoice = Invoice(
            customer_id="c1",
            status="PAID",
        )
        assert_snapshot(invoice, "invoice_basic", exclude=["id", "items"])

        snapshot_file = SNAPSHOT_DIR / "invoice_basic.json"
        stored = json.loads(snapshot_file.read_text("utf-8"))
        assert stored["customer_id"] == "c1"
        assert stored["status"] == "PAID"
        assert "id" not in stored
        assert "items" not in stored


class TestAssertSnapshotMatching:
    """Second-run behaviour — snapshots are compared."""

    def test_passes_when_snapshot_matches(self):
        data = {"name": "Bob", "score": 42}
        # First run creates
        assert_snapshot(data, "match_test")
        # Second run compares — should pass
        assert_snapshot(data, "match_test")

    def test_fails_on_mismatch(self):
        assert_snapshot({"value": 1}, "mismatch_test")

        with pytest.raises(AssertionError, match="Snapshot mismatch"):
            assert_snapshot({"value": 2}, "mismatch_test")

    def test_diff_message_contains_field_name(self):
        assert_snapshot({"status": "active"}, "diff_detail")

        with pytest.raises(AssertionError, match="status"):
            assert_snapshot({"status": "inactive"}, "diff_detail")

    def test_diff_message_mentions_update_flag(self):
        assert_snapshot({"k": "old"}, "update_hint")

        with pytest.raises(AssertionError, match="--update-snapshots"):
            assert_snapshot({"k": "new"}, "update_hint")


class TestAssertSnapshotExclude:
    """The ``exclude`` parameter strips volatile fields."""

    def test_exclude_single_field(self):
        data = {"id": "volatile-123", "name": "Alice"}
        assert_snapshot(data, "exclude_single", exclude=["id"])

        snapshot_file = SNAPSHOT_DIR / "exclude_single.json"
        stored = json.loads(snapshot_file.read_text("utf-8"))
        assert "id" not in stored
        assert stored["name"] == "Alice"

    def test_exclude_multiple_fields(self):
        data = {"id": "x", "created_at": "now", "name": "Bob"}
        assert_snapshot(data, "exclude_multi", exclude=["id", "created_at"])

        snapshot_file = SNAPSHOT_DIR / "exclude_multi.json"
        stored = json.loads(snapshot_file.read_text("utf-8"))
        assert "id" not in stored
        assert "created_at" not in stored
        assert stored["name"] == "Bob"

    def test_exclude_nonexistent_field_is_ignored(self):
        data = {"name": "Carol"}
        # Should not raise
        assert_snapshot(data, "exclude_missing", exclude=["nonexistent"])


class TestAssertSnapshotUpdateMode:
    """The ``--update-snapshots`` flag regenerates snapshots."""

    def test_update_overwrites_existing(self):
        import protean.testing as testing_mod

        assert_snapshot({"v": 1}, "update_overwrite")

        # Manually enable update mode
        original = testing_mod._update_snapshots
        testing_mod._update_snapshots = True
        try:
            # This should overwrite, not raise
            assert_snapshot({"v": 2}, "update_overwrite")
        finally:
            testing_mod._update_snapshots = original

        snapshot_file = SNAPSHOT_DIR / "update_overwrite.json"
        stored = json.loads(snapshot_file.read_text("utf-8"))
        assert stored["v"] == 2


class TestAssertSnapshotDomainObjects:
    """Snapshot testing with various domain object types."""

    def test_aggregate_with_value_object(self):
        invoice = Invoice(
            customer_id="c1",
            billing_address=Address(street="123 Main St", city="Springfield"),
        )
        assert_snapshot(
            invoice, "aggregate_with_vo", exclude=["id", "items"]
        )

        # Second call should match
        invoice2 = Invoice(
            customer_id="c1",
            billing_address=Address(street="123 Main St", city="Springfield"),
        )
        assert_snapshot(
            invoice2, "aggregate_with_vo", exclude=["id", "items"]
        )

    def test_aggregate_with_entities(self):
        invoice = Invoice(
            customer_id="c1",
            items=[
                LineItem(product_id="p1", quantity=2, price=9.99),
                LineItem(product_id="p2", quantity=1, price=19.99),
            ],
        )
        assert_snapshot(
            invoice,
            "aggregate_with_entities",
            exclude=["id"],
        )

    def test_value_object_standalone(self):
        addr = Address(street="456 Oak Ave", city="Shelbyville")
        assert_snapshot(addr, "value_object_standalone")

        addr2 = Address(street="456 Oak Ave", city="Shelbyville")
        assert_snapshot(addr2, "value_object_standalone")


class TestAssertSnapshotEdgeCases:
    """Edge cases and error handling."""

    def test_empty_dict(self):
        assert_snapshot({}, "empty_dict")
        # Second call should match
        assert_snapshot({}, "empty_dict")

    def test_path_traversal_name_rejected(self):
        with pytest.raises(ValueError, match="Invalid snapshot name"):
            assert_snapshot({"a": 1}, "../escape")

    def test_absolute_path_name_rejected(self):
        with pytest.raises(ValueError, match="Invalid snapshot name"):
            assert_snapshot({"a": 1}, "/etc/passwd")

    def test_unsupported_type_raises_type_error(self):
        with pytest.raises(TypeError, match="Cannot snapshot"):
            assert_snapshot("not a dict", "string_input")

    def test_unsupported_type_int_raises_type_error(self):
        with pytest.raises(TypeError, match="Cannot snapshot"):
            assert_snapshot(42, "int_input")

    def test_sorted_keys_for_determinism(self):
        """Dicts with different insertion order produce the same snapshot."""
        assert_snapshot({"b": 2, "a": 1}, "sorted_keys")

        snapshot_file = SNAPSHOT_DIR / "sorted_keys.json"
        content = snapshot_file.read_text("utf-8")
        # "a" should come before "b" in the JSON
        assert content.index('"a"') < content.index('"b"')

    def test_snapshot_json_is_pretty_printed(self):
        assert_snapshot({"key": "value"}, "pretty_print")

        snapshot_file = SNAPSHOT_DIR / "pretty_print.json"
        content = snapshot_file.read_text("utf-8")
        # Pretty-printed JSON has newlines and indentation
        assert "\n" in content
        assert "  " in content
