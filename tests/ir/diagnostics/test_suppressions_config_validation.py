"""Diagnostics: TestSuppressionsConfigValidation."""

import pytest

from protean import Domain
from protean.exceptions import ConfigurationError
from protean.fields.simple import String
from protean.ir.builder import IRBuilder


class TestSuppressionsConfigValidation:
    """``[lint].suppressions`` must be a table of non-negative integers."""

    def _domain_with_suppressions(self, suppressions) -> Domain:
        domain = Domain(name="BadSuppressions", root_path=".")
        domain.config["lint"] = {"suppressions": suppressions}

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        return domain

    @pytest.mark.parametrize(
        ("suppressions", "message"),
        [
            ({"AGGREGATE_TOO_LARGE": "3"}, "non-negative integer"),
            ({"AGGREGATE_TOO_LARGE": -1}, "non-negative integer"),
            # ``bool`` is an ``int`` subclass, so it must be rejected, not read as 1.
            ({"AGGREGATE_TOO_LARGE": True}, "non-negative integer"),
            (5, "table of"),
        ],
        ids=["string-count", "negative-count", "boolean-count", "non-table"],
    )
    def test_invalid_suppressions_raise_configuration_error(
        self, suppressions, message
    ):
        domain = self._domain_with_suppressions(suppressions)
        with pytest.raises(ConfigurationError, match=message):
            IRBuilder(domain).build()
