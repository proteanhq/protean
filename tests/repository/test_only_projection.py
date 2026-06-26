"""Cross-adapter tests for ``QuerySet.only()`` projection.

Marker-gated so they exercise SQLAlchemy (Postgres/SQLite/MSSQL) and
Elasticsearch backends in addition to the in-memory default. The same
behaviours are covered against memory in ``tests/query/test_only_projection.py``.
"""

import pytest

from protean import Record
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String


class Article(BaseAggregate):
    title: String(max_length=50, required=True)
    status: String(max_length=20, default="draft")
    body: String(max_length=5000)
    views: Integer(default=0)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Article)
    test_domain.init(traverse=False)


@pytest.mark.basic_storage
@pytest.mark.usefixtures("db")
class TestOnlyProjectionAcrossAdapters:
    def _seed(self, test_domain):
        repo = test_domain.repository_for(Article)
        repo.add(Article(title="Alpha", status="published", body="a" * 200, views=10))
        repo.add(Article(title="Beta", status="draft", body="b" * 200, views=5))
        return repo

    def test_only_projects_requested_fields(self, test_domain):
        self._seed(test_domain)
        repo = test_domain.repository_for(Article)

        records = repo.query.order_by("title").only("status", "views").all().items

        assert len(records) == 2
        assert all(isinstance(record, Record) for record in records)
        assert records[0].status == "published"
        assert records[0].views == 10

    def test_identifier_included_without_request(self, test_domain):
        self._seed(test_domain)
        repo = test_domain.repository_for(Article)

        record = repo.query.only("status").all().first

        assert record.id is not None

    def test_non_projected_field_absent(self, test_domain):
        self._seed(test_domain)
        repo = test_domain.repository_for(Article)

        record = repo.query.only("status").all().first

        assert "body" not in record
        with pytest.raises(AttributeError):
            _ = record.body

    def test_filter_combines_with_only(self, test_domain):
        self._seed(test_domain)
        repo = test_domain.repository_for(Article)

        records = repo.query.filter(status="published").only("title").all().items

        assert len(records) == 1
        assert records[0].title == "Alpha"
