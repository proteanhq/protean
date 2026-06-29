"""Interaction tests for tail sampling × sensitive-field redaction.

These two 0.16 logging features compose on the same wide-event path:
``Domain.configure_logging`` installs a ``TailSamplingFilter`` on the
``protean.access`` stdlib logger (the keep/drop decision) and appends the
redaction processor to the chain that the root handler's ``ProcessorFormatter``
runs as its ``foreign_pre_chain``.

The security-relevant invariant is that **redaction always runs on whatever
sampling keeps**, and a dropped event never reaches the renderer at all. The
ordering is deliberate (sampling reads the un-redacted ``status`` /
``message_type``; redaction masks what survives) so these tests lock it in with
both a positive (kept → masked) and negative (dropped → nothing leaks) path.
"""

import logging
from io import StringIO
from unittest.mock import patch

import pytest
import structlog

from protean import Domain


@pytest.fixture(autouse=True)
def _reset_logging():
    """Snapshot and restore global logging state around each test."""
    structlog.reset_defaults()
    root = logging.getLogger()
    access = logging.getLogger("protean.access")
    saved = (
        list(root.filters),
        list(root.handlers),
        root.level,
        list(access.filters),
        access.level,
    )
    root.filters, root.handlers = [], []
    access.filters = []
    yield
    structlog.reset_defaults()
    root.filters, root.handlers, root.level = saved[0], saved[1], saved[2]
    access.filters, access.level = saved[3], saved[4]


def _configure(sampling: dict) -> StringIO:
    """Configure a domain with redaction + the given sampling config.

    Returns a buffer wired to the handler ``configure_logging`` installed, so
    the *rendered* (post-redaction) output can be inspected.
    """
    domain = Domain(name="SamplingRedaction")
    domain.config["logging"] = {"redact": ["password"], "sampling": sampling}
    with patch.dict("os.environ", {}, clear=True):
        domain.configure_logging(level="DEBUG", format="json")

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # configure_logging installs a single ProcessorFormatter-backed handler;
    # redirect its stream so we can read what is actually emitted.
    handler = next(h for h in root.handlers if hasattr(h, "stream"))
    buf = StringIO()
    handler.stream = buf

    access = logging.getLogger("protean.access")
    access.setLevel(logging.DEBUG)
    return buf


def _emit_wide_event(level: int, status: str, message_type: str) -> None:
    """Emit a wide access event carrying a sensitive ``password`` field."""
    logging.getLogger("protean.access").log(
        level,
        "access.handler_completed",
        extra={
            "status": status,
            "message_type": message_type,
            "password": "s3cret",
        },
    )


class TestSamplingRedactionInteraction:
    def test_kept_event_is_redacted(self):
        # default_rate=1.0 keeps every event; the kept event must still be masked.
        buf = _configure({"enabled": True, "default_rate": 1.0})
        _emit_wide_event(logging.INFO, status="ok", message_type="UpdateProfile")

        output = buf.getvalue()
        assert output, "a kept event should be emitted"
        assert '"sampling_decision": "kept"' in output
        assert "[REDACTED]" in output
        assert "s3cret" not in output

    def test_dropped_event_leaks_nothing(self):
        # default_rate=0.0 drops happy-path events; nothing (incl. the secret)
        # may reach the renderer.
        buf = _configure(
            {"enabled": True, "default_rate": 0.0, "always_keep_errors": True}
        )
        _emit_wide_event(logging.INFO, status="ok", message_type="UpdateProfile")

        output = buf.getvalue()
        assert output == "", "a dropped event must not be emitted at all"
        assert "s3cret" not in output

    def test_always_kept_error_is_still_redacted(self):
        # Errors are force-kept even at rate 0.0 — they must not bypass redaction.
        buf = _configure({"enabled": True, "default_rate": 0.0})
        _emit_wide_event(logging.ERROR, status="failed", message_type="UpdateProfile")

        output = buf.getvalue()
        assert output, "an error event should be force-kept"
        assert "[REDACTED]" in output
        assert "s3cret" not in output
