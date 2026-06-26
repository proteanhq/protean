"""Unit tests for ``QuerySet.only()`` projection and the ``Record`` value type.

These run against the in-memory adapter (no marker). Cross-adapter behaviour
is covered in ``tests/repository/test_only_projection.py``.
"""

import pytest

from protean import Record
from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.exceptions import NotSupportedError
from protean.fields import Float, HasMany, Integer, String, ValueObject
from protean.core.entity import BaseEntity


class Task(BaseEntity):
    title: String(max_length=50)


class Money(BaseValueObject):
    currency: String(max_length=3)
    amount: Float()


class Document(BaseAggregate):
    title: String(max_length=50, required=True)
    status: String(max_length=20, default="draft")
    body: String(max_length=5000)  # the "expensive" column we want to skip
    revision: Integer(default=1)
    price = ValueObject(Money)  # flattens to price_currency / price_amount
    tasks: HasMany(Task)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Document)
    test_domain.register(Task, part_of=Document)
    test_domain.init(traverse=False)


def _seed(test_domain):
    repo = test_domain.repository_for(Document)
    repo.add(Document(title="Alpha", status="published", body="x" * 100, revision=3))
    repo.add(Document(title="Beta", status="draft", body="y" * 100, revision=1))
    return repo


class TestOnlyProjection:
    def test_only_returns_record_objects(self, test_domain):
        _seed(test_domain)
        repo = test_domain.repository_for(Document)

        records = repo.query.only("status").all().items

        assert len(records) == 2
        assert all(isinstance(record, Record) for record in records)

    def test_projected_fields_are_accessible(self, test_domain):
        _seed(test_domain)
        repo = test_domain.repository_for(Document)

        record = repo.query.filter(title="Alpha").only("status", "revision").all().first

        assert record.status == "published"
        assert record.revision == 3

    def test_identifier_always_included(self, test_domain):
        _seed(test_domain)
        repo = test_domain.repository_for(Document)

        record = repo.query.only("status").all().first

        # `id` was not requested but must still be present and addressable.
        assert "id" in record
        assert record.id is not None

    def test_non_projected_field_raises_on_attribute_access(self, test_domain):
        _seed(test_domain)
        repo = test_domain.repository_for(Document)

        record = repo.query.only("status").all().first

        with pytest.raises(AttributeError, match="has no field 'body'"):
            _ = record.body

    def test_non_projected_field_raises_on_item_access(self, test_domain):
        _seed(test_domain)
        repo = test_domain.repository_for(Document)

        record = repo.query.only("status").all().first

        with pytest.raises(KeyError):
            _ = record["body"]

    def test_only_twice_replaces_projection(self, test_domain):
        _seed(test_domain)
        repo = test_domain.repository_for(Document)

        record = repo.query.only("status").only("revision").all().first

        # Last call wins: `status` is gone, `revision` is present.
        assert record.revision is not None
        with pytest.raises(AttributeError):
            _ = record.status

    def test_only_with_no_args_clears_projection(self, test_domain):
        _seed(test_domain)
        repo = test_domain.repository_for(Document)

        entities = repo.query.only("status").only().all().items

        # Cleared projection restores full entity materialization.
        assert all(isinstance(e, Document) for e in entities)
        assert entities[0].body is not None

    def test_only_unknown_field_raises_keyerror(self, test_domain):
        repo = test_domain.repository_for(Document)

        with pytest.raises(KeyError, match="nonexistent"):
            repo.query.only("nonexistent")

    def test_only_association_field_raises_not_supported(self, test_domain):
        repo = test_domain.repository_for(Document)

        with pytest.raises(NotSupportedError, match="not a persisted field"):
            repo.query.only("tasks")

    def test_only_projects_value_object_shadow_attribute(self, test_domain):
        repo = test_domain.repository_for(Document)
        repo.add(Document(title="Priced", price=Money(currency="USD", amount=9.99)))

        # `price_amount` is a flattened VO attribute — present in attributes()
        # but not fields() — so it resolves through the attribute-name branch.
        record = repo.query.filter(title="Priced").only("price_amount").all().first

        assert record.price_amount == 9.99

    def test_filter_combines_with_only(self, test_domain):
        _seed(test_domain)
        repo = test_domain.repository_for(Document)

        records = repo.query.filter(status="draft").only("title").all().items

        assert len(records) == 1
        assert records[0].title == "Beta"

    def test_iteration_and_slicing_over_projection(self, test_domain):
        _seed(test_domain)
        repo = test_domain.repository_for(Document)

        qs = repo.query.order_by("title").only("title")

        # Iteration and slicing go through the deepcopy cache path.
        titles = [record.title for record in qs]
        assert titles == ["Alpha", "Beta"]
        assert qs[0].title == "Alpha"

    def test_rows_are_not_entities(self, test_domain):
        _seed(test_domain)
        repo = test_domain.repository_for(Document)

        record = repo.query.only("status").all().first

        # A projection carries no domain-entity machinery.
        assert not isinstance(record, BaseAggregate)
        assert not hasattr(record, "state_")

    def test_update_with_only_raises(self, test_domain):
        _seed(test_domain)
        repo = test_domain.repository_for(Document)

        with pytest.raises(NotSupportedError, match="cannot be combined with `only"):
            repo.query.only("status").update(status="archived")

    def test_delete_with_only_raises(self, test_domain):
        _seed(test_domain)
        repo = test_domain.repository_for(Document)

        with pytest.raises(NotSupportedError, match="cannot be combined with `only"):
            repo.query.only("status").delete()

    def test_count_with_only(self, test_domain):
        _seed(test_domain)
        repo = test_domain.repository_for(Document)

        # count() ignores projection (it never materializes records), so
        # `.only(...).count()` is a valid, cheap pattern.
        assert repo.query.only("status").count() == 2
        assert repo.query.filter(status="draft").only("status").count() == 1


class TestRecordValueType:
    def test_read_only(self):
        record = Record("Document", {"id": "1", "status": "draft"})

        with pytest.raises(NotSupportedError, match="read-only"):
            record.status = "published"

    def test_to_dict_and_keys(self):
        record = Record("Document", {"id": "1", "status": "draft"})

        assert record.to_dict() == {"id": "1", "status": "draft"}
        assert set(record.keys()) == {"id", "status"}

    def test_to_dict_is_a_copy(self):
        data = {"id": "1", "status": "draft"}
        record = Record("Document", data)

        record.to_dict()["status"] = "mutated"
        # Mutating the returned dict does not affect the Record.
        assert record.status == "draft"

    def test_equality(self):
        a = Record("Document", {"id": "1", "status": "draft"})
        b = Record("Document", {"id": "1", "status": "draft"})
        c = Record("Document", {"id": "2", "status": "draft"})

        assert a == b
        assert a != c
        assert a != {"id": "1", "status": "draft"}

    def test_repr_lists_projected_fields(self):
        record = Record("Document", {"id": "1", "status": "draft"})

        rendered = repr(record)
        assert "Document" in rendered
        assert "status='draft'" in rendered

    def test_deepcopy_preserves_read_only(self):
        import copy

        record = Record("Document", {"id": "1", "status": "draft"})
        clone = copy.deepcopy(record)

        assert clone == record
        with pytest.raises(NotSupportedError):
            clone.status = "published"

    def test_is_unhashable(self):
        record = Record("Document", {"id": "1", "status": "draft"})

        # Records are value carriers, not identities — deliberately unhashable.
        with pytest.raises(TypeError):
            hash(record)
