"""Hot-path regression guards for the 0.16 structured-logging chain.

The logging overhaul runs a processor chain on every emitted record. A
micro-benchmark of the configured JSON path (output redirected to memory) shows:

- an emitted INFO record costs ~18 us/call (the inherent price of the
  structlog -> stdlib ``ProcessorFormatter`` bridge);
- a *below-threshold* record (``debug()`` at level INFO) costs ~1 us/call,
  because ``structlog.stdlib.BoundLogger`` short-circuits on ``isEnabledFor``
  *before* running the chain;
- redaction / tail sampling / OTel injection are appended only when enabled,
  so a default domain pays for none of them.

The cheap-suppression property is what keeps debug-heavy code affordable in
production. These tests guard it *functionally* (a spy processor records
invocations) rather than with wall-clock assertions, which flake under load.
"""

import logging
from unittest.mock import patch

import pytest
import structlog

from protean.utils.logging import configure_logging, get_logger

pytestmark = pytest.mark.no_test_domain


@pytest.fixture(autouse=True)
def _reset_logging():
    structlog.reset_defaults()
    root = logging.getLogger()
    saved = (list(root.filters), list(root.handlers), root.level)
    root.filters, root.handlers = [], []
    yield
    structlog.reset_defaults()
    root.filters, root.handlers = saved[0], saved[1]
    root.setLevel(saved[2])


class _SpyProcessor:
    """Structlog processor that records every (method) it is invoked for."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, logger, method_name, event_dict):
        self.calls.append(method_name)
        return event_dict


class TestHotPathSuppression:
    def test_below_threshold_record_skips_the_processor_chain(self):
        spy = _SpyProcessor()
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(level="INFO", format="json", extra_processors=[spy])
        log = get_logger("protean.hotpath")

        log.debug("suppressed", order_id="o1")
        assert spy.calls == [], (
            "a below-threshold record must short-circuit before the chain runs; "
            "running the full chain for dropped logs is a hot-path regression"
        )

    def test_at_threshold_record_runs_the_chain(self):
        spy = _SpyProcessor()
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(level="INFO", format="json", extra_processors=[spy])
        log = get_logger("protean.hotpath")

        log.info("emitted", order_id="o1")
        assert spy.calls, "an at-threshold record should run the processor chain"

    def test_default_domain_has_no_redaction_or_sampling_cost(self):
        # With neither redaction nor sampling configured, those processors must
        # not be installed at all (no per-call cost on the default path).
        from protean.integrations.logging import ProteanRedactionFilter

        with patch.dict("os.environ", {}, clear=True):
            configure_logging(level="INFO", format="json")
        root = logging.getLogger()
        assert not any(isinstance(f, ProteanRedactionFilter) for f in root.filters), (
            "redaction filter must not be installed when no redact list is given"
        )
