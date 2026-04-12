"""Tests for auto-configuration of logging during Domain.init().

Verifies that:
- Domain.init() auto-configures logging when no handlers exist
- PROTEAN_NO_AUTO_LOGGING=1 disables auto-configuration
- Pre-existing handlers prevent auto-configuration (idempotency)
- Failure in configure_logging does not break Domain.init()
"""

import logging
import os
import sys
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
class TestAutoConfigureLogging:
    """Auto-configuration of logging during Domain.init()."""

    def setup_method(self):
        structlog.reset_defaults()
        _clear_root_logger()

    def teardown_method(self):
        _clear_root_logger()

    def test_domain_init_auto_configures_logging(self):
        """Fresh Domain with no handlers on root logger gets logging configured."""
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestAutoConfig",
        )

        # Clear right before init — pytest may have re-added LogCaptureHandler
        _clear_root_logger()
        root = logging.getLogger()

        with patch.dict(os.environ, {}, clear=True):
            domain.init(traverse=False)

        assert len(root.handlers) > 0, "Auto-config should add handlers"
        assert root.level == logging.DEBUG  # development default

    @pytest.mark.parametrize("env_value", ["1", "true", "True", "TRUE"])
    def test_protean_no_auto_logging_env_var(self, env_value: str):
        """PROTEAN_NO_AUTO_LOGGING=1 or true prevents auto-configuration."""
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestNoAutoLogging",
        )

        _clear_root_logger()
        root = logging.getLogger()

        with patch.dict(os.environ, {"PROTEAN_NO_AUTO_LOGGING": env_value}, clear=True):
            domain.init(traverse=False)

        # No handlers should have been added by auto-config
        assert len(root.handlers) == 0

    def test_pre_existing_handlers_skip_auto_config(self):
        """If root logger already has handlers, auto-config is skipped."""
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestPreExisting",
        )

        _clear_root_logger()
        root = logging.getLogger()

        # Add a pre-existing handler
        existing_handler = logging.StreamHandler(sys.stderr)
        root.addHandler(existing_handler)
        handler_count_before = len(root.handlers)

        with patch.dict(os.environ, {}, clear=True):
            domain.init(traverse=False)

        # The pre-existing handler should still be there, no new ones added
        assert existing_handler in root.handlers
        assert len(root.handlers) == handler_count_before

    def test_auto_config_failure_is_nonfatal(self):
        """If configure_logging raises, Domain.init() still succeeds."""
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestNonfatalFailure",
        )

        _clear_root_logger()

        with patch(
            "protean.domain.Domain.configure_logging",
            side_effect=RuntimeError("logging boom"),
        ):
            with patch.dict(os.environ, {}, clear=True):
                # Should not raise
                domain.init(traverse=False)

    def test_auto_config_uses_domain_toml_logging_section(self):
        """Auto-configuration picks up [logging] from domain config."""
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestAutoConfigToml",
            config={
                "logging": {
                    "level": "ERROR",
                }
            },
        )

        _clear_root_logger()
        root = logging.getLogger()

        with patch.dict(os.environ, {}, clear=True):
            domain.init(traverse=False)

        assert root.level == logging.ERROR
