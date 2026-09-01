"""Lightweight health check HTTP server for the Protean Engine.

Provides Kubernetes-compatible liveness and readiness probes that run
alongside the Engine's event loop.  No external HTTP framework required —
built on ``asyncio.start_server`` with minimal HTTP/1.1 parsing.

Endpoints:
    GET /healthz  — Liveness: engine running, event loop responsive → 200
    GET /livez    — Alias for /healthz
    GET /readyz   — Readiness: providers alive, broker connected, event store
                    and caches reachable, not shutting down, not draining
                    → 200 / 503
    POST /drainz  — Advisory drain: flip the engine to ``draining`` so it stops
                    taking new work while in-flight handlers finish. The process
                    stays alive; readiness then reports not-ready so a load
                    balancer stops routing. → 200

Every endpoint here answers for the engine in *this* process, ``/drainz``
included: it drains the worker whose health server took the request, not its
peers.  Under ``protean server --workers N`` each worker runs its own health
server and the workers share no IPC, so quiescing the whole group means POSTing
to each worker's health port.  That needs ``port_auto_increment = true``: with
the default ``false`` only the first worker binds and the rest run without
probes.  One worker per pod (the usual Kubernetes shape) has no such gap.

The readiness response also carries a ``subscriptions`` block reporting per-
subscription lag, status, and circuit-breaker state.  Each row also carries a
``lag_drain_rate``: the change in ``lag_seconds`` per second, negative while the
backlog drains and positive while it grows.  It is ``null`` until two refreshes
have landed and for any row whose ``lag_seconds`` is unknown.  That block is
**informational and is not one of the gates above**: a lagging subscription or
an open breaker never flips the probe to 503, because a backlog is not a reason
for Kubernetes to pull the pod out of service — the engine is still healthy and
still draining the stream.  Building the block can never fail the probe either;
if collection breaks, the block says so and readiness answers normally.

Configuration (``domain.toml``):

.. code-block:: toml

    [server.health]
    enabled = true              # default
    host = "127.0.0.1"          # default (loopback); set "0.0.0.0" to expose
    port = 8080                 # default
    port_auto_increment = false # default; try 8081, 8082, ... if 8080 is taken
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from protean.server.subscription.profiles import CircuitBreakerState
from protean.server.subscription_status import (
    SubscriptionStatus,
    collect_subscription_statuses,
)
from protean.utils.health import (
    STATUS_DEGRADED,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    check_brokers,
    check_caches,
    check_event_store,
    check_providers,
)

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.server.engine import Engine

logger = logging.getLogger(__name__)

# When ``port_auto_increment`` is enabled, how many consecutive ports to try
# starting from the configured one before giving up (8080..8179 by default).
_MAX_PORT_ATTEMPTS = 100

# How often the background task recollects subscription statuses.  Collection
# queries infrastructure once per subscription (Redis XLEN/XINFO, event-store
# reads, outbox counts), so this is a load knob on those backends, not a probe
# latency knob — probes read whatever the last refresh produced.  Mirrors the
# 2s scrape cache the OTEL gauges use in ``server/observatory/metrics.py``.
_SUBSCRIPTION_REFRESH_SECONDS = 2.0

# How many missed refreshes before the block is called stale.  One skipped tick
# is normal jitter; several in a row means collection is wedged.
_STALE_AFTER_INTERVALS = 3

# How many recent (clock, lag_seconds) samples to retain per subscription when
# computing the lag-drain rate.  At the 2s refresh cadence this is about a 60s
# window.  It is a ``deque`` maxlen, so it bounds the per-subscription state:
# the window slides, it never grows with runtime.
_LAG_SAMPLE_WINDOW = 30

# SubscriptionStatus fields the readiness block drops: stream cursors and
# bookkeeping that answer "where is it?" rather than "is it healthy?".
_POSITION_FIELDS = (
    "current_position",
    "head_position",
    "consumer_count",
    "last_updated",
)


# ---------------------------------------------------------------------------
# Minimal HTTP response builders
# ---------------------------------------------------------------------------

_REASONS = {
    200: "OK",
    404: "Not Found",
    405: "Method Not Allowed",
    503: "Service Unavailable",
}


def _json_response(status_code: int, body: dict[str, Any]) -> bytes:
    """Build a minimal HTTP/1.1 response with JSON body."""
    payload = json.dumps(body).encode("utf-8")
    reason = _REASONS.get(status_code, "Unknown")
    header = (
        f"HTTP/1.1 {status_code} {reason}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    )
    return header.encode("utf-8") + payload


def _parse_request_line(data: bytes) -> tuple[str, str]:
    """Extract HTTP method and path from the first line of the request."""
    first_line = data.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
    parts = first_line.split(" ")
    if len(parts) >= 2:
        return parts[0].upper(), parts[1]
    return "", ""


# ---------------------------------------------------------------------------
# Health check logic
# ---------------------------------------------------------------------------


def _check_liveness(engine: Engine) -> dict[str, Any]:
    """Liveness probe: event loop is responsive (proven by this handler executing)."""
    return {
        "status": STATUS_OK,
        "checks": {
            "event_loop": "responsive",
        },
    }


class _SubscriptionBlockRefresher:
    """Keeps a current subscription block so the probe never touches I/O.

    Collection talks to Redis, the event store, and the outbox: it can be slow
    or hang outright.  None of that belongs on a readiness probe, where waiting
    means blowing past the orchestrator's probe timeout (Kubernetes defaults to
    one second) and losing the pod its place in the load balancer because a
    *dashboard field* was slow.

    So nothing collects on the probe path.  A background task refreshes the
    block on an interval and the probe reads the last result out of memory,
    which cannot block and cannot fail.  A hung backend just means the block
    stops being updated, and the probe says so by reporting its age rather than
    passing stale numbers off as current.
    """

    def __init__(
        self,
        engine: Engine,
        interval: float = _SUBSCRIPTION_REFRESH_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        self._engine = engine
        self._interval = interval
        # Injected so tests can drive the staleness boundary without patching
        # the process-wide clock the event loop itself runs on.
        self._clock = clock
        self._block: dict[str, Any] | None = None
        self._collected_at: float = 0.0
        self._task: asyncio.Task[None] | None = None
        # Per-subscription sliding window of (clock_time, lag_seconds) samples,
        # keyed by subscription name.  Each deque is bounded by
        # ``_LAG_SAMPLE_WINDOW`` and the key set is pruned to the names in the
        # current block, so neither axis of this state grows with runtime.
        self._samples: dict[str, deque[tuple[float, float]]] = {}

    @property
    def block(self) -> dict[str, Any]:
        """The most recent block.  Pure memory read: no I/O, never raises."""
        if self._block is None:
            return {
                "total": _subscription_total(self._engine),
                "collection_pending": True,
                "details": [],
            }

        age = max(0.0, self._clock() - self._collected_at)
        if age <= self._interval * _STALE_AFTER_INTERVALS:
            return self._block

        # Refreshes have stopped landing — a wedged backend, most likely.
        # "lag: 0, status: ok" is reassuring and worthless if it was collected
        # hours ago, so say how old it is.
        return {**self._block, "stale": True, "age_seconds": round(age, 3)}

    async def start(self) -> None:
        """Begin refreshing in the background."""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop refreshing and wait for the loop to unwind."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _refresh_once(self) -> None:
        """Collect once and adopt the result, keeping the old block on failure."""
        try:
            block = await _snapshot_and_collect(self._engine)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Keep serving the previous block and try again next tick.  A
            # monitoring read must never take the refresher down.
            logger.debug("Subscription block refresh failed", exc_info=True)
            return

        self._annotate_lag_drain_rates(block)
        self._block = block
        self._collected_at = self._clock()

    def _annotate_lag_drain_rates(self, block: dict[str, Any]) -> None:
        """Set ``lag_drain_rate`` on each detail row of *block*, in place.

        The rate is the change in ``lag_seconds`` per second, computed by
        least-squares over this subscription's retained samples.  Negative means
        the backlog is draining; positive means it is falling behind.  It is
        ``None`` until two windows have landed, and ``None`` for any row whose
        ``lag_seconds`` is unknown (an unreachable backend or an unmatched
        breaker) — a rate with no window is meaningless and must never read as 0.

        Only the refresher holds a window, so the rate is computed here rather
        than in the one-shot collector, and both readiness entry points that
        read the block get the field without a second wiring site.
        """
        details = block.get("details")
        if not isinstance(details, list):
            return

        now = self._clock()
        seen: set[str] = set()
        for detail in details:
            name = detail.get("name")
            lag_seconds = detail.get("lag_seconds")
            if not isinstance(name, str) or not isinstance(lag_seconds, (int, float)):
                # Unknown lag (or a malformed row): no sample, no rate.  A 0
                # sample here would later read as a real, drained rate.
                detail["lag_drain_rate"] = None
                continue

            seen.add(name)
            samples = self._samples.setdefault(name, deque(maxlen=_LAG_SAMPLE_WINDOW))
            samples.append((now, float(lag_seconds)))
            detail["lag_drain_rate"] = _lag_drain_rate(samples)

        # Prune windows for subscriptions no longer in the block, so the key set
        # cannot grow unbounded as subscriptions churn.
        for stale_name in self._samples.keys() - seen:
            del self._samples[stale_name]

    async def _run(self) -> None:
        while True:
            await self._refresh_once()
            await asyncio.sleep(self._interval)


def _lag_drain_rate(samples: deque[tuple[float, float]]) -> float | None:
    """Least-squares slope of ``lag_seconds`` over ``(time, lag_seconds)`` samples.

    Returns the change in lag-seconds per second: negative while draining,
    positive while falling behind.  Returns ``None`` with fewer than two samples
    (no line to fit) or when the samples share one instant (a fixed or
    non-advancing clock), which would otherwise divide by zero.
    """
    n = len(samples)
    if n < 2:
        return None

    mean_t = sum(t for t, _ in samples) / n
    mean_y = sum(y for _, y in samples) / n
    denominator = sum((t - mean_t) ** 2 for t, _ in samples)
    if denominator == 0:
        return None

    numerator = sum((t - mean_t) * (y - mean_y) for t, y in samples)
    return numerator / denominator


def _circuit_states(engine: Engine) -> dict[str, str]:
    """Map the engine's own subscription name → circuit-breaker state.

    Read straight off the live subscription objects, so this costs no I/O.
    Only stream subscriptions carry a breaker, so a subscription missing from
    this map has none rather than an unknown one.  The ``isinstance`` check is
    deliberate: anything else in ``circuit_state`` is ignored instead of being
    coerced, so a malformed subscription cannot take the readiness probe down.
    """
    states: dict[str, str] = {}
    for name, subscription in engine._subscriptions.items():
        state = getattr(subscription, "circuit_state", None)
        if isinstance(state, CircuitBreakerState):
            states[name] = state.value
    return states


def _collect_subscription_health(
    domain: Domain,
    total: int,
    breakers: dict[str, str],
) -> dict[str, Any]:
    """Build the readiness ``subscriptions`` block.

    Lag, pending counts, and status come from
    :func:`~protean.server.subscription_status.collect_subscription_statuses`
    — the same source behind the ``protean.subscription.consumer_lag`` and
    ``protean.subscription.pending_messages`` gauges and the
    ``protean subscriptions status`` CLI.  Circuit-breaker state is merged in
    from *breakers*, snapshotted off the engine's live subscription objects,
    which the status collector cannot see (it is designed to work without a
    running engine).

    ``total`` and ``details`` count different things and may legitimately
    disagree in length: ``total`` is the engine's own tally of live
    subscription objects, while ``details`` comes from walking the domain
    registry.  One partitioned process manager, for instance, is a single
    engine subscription but one detail row per stream category.

    Runs the blocking collection, so callers hand it to a worker thread.  It
    takes a plain domain and pre-read snapshots rather than the engine itself:
    engine state must be read on the event-loop thread, not raced with it
    from a worker.
    """
    try:
        statuses: list[SubscriptionStatus] = collect_subscription_statuses(domain)

        unmatched_breakers = dict(breakers)
        details: list[dict[str, Any]] = []
        for status in statuses:
            # Keys mirror SubscriptionStatus, so a subscription reads the same
            # here as it does from `protean subscriptions status` and the
            # Observatory API.  Only the cursor/bookkeeping fields are dropped:
            # a probe wants health, not stream positions.
            detail = status.to_dict()
            for field in _POSITION_FIELDS:
                detail.pop(field, None)

            breaker_state = unmatched_breakers.pop(status.name, None)
            if breaker_state is not None:
                detail["circuit_state"] = breaker_state
            details.append(detail)

        # Any breaker left over belongs to a live subscription the status
        # collector named differently — a ``sequential_by`` process manager is
        # keyed ``{name}-partitioned`` by the engine but reported per stream
        # category by the collector.  Report those rather than dropping them:
        # an operator hunting a tripped breaker must not find a hole where it
        # should be.  Every count is null rather than 0: nothing is known about
        # this key, and a 0 would read as "no backlog" instead of "no data".
        for name, breaker_state in unmatched_breakers.items():
            details.append(
                {
                    "name": name,
                    "handler_name": name,
                    "subscription_type": "unknown",
                    "stream_category": None,
                    "lag": None,
                    "lag_seconds": None,
                    "pending": None,
                    "dlq_depth": None,
                    "status": "unknown",
                    "circuit_state": breaker_state,
                }
            )
    except Exception:
        # Never let a monitoring read break the probe: readiness reflects
        # whether the engine can process messages, and it still can.  This
        # guards the whole build, not just the collection call — an exception
        # escaping here would reach the connection handler, which closes the
        # socket without writing a response, and an empty reply reads to
        # Kubernetes as a failed probe.
        logger.debug("Subscription status collection failed", exc_info=True)
        return {"total": total, "collection_error": True, "details": []}

    return {"total": total, "details": details}


def _subscription_total(engine: Engine) -> int:
    """Count the engine's live subscription objects.  No I/O."""
    try:
        return (
            len(engine._subscriptions)
            + len(engine._broker_subscriptions)
            + len(engine._outbox_processors)
        )
    except Exception:
        logger.debug("Counting engine subscriptions failed", exc_info=True)
        return 0


async def _snapshot_and_collect(engine: Engine) -> dict[str, Any]:
    """Read engine state on this thread, then do the blocking reads off it.

    Engine dicts are read here, on the event loop, rather than inside the
    worker: iterating them from another thread could race the loop mutating
    them.
    """
    total = _subscription_total(engine)
    try:
        breakers = _circuit_states(engine)
    except Exception:
        logger.debug("Reading circuit-breaker state failed", exc_info=True)
        return {"total": total, "collection_error": True, "details": []}

    return await asyncio.to_thread(
        _collect_subscription_health, engine.domain, total, breakers
    )


async def _check_readiness(
    engine: Engine,
    subscriptions: dict[str, Any],
) -> dict[str, Any]:
    """Readiness probe: is the engine ready to process messages?

    The verdict is decided by shutdown state, providers, brokers, event store,
    and caches.  Per-subscription lag, status, and circuit-breaker state are
    also *reported*, but do not affect it — see the module docstring for why
    lag must not take a pod out of service.

    Args:
        engine: The running engine to probe.
        subscriptions: The already-collected subscription block.  Passed in
            rather than gathered here, so probing never waits on I/O.
    """
    checks: dict[str, Any] = {}
    all_ok = True

    if engine.shutting_down:
        return {
            "status": STATUS_UNAVAILABLE,
            "checks": {"shutting_down": True},
        }
    checks["shutting_down"] = False

    # A draining engine is healthy but should stop receiving new requests, so
    # readiness reports not-ready and a load balancer pulls the pod out of
    # rotation. Kept distinct from the shutting_down payload so an operator can
    # tell a draining pod (finishing in-flight work) from one tearing down.
    if engine.draining:
        return {
            "status": STATUS_UNAVAILABLE,
            "checks": {"draining": True},
        }
    checks["draining"] = False

    domain = engine.domain

    provider_statuses, providers_ok = check_providers(domain)
    checks["providers"] = provider_statuses
    if not providers_ok:
        all_ok = False

    broker_statuses, brokers_ok = check_brokers(domain)
    checks["brokers"] = broker_statuses
    if not brokers_ok:
        all_ok = False

    es_status, es_ok = check_event_store(domain)
    checks["event_store"] = es_status
    if not es_ok:
        all_ok = False

    cache_statuses, caches_ok = check_caches(domain)
    checks["caches"] = cache_statuses
    if not caches_ok:
        all_ok = False

    # Reported last and never folded into `all_ok`: this block informs, it does
    # not gate.
    checks["subscriptions"] = subscriptions

    status = STATUS_OK if all_ok else STATUS_DEGRADED
    return {"status": status, "checks": checks}


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class HealthServer:
    """Async HTTP server for Engine health probes.

    Runs as a task on the Engine's event loop.  Start with :meth:`start`
    and stop with :meth:`stop`.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._server: asyncio.AbstractServer | None = None
        self._subscriptions = _SubscriptionBlockRefresher(engine)

        try:
            health_config = engine.domain.config.get("server", {}).get("health", {})
        except (AttributeError, TypeError):
            health_config = {}
        self.enabled: bool = health_config.get("enabled", True)
        self.host: str = health_config.get("host", "127.0.0.1")
        self.port: int = health_config.get("port", 8080)
        self.port_auto_increment: bool = health_config.get("port_auto_increment", False)

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single HTTP connection."""
        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            if not data:
                return

            method, path = _parse_request_line(data)

            if method == "POST" and path == "/drainz":
                # Advisory drain trigger: flip the engine to draining so it
                # stops taking new work while in-flight handlers finish. The
                # process stays alive; the orchestrator's later SIGTERM drives
                # the actual shutdown. Matched before the generic 405 branch so
                # every other non-GET request still gets 405.
                #
                # The flag lives on this process's Engine, so the drain covers
                # this worker only. Workers have no IPC (see
                # protean.server.supervisor), so under `--workers N` an
                # orchestrator must POST every worker's health port to quiesce
                # the whole group. The response carries the pid so the caller
                # can tell the workers apart.
                self.engine.draining = True
                pid = os.getpid()
                logger.info("engine.drain_requested", extra={"pid": pid})
                writer.write(_json_response(200, {"status": "draining", "pid": pid}))
            elif method != "GET":
                writer.write(_json_response(405, {"error": "Method Not Allowed"}))
            elif path in ("/healthz", "/livez"):
                result = _check_liveness(self.engine)
                writer.write(_json_response(200, result))
            elif path == "/readyz":
                result = await _check_readiness(self.engine, self._subscriptions.block)
                code = 200 if result["status"] == STATUS_OK else 503
                writer.write(_json_response(code, result))
            else:
                writer.write(_json_response(404, {"error": "Not Found"}))

            await writer.drain()
        except (TimeoutError, ConnectionResetError, BrokenPipeError):
            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            # Answer, rather than closing the socket on an unwritten response.
            # An empty reply is indistinguishable from a dead process to an
            # orchestrator, so a bug in probe assembly would take the pod out
            # of rotation. A 503 says "not ready", which is at least true and
            # is what the caller can act on.
            logger.warning("Health server connection error", exc_info=True)
            with contextlib.suppress(Exception):
                # `degraded`, not `unavailable`: the latter is reserved for
                # the shutdown case and carries `shutting_down: true`, so
                # reusing it here would read as "this pod is draining".
                writer.write(
                    _json_response(503, {"status": STATUS_DEGRADED, "checks": {}})
                )
                await writer.drain()
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self) -> None:
        """Start the health check HTTP server.

        Binds ``self.port`` directly unless ``port_auto_increment`` is enabled,
        in which case it walks up to :data:`_MAX_PORT_ATTEMPTS` consecutive
        ports until one is free, updating ``self.port`` to the bound port. This
        lets several engines share a host without colliding on 8080. If no port
        can be bound, the engine logs a warning and continues without probes.
        """
        if not self.enabled:
            logger.debug("Health check server disabled by configuration")
            return

        start_port = self.port
        max_attempts = _MAX_PORT_ATTEMPTS if self.port_auto_increment else 1
        last_error: Exception | None = None

        for candidate in range(start_port, start_port + max_attempts):
            try:
                self._server = await asyncio.start_server(
                    self._handle_connection,
                    host=self.host,
                    port=candidate,
                )
            # OSError: port taken / permission; ValueError/OverflowError: the
            # candidate walked past the valid 0-65535 range. Treat all as
            # "cannot bind here" and keep the engine running without probes.
            except (OSError, ValueError, OverflowError) as e:
                last_error = e
                continue

            # Reflect the port actually bound (candidate, or an OS-assigned one
            # when the configured port is 0).
            self.port = self._server.sockets[0].getsockname()[1]
            await self._subscriptions.start()
            logger.info(
                f"Health check server listening on http://{self.host}:{self.port}"
            )
            return

        # For a single attempt this renders as "8080"; for an auto-increment
        # scan, the full "8080-8179" span that was tried.
        attempted = (
            f"{start_port}-{start_port + max_attempts - 1}"
            if self.port_auto_increment
            else str(start_port)
        )
        logger.warning(
            f"Failed to start health check server on {self.host} (port {attempted}): "
            f"{last_error}. Engine will continue without health probes."
        )

    async def stop(self) -> None:
        """Stop the health check HTTP server and its background refresher.

        Cancels the refresh loop. A collection already handed to a worker
        thread runs to completion, since ``asyncio.to_thread`` work cannot be
        cancelled; its result is simply discarded.
        """
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("Health check server stopped")
        await self._subscriptions.stop()
