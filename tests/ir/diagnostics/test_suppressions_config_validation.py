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

    def test_string_count_raises_configuration_error(self):
        domain = self._domain_with_suppressions({"AGGREGATE_TOO_LARGE": "3"})
        with pytest.raises(ConfigurationError, match="non-negative integer"):
            IRBuilder(domain).build()

    def test_negative_count_raises_configuration_error(self):
        domain = self._domain_with_suppressions({"AGGREGATE_TOO_LARGE": -1})
        with pytest.raises(ConfigurationError, match="non-negative integer"):
            IRBuilder(domain).build()

    def test_boolean_count_raises_configuration_error(self):
        # ``bool`` is an ``int`` subclass — must be rejected, not read as 1.
        domain = self._domain_with_suppressions({"AGGREGATE_TOO_LARGE": True})
        with pytest.raises(ConfigurationError, match="non-negative integer"):
            IRBuilder(domain).build()

    def test_non_table_raises_configuration_error(self):
        domain = self._domain_with_suppressions(5)
        with pytest.raises(ConfigurationError, match="table of"):
            IRBuilder(domain).build()

    def test_valid_zero_count_does_not_raise(self):
        domain = self._domain_with_suppressions(
            {"AGGREGATE_WITHOUT_COMMAND_HANDLER": 0}
        )
        # Must build cleanly — 0 is a valid non-negative integer.
        ir = IRBuilder(domain).build()
        assert any(
            d["code"] == "AGGREGATE_WITHOUT_COMMAND_HANDLER" for d in ir["diagnostics"]
        )
