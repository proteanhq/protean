"""Guard tests for suite descriptor hermeticity.

The autouse fixtures in ``tests/conftest.py`` track every event loop and every
Starlette/FastAPI ``TestClient`` created during a test and close them at
teardown, so file descriptors do not accumulate across the ~11k-test suite
(which otherwise exhausts the process limit: ``OSError: Too many open files``).

Teardown reclamation is only observable *after* a test finishes, so each guard
is a pair: the first test records a resource it created, and the second asserts
that the intervening autouse teardown closed it. The suite runs single-process
and in definition order (no ``pytest-xdist``), so the ordering is reliable. If
the trackers are removed, the second test of each pair fails — that is what
makes these guards non-vacuous.
"""

import asyncio
from typing import Any

import pytest

# Cross-test stash: the recording test drops a resource here; the checking test
# reads it back and asserts the autouse teardown closed it.
_stash: dict[str, Any] = {}


class TestEventLoopReclamation:
    def test_loop_created_in_a_test_is_open(self) -> None:
        # Created via the patched asyncio.new_event_loop, so it is tracked.
        loop = asyncio.new_event_loop()
        _stash["loop"] = loop
        assert not loop.is_closed()

    def test_prior_test_loop_was_closed_at_teardown(self) -> None:
        loop = _stash.get("loop")
        if loop is None:
            pytest.skip("recording test did not run in this session")
        assert loop.is_closed(), (
            "auto_set_and_close_loop should have closed the loop created in the "
            "previous test; a leaked loop keeps its self-pipe descriptors open"
        )


async def _minimal_asgi_app(scope: Any, receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


class TestTestClientReclamation:
    def test_client_created_in_a_test_is_open(self) -> None:
        testclient = pytest.importorskip("starlette.testclient")
        client = testclient.TestClient(_minimal_asgi_app)
        _stash["client"] = client
        assert client.is_closed is False

    def test_prior_test_client_was_closed_at_teardown(self) -> None:
        client = _stash.get("client")
        if client is None:
            pytest.skip("recording test did not run in this session")
        assert client.is_closed is True, (
            "_close_test_clients should have closed the TestClient created in "
            "the previous test; a leaked client keeps its httpx sockets open"
        )
