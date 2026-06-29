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
processors) and via a *self-contained* check of the filter itself, rather than
by emitting through a shared logger whose effective level other tests can
mutate (an isolation hazard that flaked only under the full suite on 3.14).
"""

import logging

import pytest
import structlog

from protean.integrations.logging import ProteanRedactionFilter
from protean.utils.logging import configure_logging

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


class TestHotPathSuppression:
    def test_level_filter_precedes_the_expensive_processors(self):
        # The mechanism that makes below-threshold records cheap: the level
        # filter drops them at the head of the chain, before the costly
        # callsite/render processors run. If a regression reorders or removes
        # it, suppressed logs would pay the full chain cost.
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

    def test_head_filter_drops_below_threshold_records(self):
        # Verify the head-of-chain filter actually drops a below-threshold
        # record (and passes an at-threshold one). Uses a logger whose level we
        # set explicitly, so the result never depends on global logging state
        # another test may have mutated.
        logger = logging.getLogger("protean.tests.hotpath.isolated")
        logger.setLevel(logging.INFO)

        with pytest.raises(structlog.DropEvent):
            structlog.stdlib.filter_by_level(logger, "debug", {"event": "dropped"})

        kept = structlog.stdlib.filter_by_level(logger, "info", {"event": "kept"})
        assert kept == {"event": "kept"}

    def test_default_path_installs_no_redaction_filter(self):
        # With no redact list configured, the redaction filter must not be
        # installed at all, so the default path pays no per-record masking cost.
        configure_logging(level="INFO", format="json")
        root = logging.getLogger()
        assert not any(isinstance(f, ProteanRedactionFilter) for f in root.filters)
