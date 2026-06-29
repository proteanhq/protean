"""Tests for the Observatory's secure-by-default network binding.

The Observatory is unauthenticated and exposes domain internals and DLQ
management endpoints, so it binds loopback by default and warns when bound to a
non-loopback address.
"""

import inspect
import logging
from unittest.mock import patch

from protean.server.observatory import Observatory


def _run(domains, host):
    """Invoke ``Observatory.run`` without actually starting the server."""
    obs = Observatory(domains=domains)
    with patch("protean.server.observatory.uvicorn.run"):
        obs.run(host=host)


class TestObservatoryBinding:
    def test_run_defaults_to_loopback(self):
        assert inspect.signature(Observatory.run).parameters["host"].default == (
            "127.0.0.1"
        )

    def test_cli_default_host_is_loopback(self):
        from protean.cli.observatory import observatory

        assert inspect.signature(observatory).parameters["host"].default == "127.0.0.1"

    def test_non_loopback_bind_warns(self, test_domain, caplog):
        with caplog.at_level(logging.WARNING, logger="protean.server.observatory"):
            _run([test_domain], host="0.0.0.0")

        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "0.0.0.0" in messages
        assert "no authentication" in messages

    def test_loopback_bind_does_not_warn(self, test_domain, caplog):
        with caplog.at_level(logging.WARNING, logger="protean.server.observatory"):
            _run([test_domain], host="127.0.0.1")

        assert not any("no authentication" in r.getMessage() for r in caplog.records)
