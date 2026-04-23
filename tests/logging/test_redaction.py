"""Tests for sensitive-field redaction in log output.

Verifies:
- ``ProteanRedactionFilter`` masks top-level and nested values on stdlib
  ``LogRecord`` objects.
- ``make_redaction_processor`` / ``protean_redaction_processor`` mask the
  same fields in structlog event dicts.
- The default redact list (password, token, secret, api_key, authorization,
  cookie, session, csrf) is applied when no custom list is provided.
- Matching is case-insensitive.
- Recursion is bounded so pathological payloads do not stall logging.
- ``log_method_call`` inherits redaction via the structlog chain when
  ``configure_logging(redact=[...])`` is called.
"""

import logging
import time
from io import StringIO
from unittest.mock import patch

import pytest
import structlog

from protean.integrations.logging import (
    DEFAULT_REDACT_KEYS,
    ProteanRedactionFilter,
    make_redaction_processor,
    protean_redaction_processor,
)
from protean.utils.logging import configure_logging, get_logger, log_method_call


@pytest.fixture(autouse=True)
def _reset_logging():
    """Reset structlog and root logger state around each test."""
    structlog.reset_defaults()
    root = logging.getLogger()
    saved_filters = list(root.filters)
    saved_handlers = list(root.handlers)
    saved_level = root.level
    root.filters = []
    root.handlers = []
    yield
    structlog.reset_defaults()
    root.filters = saved_filters
    root.handlers = saved_handlers
    root.setLevel(saved_level)


class TestRedactionProcessor:
    """Structlog processor masks matching keys in the event dict."""

    def test_top_level_password_redacted(self):
        proc = protean_redaction_processor
        event = {"event": "login", "password": "s3cret", "username": "alice"}
        out = proc(None, "info", event)
        assert out["password"] == "[REDACTED]"
        assert out["username"] == "alice"

    def test_nested_dict_redacted(self):
        proc = protean_redaction_processor
        event = {
            "event": "request",
            "payload": {
                "headers": {"authorization": "Bearer abc"},
                "body": {"x": 1},
            },
        }
        out = proc(None, "info", event)
        assert out["payload"]["headers"]["authorization"] == "[REDACTED]"
        assert out["payload"]["body"]["x"] == 1

    def test_list_of_dicts_redacted(self):
        proc = protean_redaction_processor
        event = {
            "event": "bulk",
            "users": [
                {"name": "a", "token": "t1"},
                {"name": "b", "token": "t2"},
            ],
        }
        out = proc(None, "info", event)
        assert out["users"][0]["token"] == "[REDACTED]"
        assert out["users"][1]["token"] == "[REDACTED]"
        assert out["users"][0]["name"] == "a"
        assert out["users"][1]["name"] == "b"

    def test_custom_redact_list_masks_custom_field(self):
        proc = make_redaction_processor(["x_custom_field"])
        event = {"event": "evt", "x_custom_field": "sensitive"}
        out = proc(None, "info", event)
        assert out["x_custom_field"] == "[REDACTED]"

    def test_custom_redact_list_unions_with_defaults(self):
        """An explicit list extends (does not replace) the defaults.

        Operators cannot accidentally turn off masking of core fields like
        ``password`` by supplying their own list — the configured list is
        unioned with :data:`DEFAULT_REDACT_KEYS`.
        """
        proc = make_redaction_processor(["only_this"])
        event = {"event": "evt", "password": "still_masked", "only_this": "gone"}
        out = proc(None, "info", event)
        assert out["only_this"] == "[REDACTED]"
        assert out["password"] == "[REDACTED]"

    def test_case_insensitive(self):
        proc = protean_redaction_processor
        event = {"event": "evt", "Password": "X", "TOKEN": "Y"}
        out = proc(None, "info", event)
        assert out["Password"] == "[REDACTED]"
        assert out["TOKEN"] == "[REDACTED]"

    def test_recursion_depth_bounded(self):
        """Pathological nested payloads should not stall the processor."""
        deep: dict = {"token": "leaked"}
        for _ in range(100):
            deep = {"next": deep}
        event = {"event": "deep", "payload": deep}

        start = time.perf_counter()
        out = protean_redaction_processor(None, "info", event)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0
        # The processor returned something sensible — we don't care about the
        # contents beyond "no exception, no hang".
        assert "payload" in out

    def test_non_string_keys_ignored(self):
        proc = protean_redaction_processor
        event = {"event": "evt", 42: "not_a_string_key"}
        out = proc(None, "info", event)
        assert out[42] == "not_a_string_key"

    def test_default_keys_include_cookie_session_csrf(self):
        """Default redact list covers the three session-hijack vectors."""
        assert "cookie" in DEFAULT_REDACT_KEYS
        assert "session" in DEFAULT_REDACT_KEYS
        assert "csrf" in DEFAULT_REDACT_KEYS


class TestRedactionFilter:
    """Stdlib filter masks matching attributes on the LogRecord."""

    def _build_record(self, **extra):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        for k, v in extra.items():
            setattr(record, k, v)
        return record

    def test_top_level_attribute_redacted(self):
        filt = ProteanRedactionFilter()
        record = self._build_record(password="secret", user="alice")
        assert filt.filter(record) is True
        assert record.password == "[REDACTED]"  # type: ignore[attr-defined]
        assert record.user == "alice"  # type: ignore[attr-defined]

    def test_nested_dict_attribute_redacted(self):
        filt = ProteanRedactionFilter()
        record = self._build_record(payload={"authorization": "Bearer x", "safe": "v"})
        filt.filter(record)
        assert record.payload["authorization"] == "[REDACTED]"  # type: ignore[attr-defined]
        assert record.payload["safe"] == "v"  # type: ignore[attr-defined]

    def test_custom_redact_list_unions_with_defaults(self):
        filt = ProteanRedactionFilter(redact=["my_secret_key"])
        record = self._build_record(my_secret_key="v", password="still_masked")
        filt.filter(record)
        assert record.my_secret_key == "[REDACTED]"  # type: ignore[attr-defined]
        # Defaults remain in effect alongside the configured custom keys.
        assert record.password == "[REDACTED]"  # type: ignore[attr-defined]

    def test_reserved_attrs_are_not_touched(self):
        filt = ProteanRedactionFilter()
        record = self._build_record(password="leaked")
        filt.filter(record)
        # LogRecord's own attributes must be preserved verbatim.
        assert record.name == "test"
        assert record.levelname == "INFO"

    def test_filter_never_suppresses_record(self):
        filt = ProteanRedactionFilter()
        record = self._build_record(password="x")
        assert filt.filter(record) is True


class TestConfigureLoggingWiresRedaction:
    """``configure_logging(redact=[...])`` wires both filter and processor."""

    def test_root_logger_has_redaction_filter(self):
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(level="DEBUG", format="json", redact=["password"])

        root = logging.getLogger()
        assert any(isinstance(f, ProteanRedactionFilter) for f in root.filters)

    def test_redaction_filter_not_installed_when_redact_is_none(self):
        """Opt-in only — no filter installed when ``redact`` is not provided."""
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(level="DEBUG", format="json")

        root = logging.getLogger()
        assert not any(isinstance(f, ProteanRedactionFilter) for f in root.filters)

    def test_dict_config_path_installs_redaction_filter(self):
        """The dictConfig code path also installs the filter when ``redact`` is set."""
        minimal_dict_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": "INFO",
                }
            },
            "root": {"handlers": ["console"], "level": "INFO"},
        }
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(dict_config=minimal_dict_config, redact=["password"])

        root = logging.getLogger()
        assert any(isinstance(f, ProteanRedactionFilter) for f in root.filters)

    def test_structlog_event_dict_is_redacted(self):
        """Structlog pipeline masks sensitive kwargs end-to-end."""
        buf = StringIO()

        with patch.dict("os.environ", {}, clear=True):
            configure_logging(level="DEBUG", format="json", redact=["password"])

        # Redirect the ProcessorFormatter's output to a buffer we can inspect
        # by replacing the stream on the existing handler — that keeps the
        # formatter wiring configure_logging() installed.
        root = logging.getLogger()
        assert len(root.handlers) == 1, "configure_logging installed a single handler"
        root.handlers[0].stream = buf
        root.setLevel(logging.DEBUG)

        sl = get_logger("protean.test.redaction")
        sl.info("login_attempt", password="s3cret", username="alice")

        output = buf.getvalue()
        assert "[REDACTED]" in output
        assert "s3cret" not in output
        assert "alice" in output

    def test_log_method_call_redacts_kwargs(self):
        """@log_method_call inherits redaction transparently via structlog."""
        buf = StringIO()

        with patch.dict("os.environ", {}, clear=True):
            configure_logging(level="DEBUG", format="json", redact=["password"])

        root = logging.getLogger()
        assert len(root.handlers) == 1
        root.handlers[0].stream = buf
        root.setLevel(logging.DEBUG)

        @log_method_call
        def register(self_, username, password):  # noqa: ARG001
            return "ok"

        register(object(), username="alice", password="s3cret")

        output = buf.getvalue()
        assert "s3cret" not in output
        assert "[REDACTED]" in output


# ---------------------------------------------------------------------------
# Contract tests — lock invariants that have been broken in past PRs.
# These guard against regressions of two specific failure modes:
#   (1) The redaction stage being inserted ahead of caller-supplied stages,
#       letting later processors smuggle sensitive fields past the masker.
#   (2) The configured ``redact`` list silently dropping the framework
#       defaults (so an operator adding one custom key turns OFF masking
#       of ``password``/``token``/etc.).
# ---------------------------------------------------------------------------


class TestRedactionContractInvariants:
    """Locked invariants for the redaction subsystem — do not relax."""

    def test_default_redact_keys_always_present(self):
        """``_build_key_set`` must be a superset of :data:`DEFAULT_REDACT_KEYS`.

        Operators cannot disable framework-default protection by supplying
        their own ``[logging].redact`` list. Any change that turns this
        from a union into a replacement is a security regression.
        """
        from protean.integrations.logging import _build_key_set

        defaults = {k.lower() for k in DEFAULT_REDACT_KEYS}

        # No input → defaults only.
        assert defaults <= _build_key_set(None)
        # Empty input → still defaults only.
        assert defaults <= _build_key_set([])
        # Custom input → defaults are still present.
        assert defaults <= _build_key_set(["x_custom"])
        # The custom key is also there.
        assert "x_custom" in _build_key_set(["x_custom"])
        # Multiple custom keys, mixed-case input still matched.
        assert defaults <= _build_key_set(["UPPER_KEY", "x"])
        assert "upper_key" in _build_key_set(["UPPER_KEY", "x"])

    def test_redaction_runs_after_caller_processors(self):
        """Sensitive fields injected by a later processor are still masked.

        This is the canonical pipeline-ordering contract: the redaction
        processor MUST be appended (not prepended) so anything a
        caller-supplied processor adds to the event dict gets scrubbed
        before the renderer sees it. A regression here would let a custom
        processor smuggle ``password=...`` past the masker.
        """

        # A "caller-supplied" processor that injects a sensitive field
        # AFTER the user's call site — modelling correlation/OTel/business
        # processors that enrich events in the chain.
        def smuggler_processor(logger, method, event_dict):
            event_dict["password"] = "leaked_via_late_processor"
            return event_dict

        buf = StringIO()
        with patch.dict("os.environ", {}, clear=True):
            from protean.utils.logging import configure_logging as _cfg

            _cfg(
                level="DEBUG",
                format="json",
                redact=["password"],
                extra_processors=[smuggler_processor],
            )

        root = logging.getLogger()
        assert len(root.handlers) == 1
        root.handlers[0].stream = buf
        root.setLevel(logging.DEBUG)

        sl = get_logger("protean.test.redaction.contract")
        sl.info("event_without_password")  # caller didn't pass `password`

        output = buf.getvalue()
        assert "leaked_via_late_processor" not in output, (
            "Redaction processor must run AFTER caller-supplied processors — "
            "if it runs first, fields injected later bypass masking."
        )
        assert "[REDACTED]" in output
