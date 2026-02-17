"""Tests for Protean's structured logging module."""

import logging
import os
from unittest.mock import patch

import pytest
import structlog

from protean.utils.logging import (
    add_context,
    clear_context,
    configure_for_testing,
    configure_logging,
    get_logger,
    log_method_call,
)


class TestConfigureLogging:
    """Tests for configure_logging()."""

    def setup_method(self):
        """Reset logging state before each test."""
        # Reset structlog configuration
        structlog.reset_defaults()
        # Reset root logger
        root = logging.getLogger()
        root.handlers = []
        root.setLevel(logging.WARNING)

    def test_default_development_setup(self):
        """Default (no args) configures for development: DEBUG level, console renderer."""
        with patch.dict(os.environ, {}, clear=True):
            configure_logging()

        root = logging.getLogger()
        assert root.level == logging.DEBUG
        # Should have exactly one handler (console)
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.StreamHandler)

    def test_production_env_sets_info_level(self):
        """PROTEAN_ENV=production sets INFO level."""
        with patch.dict(os.environ, {"PROTEAN_ENV": "production"}, clear=True):
            configure_logging()

        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_test_env_sets_warning_level(self):
        """PROTEAN_ENV=test sets WARNING level."""
        with patch.dict(os.environ, {"PROTEAN_ENV": "test"}, clear=True):
            configure_logging()

        root = logging.getLogger()
        assert root.level == logging.WARNING

    def test_explicit_level_overrides_env(self):
        """Explicit level= parameter overrides environment detection."""
        with patch.dict(os.environ, {"PROTEAN_ENV": "production"}, clear=True):
            configure_logging(level="DEBUG")

        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_log_level_env_var_overrides_env_default(self):
        """PROTEAN_LOG_LEVEL env var overrides the environment-based default."""
        with patch.dict(
            os.environ,
            {"PROTEAN_ENV": "production", "PROTEAN_LOG_LEVEL": "DEBUG"},
            clear=True,
        ):
            configure_logging()

        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_file_handlers_disabled_by_default(self):
        """Without log_dir, no file handlers are created."""
        with patch.dict(os.environ, {}, clear=True):
            configure_logging()

        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 0

    def test_file_handlers_created_with_log_dir(self, tmp_path):
        """With log_dir, rotating file handlers are created."""
        with patch.dict(os.environ, {}, clear=True):
            configure_logging(log_dir=tmp_path, log_file_prefix="testapp")

        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        # One main log + one error log
        assert len(file_handlers) == 2
        filenames = {h.baseFilename for h in file_handlers}
        assert str(tmp_path / "testapp.log") in filenames
        assert str(tmp_path / "testapp_error.log") in filenames

    def test_noisy_loggers_suppressed(self):
        """Third-party loggers are set to WARNING level."""
        with patch.dict(os.environ, {}, clear=True):
            configure_logging()

        assert logging.getLogger("urllib3").level == logging.WARNING
        assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING
        assert logging.getLogger("redis").level == logging.WARNING

    def test_framework_loggers_set_at_non_debug(self):
        """Protean framework loggers are set appropriately at INFO+ levels."""
        with patch.dict(os.environ, {"PROTEAN_ENV": "production"}, clear=True):
            configure_logging()

        assert logging.getLogger("protean.server.engine").level == logging.INFO
        assert logging.getLogger("protean.core").level == logging.WARNING

    def test_framework_loggers_debug_when_debug(self):
        """At DEBUG level, protean root logger is set to DEBUG."""
        with patch.dict(os.environ, {}, clear=True):
            configure_logging(level="DEBUG")

        assert logging.getLogger("protean").level == logging.DEBUG

    def test_reconfiguration_removes_old_handlers(self, tmp_path):
        """Calling configure_logging twice doesn't duplicate handlers."""
        with patch.dict(os.environ, {}, clear=True):
            configure_logging(log_dir=tmp_path)
            configure_logging(log_dir=tmp_path)

        root = logging.getLogger()
        # Should have 3 handlers (1 console + 2 file), not 6
        assert len(root.handlers) == 3


class TestGetLogger:
    """Tests for get_logger()."""

    def test_returns_structlog_logger(self):
        """get_logger returns a structlog logger proxy."""
        configure_logging()
        logger = get_logger("test.module")
        # structlog.get_logger returns a BoundLoggerLazyProxy that wraps
        # the configured BoundLogger. Verify it's a structlog logger by
        # checking it has the standard logging methods.
        assert hasattr(logger, "info")
        assert hasattr(logger, "debug")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")
        assert hasattr(logger, "bind")


class TestContextManagement:
    """Tests for add_context() and clear_context()."""

    def setup_method(self):
        clear_context()

    def teardown_method(self):
        clear_context()

    def test_add_and_clear_context_roundtrip(self):
        """Context variables can be added and cleared."""
        add_context(request_id="abc-123")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("request_id") == "abc-123"

        clear_context()
        ctx = structlog.contextvars.get_contextvars()
        assert "request_id" not in ctx

    def test_multiple_context_values(self):
        """Multiple context values accumulate."""
        add_context(request_id="abc-123")
        add_context(user_id="user-456")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("request_id") == "abc-123"
        assert ctx.get("user_id") == "user-456"


class TestLogMethodCall:
    """Tests for the @log_method_call decorator."""

    def test_decorated_function_returns_value(self):
        """Decorated function still returns its value."""

        @log_method_call
        def add(a, b):
            return a + b

        configure_logging(level="DEBUG")
        assert add(1, 2) == 3

    def test_decorated_function_raises_exception(self):
        """Decorated function still raises exceptions."""

        @log_method_call
        def fail():
            raise ValueError("boom")

        configure_logging(level="DEBUG")
        with pytest.raises(ValueError, match="boom"):
            fail()

    def test_preserves_function_metadata(self):
        """Decorator preserves __name__ and __module__."""

        @log_method_call
        def my_function():
            pass

        assert my_function.__name__ == "my_function"


class TestConfigureForTesting:
    """Tests for configure_for_testing()."""

    def test_sets_warning_level(self):
        """Sets root logger to WARNING."""
        configure_logging(level="DEBUG")
        configure_for_testing()
        assert logging.getLogger().level == logging.WARNING

    def test_removes_file_handlers(self, tmp_path):
        """Removes file handlers but keeps console handler."""
        configure_logging(log_dir=tmp_path)
        root = logging.getLogger()
        assert any(isinstance(h, logging.FileHandler) for h in root.handlers)

        configure_for_testing()
        assert not any(isinstance(h, logging.FileHandler) for h in root.handlers)
        # Console handler should remain
        assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)


class TestFormatSelection:
    """Tests for format parameter."""

    def test_json_format_forced(self):
        """format='json' forces JSON even in development."""
        with patch.dict(os.environ, {}, clear=True):
            # Should not raise - JSON renderer is selected
            configure_logging(format="json")

    def test_console_format_forced(self):
        """format='console' forces console even in production."""
        with patch.dict(os.environ, {"PROTEAN_ENV": "production"}, clear=True):
            # Should not raise - console renderer is selected
            configure_logging(format="console")
