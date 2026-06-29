"""Hot-path regression guards for the 0.16 structured-logging chain.

The logging overhaul runs a processor chain on every record. A micro-benchmark
of the configured JSON path (output redirected to memory) shows:

- an emitted INFO record costs ~18 us/call (the inherent price of the
  structlog -> stdlib ``ProcessorFormatter`` bridge);
- a *below-threshold* record (``debug()`` at level INFO) costs ~1 us/call,
  because ``filter_by_level`` sits at the **head** of the chain and drops the
  record before the expensive ``CallsiteParameterAdder`` and renderer run
  (``structlog.stdlib.BoundLogger`` itself does not short-circuit, so the order
  is what matters);
- redaction / tail sampling / OTel injection are appended only when enabled,
  so a default domain pays for none of them.

The cheap-suppression property keeps debug-heavy code affordable in production.
These tests guard it *structurally* (the level filter precedes the costly
processors) and *functionally* (a dropped record never reaches the chain tail),
rather than with wall-clock assertions, which flake under load.
"""

import logging
from unittest.mock import patch

import pytest
import structlog

from protean.integrations.logging import ProteanRedactionFilter
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


def _processor_names() -> list[str]:
    return [
        getattr(p, "__name__", type(p).__name__)
        for p in structlog.get_config()["processors"]
    ]


class _SpyProcessor:
    """Structlog processor that records every method it is invoked for."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, logger, method_name, event_dict):
        self.calls.append(method_name)
        return event_dict


class TestHotPathSuppression:
    def test_level_filter_precedes_the_expensive_processors(self):
        # The mechanism that makes below-threshold records cheap: the level
        # filter drops them at the head of the chain, before the costly
        # callsite/render processors run. If a regression reorders or drops it,
        # suppressed logs would pay the full chain cost.
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(level="INFO", format="json")
        names = _processor_names()

        assert names[0] == "filter_by_level", (
            f"filter_by_level must be the first processor, got order: {names}"
        )
        level_idx = names.index("filter_by_level")
        assert level_idx < names.index("CallsiteParameterAdder"), (
            "the costly CallsiteParameterAdder must run after the level filter "
            "so it is skipped for dropped records"
        )
        assert level_idx < names.index("JSONRenderer")

    def test_below_threshold_record_never_reaches_the_chain_tail(self):
        # A processor appended near the tail must not run for a dropped record
        # (it is short-circuited by the head-of-chain level filter), but must
        # run for an at-threshold record.
        spy = _SpyProcessor()
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(level="INFO", format="json", extra_processors=[spy])
        log = get_logger("protean.hotpath")

        log.debug("suppressed", order_id="o1")
        assert spy.calls == [], (
            "a below-threshold record must be dropped before the chain tail; "
            "running the tail for dropped logs is a hot-path regression"
        )

        log.info("emitted", order_id="o1")
        assert spy.calls, "an at-threshold record should reach the chain tail"

    def test_default_path_installs_no_redaction_filter(self):
        # With no redact list configured, the redaction filter must not be
        # installed at all, so the default path pays no per-record masking cost.
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(level="INFO", format="json")
        root = logging.getLogger()
        assert not any(isinstance(f, ProteanRedactionFilter) for f in root.filters)
