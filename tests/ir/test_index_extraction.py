"""Tests for IRBuilder index extraction and schema metadata."""

import pytest

from protean import Index, Q
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.ir.builder import IRBuilder
from protean.ir.generators.schema import generate_element_schema


def _indexed_domain():
    from protean.domain import Domain

    domain = Domain(name="IRIndexes")

    @domain.aggregate(
        indexes=[
            Index(
                "status",
                "priority",
                desc=("priority",),
                where=Q(status="active"),
                name="ix_active",
            ),
            Index("sku", unique=True),
            Index.from_sql("postgresql", "CREATE INDEX gx ON product (status)"),
        ]
    )
    class Product(BaseAggregate):
        status = String(max_length=32)
        priority = Integer()
        sku = String(max_length=64)

    domain.init(traverse=False)
    return domain, Product


@pytest.mark.no_test_domain
class TestIndexExtraction:
    def test_extracts_index_summaries(self):
        domain, product_cls = _indexed_domain()
        builder = IRBuilder(domain)
        indexes = builder._extract_indexes(product_cls)

        assert len(indexes) == 3
        partial = next(i for i in indexes if i.get("name") == "ix_active")
        assert partial["fields"] == ["status", "priority"]
        assert partial["desc"] == ["priority"]
        assert partial["partial"] is True

        unique = next(i for i in indexes if i.get("unique"))
        assert unique["fields"] == ["sku"]

        raw = next(i for i in indexes if i.get("raw"))
        assert raw["dialect"] == "postgresql"
        assert "gx" in raw["ddl"]

    def test_no_indexes_returns_empty(self):
        from protean.domain import Domain

        domain = Domain(name="NoIdx")

        @domain.aggregate
        class Plain(BaseAggregate):
            name = String(max_length=32)

        domain.init(traverse=False)
        builder = IRBuilder(domain)
        assert builder._extract_indexes(Plain) == []

    def test_schema_includes_x_protean_indexes(self):
        domain, _product_cls = _indexed_domain()
        ir = domain.to_ir()

        # Locate the Product aggregate IR entry.
        agg_ir = None
        for cluster in ir["clusters"].values():
            if cluster.get("aggregate", {}).get("name") == "Product":
                agg_ir = cluster["aggregate"]
                break
        assert agg_ir is not None

        schema = generate_element_schema(agg_ir)
        assert "x-protean-indexes" in schema
        assert len(schema["x-protean-indexes"]) == 3
