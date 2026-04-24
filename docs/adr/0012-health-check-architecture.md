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
  store, and cache; on the async engine it also reports the
  subscription count. Returns `200` when every check passes, `503`
  when any check fails (status `degraded`), and `503` with
  `{"shutting_down": true}` when shutdown is in progress
  (status `unavailable`).

**Two implementations, one readiness logic:**

- **Async engine:** `HealthServer` in `src/protean/server/health.py`,
  built directly on `asyncio.start_server` with minimal HTTP/1.1
  parsing. Enabled by default, listening on `0.0.0.0:8080`, disabled
  via `[server.health] enabled = false`.
- **FastAPI applications:** `create_health_router(domain)` in
  `src/protean/integrations/fastapi/health.py` returns an `APIRouter`
  that mounts the same three paths on an existing FastAPI app. Pods
  that already serve HTTP traffic do not need a separate probe server.

Both implementations share readiness logic through `protean.utils.health`,
which exposes `check_providers`, `check_brokers`, `check_event_store`,
and `check_caches`. The async-engine probe adds a subscription count
check on top.

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
- Subscription count is reported as a single integer. We do not
  currently expose per-subscription readiness, so a single
  misbehaving subscription does not show up in `/readyz`. Operators
  who need per-subscription visibility must reach for OTEL metrics
  or the Observatory dashboard.

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

**Per-subscription readiness.** Deferred. Reporting subscription
count rather than per-subscription state keeps the probe response
small and fast. A richer readiness API — "which subscription is
stuck?" — is the Observatory's job and is already addressed by
OTEL metrics (`protean.engine.active_subscriptions`,
`protean.subscription.consumer_lag`).

## References

- `docs/guides/server/hardening.md` — operational guidance for probe
  wiring and Kubernetes `terminationGracePeriodSeconds`.
- `docs/reference/server/hardening.md` — probe response bodies, status
  codes, and configuration reference.
- ADR-0011 — Engine shutdown and resource lifecycle contract (the
  shutdown sequence that `/readyz` signals during).
