# ADR-0012: Health Check Architecture

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-23 |
| **Author** | Subhash Bhushan |

## Context

Before the 5.1 hardening work, Protean had no built-in health probes.
Operators deploying to Kubernetes wrote their own liveness and
readiness checks — typically a Python script that imported the domain
and called `broker.ping()` — and exposed it through a sidecar or a
manual HTTP server. The pattern in `docs/guides/server/production-deployment.md`
showed this exact workaround. Three problems made this approach
untenable at scale:

1. **No uniform probe contract.** Each team invented its own probe
   semantics. Some checked only broker connectivity; some checked every
   adapter; some returned `200` even when the domain was mid-shutdown.
   There was no standard for what "ready" meant.
2. **FastAPI vs engine duplication.** Teams running both an API tier
   (FastAPI) and the async engine (`protean server`) wrote two
   separate probes. The async engine had no HTTP surface at all.
3. **Shutdown invisibility.** A pod mid-drain looked identical to a
   healthy pod from outside. Load balancers and service meshes had no
   way to know a pod was winding down until TCP connections started
   failing.

The question was: should Protean ship a standard health-probe
contract, and if so, how should it be delivered?

## Decision

We will ship a standard health-probe contract with two implementations
that share their readiness logic, and we will embed a probe server in
the async engine by default.

**Probe endpoints (uniform across implementations):**

- `GET /healthz` — liveness. Proves the process is alive and able to
  respond. Returns `200` with
  `{"status": "ok", "checks": {"event_loop": "responsive"}}` on the
  async engine; `{"application": "running"}` on the FastAPI router.
- `GET /livez` — alias for `/healthz`.
- `GET /readyz` — readiness. Inspects every provider, broker, event
  store, and cache; on the async engine it also reports a
  `subscriptions` block (see "Per-subscription readiness" below).
  Returns `200` when every check passes, `503`
  when any check fails (status `degraded`), and `503` with
  `{"shutting_down": true}` when shutdown is in progress
  (status `unavailable`).

**Two implementations, one readiness logic:**

- **Async engine:** `HealthServer` in `src/protean/server/health.py`,
  built directly on `asyncio.start_server` with minimal HTTP/1.1
  parsing. Enabled by default, listening on `127.0.0.1:8080` (loopback;
  set `[server.health] host = "0.0.0.0"` to expose off-host), disabled
  via `[server.health] enabled = false`.
- **FastAPI applications:** `create_health_router(domain)` in
  `src/protean/integrations/fastapi/health.py` returns an `APIRouter`
  that mounts the same three paths on an existing FastAPI app. Pods
  that already serve HTTP traffic do not need a separate probe server.

Both implementations share readiness logic through `protean.utils.health`,
which exposes `check_providers`, `check_brokers`, `check_event_store`,
and `check_caches`. The async-engine probe adds the `subscriptions`
block on top; the FastAPI router does not. Not because it couldn't —
`collect_subscription_statuses()` walks the registry and works fine
without a running engine — but because an API pod's readiness should
not depend on how far behind a worker's consumers are. Those are
separate deployments with separate failure modes, and a web pod that
can serve requests is ready even when a worker is backed up. Only
`circuit_state` and `total` are genuinely engine-only.

**Transport choice: asyncio over aiohttp/ASGI.**

The engine's probe server uses `asyncio.start_server` directly, not
`aiohttp` or an ASGI framework. Health probes are the simplest
possible HTTP workload — a few fixed routes returning small JSON
payloads — and bringing in an HTTP framework for a probe server
inflates the dependency graph of a package that is deliberately
minimal.

**Readiness during shutdown:**

`/readyz` returns `503` the moment `Engine.shutdown()` sets
`shutting_down = True`, well before subscriptions stop or handlers
drain. This is the "graceful drain" signal to load balancers — pull
the pod out of rotation first, then let in-flight work complete on the
old pod.

**Liveness during shutdown:**

`/healthz` keeps returning `200` while the engine drains. The
asymmetry is deliberate: liveness failure triggers a container
restart, which would kill the drain mid-flight. Only the event loop
itself being unresponsive should fail liveness.

## Consequences

**Positive:**

- Every Protean deployment gets Kubernetes-compatible probes without
  user code. The `docs/guides/server/production-deployment.md`
  workaround goes away.
- The async engine is visible to service meshes and load balancers
  for the first time. Rolling deploys drain cleanly.
- Liveness and readiness have correct asymmetric behaviour during
  shutdown (readiness fails first, liveness holds until the event
  loop is compromised).
- FastAPI users get probes with one `app.include_router` call. The
  shared readiness logic means API probes and engine probes report
  consistent health.
- No new dependencies. The implementation uses only `asyncio` (stdlib)
  and, for FastAPI, the user's existing FastAPI install.

**Negative:**

- Port `8080` is opened by default. Operators running other services
  on `8080` (local Jenkins, another app's admin port) must either
  move Protean via `[server.health] port = ...` or disable the
  server. This is the most common "gotcha" adopters will hit.
- The engine probe's HTTP implementation is hand-rolled. It is
  deliberately minimal (no keep-alive, no chunked transfer, no
  compression) but it is our responsibility to maintain. A future
  need for HTTPS or HTTP/2 on the probe port would force a rewrite.
- Readiness checks call `provider.is_alive()`, `broker.ping()`,
  `cache.ping()`, and the event store's equivalent on every
  `GET /readyz`. Probes every 5 seconds add ping load to every
  adapter. For high-throughput systems this is negligible; for
  rate-limited upstreams (e.g., managed Redis with per-second caps)
  it is worth sizing.
- The `subscriptions` block queries infrastructure once per
  subscription (Redis `XLEN`/`XINFO`, event-store reads, outbox
  counts). That is far heavier than the adapter pings above, and
  unlike them it can hang, so **it is not collected on the probe
  path at all**: a background task refreshes it every two seconds
  and the probe reads the result out of memory. Answering `/readyz`
  therefore stays as cheap as it was when the field was a bare
  integer. A deployment with very many subscriptions pays the
  collection cost once per interval regardless of probe frequency.
  This is deliberately the opposite trade from the adapter pings,
  which still run inline: those decide the verdict, so they must be
  current; the subscription block only informs, so it may be stale.
- Reporting lag without acting on it is deliberate (see
  "Per-subscription readiness" below), so `/readyz` alone will not
  page anyone about a stuck subscription. Alerting still belongs on
  the metrics.
- The block inherits the coverage gaps of
  `collect_subscription_statuses()`, which predate it and are shared
  with the `protean subscriptions status` CLI and the OTEL gauges.
  Three are known: outbox processors for `outbox.external_brokers`
  get no row; providers with `managed = false` get a row for a
  processor the engine never started; and a subscription on a
  partitioned (`sequential_by`) category reports
  `lag: null, status: "unknown"`, because the collector reads the base
  stream while the consumers read `{category}:{key}` partitions. That
  last one matters most: a halted partition is the framework's own
  definition of a stuck subscription and it produces no signal here.
  Fixing them belongs in the collector, not in the probe, so `total`
  and `len(details)` can legitimately disagree until then.

## Alternatives Considered

**Unix domain socket instead of TCP.** Rejected. Kubernetes probes
use HTTP over TCP; a Unix socket would force an `exec` probe, which
is heavier and less portable across orchestrators (Nomad, ECS, etc.).

**aiohttp or Starlette.** Rejected. Both would have satisfied the
probe requirements, but each carries a non-trivial dependency tree.
Protean's server surface is deliberately minimal to keep the base
install small. The probe server's footprint in `src/protean/server/health.py`
is under 250 lines.

**TCP-only probe (no HTTP).** Rejected. TCP `SYN-ACK` is not a strong
signal of readiness — the engine's event loop could be unresponsive
while the socket layer still accepts connections. HTTP with a
response body is the standard Kubernetes probe contract and signals
something meaningful.

**Mounting probes on an existing API app.** Considered. `create_health_router`
does exactly this for FastAPI users. For the async engine, which has
no HTTP surface otherwise, a standalone probe server was the simpler
choice than mandating FastAPI as a runtime dependency.

**One combined probe with query-parameter liveness vs readiness.**
Rejected. Kubernetes expects distinct paths with distinct behaviours
(`livenessProbe` restarts the container; `readinessProbe` pulls it
from rotation). Conflating them in one endpoint obscures the
semantic difference and invites misconfiguration.

**Per-subscription readiness.** Originally deferred in favour of a bare
count; **adopted in 0.17 (#832)** as a reported-but-not-enforced block.
`/readyz` now carries per-subscription lag, pending count, DLQ depth,
status, and circuit-breaker state, sourced from the same
`collect_subscription_statuses()` that feeds the
`protean.subscription.consumer_lag` and
`protean.subscription.pending_messages` gauges and the
`protean subscriptions status` CLI. No new metric names were introduced.

The block is **informational: it never changes the probe's verdict.**
Letting lag flip readiness to `503` was considered and rejected. A
backlog is a normal, self-correcting condition — a burst of traffic, a
replay, a slow downstream — and it is precisely when a consumer is
behind that you least want Kubernetes to pull it out of rotation and
stop it draining. An open circuit breaker is treated the same way: one
handler is paused, the engine is still healthy. Readiness answers "can
this pod process messages?", which stays true under lag. Alerting on
lag remains the metrics' job; the block exists so an operator debugging
a pod can see *which* subscription is behind without leaving the probe.

## References

- `docs/guides/server/hardening.md` — operational guidance for probe
  wiring and Kubernetes `terminationGracePeriodSeconds`.
- `docs/reference/server/hardening.md` — probe response bodies, status
  codes, and configuration reference.
- ADR-0011 — Engine shutdown and resource lifecycle contract (the
  shutdown sequence that `/readyz` signals during).
