"""Diagnostics: TestLintTableConfigValidation."""

import pytest

from protean import Domain
from protean.exceptions import ConfigurationError
from protean.fields.simple import String
from protean.ir.builder import IRBuilder


class TestLintTableConfigValidation:
    """``[lint]`` itself must be a table — non-CLI entry points (``protean
    generate``, materialize hooks, staleness detection) build the IR directly
    without going through ``protean check``'s validation, so the builder must
    reject a malformed ``[lint]`` before any ``[lint]``-scoped rule reads it."""

    def test_non_table_lint_raises_configuration_error(self):
        domain = Domain(name="BadLintTable", root_path=".")
        domain.config["lint"] = 5

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        with pytest.raises(ConfigurationError, match=r"\[lint\] must be a table"):
            IRBuilder(domain).build()

    def test_non_table_lint_raises_before_aggregate_size_limit_read(self):
        """``aggregate_size_limit`` runs before the suppression
        stage in ``_collect_diagnostics`` — the guard must fire before *any*
        rule reads ``[lint]``, not just before ``_apply_suppressions``."""
        domain = Domain(name="BadLintTableEarly", root_path=".")
        domain.config["lint"] = "not-a-table"

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        with pytest.raises(ConfigurationError, match=r"\[lint\] must be a table"):
            IRBuilder(domain).build()
