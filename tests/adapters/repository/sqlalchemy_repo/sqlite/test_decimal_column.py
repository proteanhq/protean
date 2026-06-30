"""SQLite coverage for the Decimal field → NUMERIC(precision, scale) mapping (#1038)."""

import pytest
from sqlalchemy import Numeric

from protean.core.aggregate import BaseAggregate
from protean.fields import Decimal, String


class Invoice(BaseAggregate):
    name = String(max_length=50)
    total = Decimal(precision=19, scale=4)
    discount = Decimal()  # no explicit precision/scale


@pytest.fixture
def invoice_columns(test_domain):
    test_domain.register(Invoice)
    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Invoice)._dao
    provider = test_domain.providers["default"]
    provider._metadata.create_all(provider._engine)
    return dao.database_model_cls.__table__.columns


@pytest.mark.sqlite
class TestDecimalColumnDDL:
    def test_decimal_maps_to_numeric_with_precision_scale(self, invoice_columns):
        col = invoice_columns["total"]
        assert isinstance(col.type, Numeric)
        assert col.type.precision == 19
        assert col.type.scale == 4

    def test_decimal_without_precision_scale_is_unbounded_numeric(
        self, invoice_columns
    ):
        col = invoice_columns["discount"]
        assert isinstance(col.type, Numeric)
        assert col.type.precision is None
        assert col.type.scale is None
