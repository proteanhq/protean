"""Tests for [logging] domain.toml integration with Domain.configure_logging().

Verifies that:
- domain.toml [logging] section values are applied during configure_logging()
- Explicit kwargs override config values
- Environment variables override config but not kwargs
- per_logger map from config is applied
- redact list from config is passed through
"""

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import structlog

from protean import Domain


def _clear_root_logger() -> None:
    """Reset root logger state, removing pytest's LogCaptureHandler too."""
    root = logging.getLogger()
    root.handlers.clear()
    root.filters.clear()
    root.setLevel(logging.WARNING)


@pytest.mark.no_test_domain
class TestDomainTomlLoggingSection:
    """Config values from [logging] flow into configure_logging()."""

    def setup_method(self):
        structlog.reset_defaults()
        _clear_root_logger()

    def teardown_method(self):
        _clear_root_logger()

    def test_domain_toml_logging_section_applied(self):
        """Load a Domain with logging config; domain.init() applies it."""
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestLoggingConfig",
            config={
                "logging": {
                    "level": "DEBUG",
                    "per_logger": {
                        "protean.server.engine": "WARNING",
                    },
                }
            },
        )

        _clear_root_logger()

        with patch.dict(os.environ, {}, clear=True):
            domain.init(traverse=False)

        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert logging.getLogger("protean.server.engine").level == logging.WARNING

    def test_explicit_kwargs_override_config(self):
        """Explicit kwargs to configure_logging() win over config values."""
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestKwargsOverride",
            config={
                "logging": {
                    "level": "INFO",
                }
            },
        )

        _clear_root_logger()

        with patch.dict(os.environ, {}, clear=True):
            domain.configure_logging(level="DEBUG")

        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_env_var_overrides_config_but_not_kwargs(self):
        """PROTEAN_LOG_LEVEL overrides config, but explicit kwarg wins over env."""
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestEnvPrecedence",
            config={
                "logging": {
                    "level": "INFO",
                }
            },
        )

        _clear_root_logger()

        # Env var should override config (config level="INFO", env var="WARNING")
        with patch.dict(
            os.environ,
            {"PROTEAN_LOG_LEVEL": "WARNING"},
            clear=True,
        ):
            domain.configure_logging()

        root = logging.getLogger()
        assert root.level == logging.WARNING

        _clear_root_logger()

        # Explicit kwarg should override env var
        with patch.dict(
            os.environ,
            {"PROTEAN_LOG_LEVEL": "WARNING"},
            clear=True,
        ):
            domain.configure_logging(level="DEBUG")

        assert root.level == logging.DEBUG

    def test_redact_list_passed_to_configure_logging(self):
        """The redact list from [logging] config is accessible in domain config."""
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestRedactConfig",
            config={
                "logging": {
                    "redact": ["custom_field"],
                }
            },
        )

        # Verify the config was loaded (redact is plumbed through config,
        # to be consumed by the redaction filter in a future PR)
        assert domain.config["logging"]["redact"] == ["custom_field"]

    def test_per_logger_map_from_config(self):
        """per_logger from [logging.per_logger] sets individual logger levels."""
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestPerLogger",
            config={
                "logging": {
                    "per_logger": {
                        "myapp.orders": "DEBUG",
                        "myapp.payments": "ERROR",
                    },
                }
            },
        )

        _clear_root_logger()

        with patch.dict(os.environ, {}, clear=True):
            domain.configure_logging()

        assert logging.getLogger("myapp.orders").level == logging.DEBUG
        assert logging.getLogger("myapp.payments").level == logging.ERROR

    def test_format_config_applied(self):
        """format from [logging] config is applied."""
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestFormatConfig",
            config={
                "logging": {
                    "format": "json",
                }
            },
        )

        _clear_root_logger()

        with patch.dict(os.environ, {}, clear=True):
            domain.configure_logging()

        root = logging.getLogger()
        assert len(root.handlers) > 0

    def test_empty_level_uses_env_default(self):
        """Empty level string means 'use environment-based default'."""
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestEmptyLevel",
            config={
                "logging": {
                    "level": "",  # empty = env-based default
                }
            },
        )

        _clear_root_logger()

        with patch.dict(os.environ, {"PROTEAN_ENV": "production"}, clear=True):
            domain.configure_logging()

        root = logging.getLogger()
        assert root.level == logging.INFO  # production default

    def test_repeated_configure_logging_no_duplicate_filters(self):
        """Calling configure_logging() twice does not add duplicate filters."""
        from protean.integrations.logging import ProteanCorrelationFilter

        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestNoDuplicateFilters",
        )

        _clear_root_logger()

        with patch.dict(os.environ, {}, clear=True):
            domain.configure_logging()
            domain.configure_logging()

        root = logging.getLogger()
        correlation_filters = [
            f for f in root.filters if isinstance(f, ProteanCorrelationFilter)
        ]
        assert len(correlation_filters) == 1
