"""Logging helpers fall back quietly on the two failures they expect.

``get_logging_config_value`` returns the default when the ``[logging]`` value
is not a table. ``_reset_access_log_counters`` does nothing when no domain
context is active.
"""

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from protean.utils.globals import _domain_context_stack, g
from protean.utils.logging import (
    _reset_access_log_counters,
    get_logging_config_value,
)


@contextmanager
def _no_domain_context() -> Iterator[None]:
    popped = []
    while _domain_context_stack.top is not None:
        popped.append(_domain_context_stack.pop())
    try:
        yield
    finally:
        for ctx in reversed(popped):
            _domain_context_stack.push(ctx)


class TestGetLoggingConfigValue:
    def test_reads_the_configured_value(self, test_domain):
        test_domain.config["logging"]["slow_handler_threshold_ms"] = 42

        assert get_logging_config_value("slow_handler_threshold_ms", 500) == 42

    @pytest.mark.parametrize("bad_section", ["not-a-table", ["a", "b"], 7])
    def test_non_table_logging_section_returns_default(self, test_domain, bad_section):
        test_domain.config["logging"] = bad_section

        assert get_logging_config_value("slow_handler_threshold_ms", 500) == 500

    def test_no_domain_context_returns_default(self, test_domain):
        with _no_domain_context(), warnings.catch_warnings():
            warnings.simplefilter("error")
            assert get_logging_config_value("slow_handler_threshold_ms", 500) == 500

    @pytest.mark.parametrize("error", [RuntimeError, AttributeError])
    def test_unexpected_config_error_propagates(self, test_domain, error):
        with (
            patch.object(type(test_domain.config), "get", side_effect=error("boom")),
            pytest.raises(error, match="boom"),
        ):
            get_logging_config_value("slow_handler_threshold_ms", 500)


class TestResetAccessLogCounters:
    def test_resets_counters_on_g(self, test_domain):
        g._access_log_repo_loads = 3
        g._access_log_events_raised = ["Placed"]

        _reset_access_log_counters()

        assert g._access_log_repo_loads == 0
        assert g._access_log_repo_saves == 0
        assert g._access_log_events_raised == []
        assert g._access_log_uow_outcome == "no_uow"

    def test_no_domain_context_is_a_no_op(self, test_domain):
        with _no_domain_context(), warnings.catch_warnings():
            warnings.simplefilter("error")
            _reset_access_log_counters()
