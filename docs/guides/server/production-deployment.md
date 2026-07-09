# Production Deployment

This guide covers deploying the Protean server in production — process
management, containerization, scaling strategies, and health checks.

For basic server usage, see [Run the Server](./index.md). For the full
production checklist — pool sizing, DLQ maintenance, subscription
profiles, OTEL metrics, and graceful shutdown — see
[Harden the Server](./hardening.md).

## Process Management

Use a process manager like systemd, supervisord, or Docker. Send
`SIGTERM` to trigger graceful shutdown and give the process at least
15 seconds to drain in-flight handlers:

```ini
# /etc/systemd/system/protean-server.service
[Unit]
Description=Protean Message Server
After=network.target

[Service]
Type=simple
User=app
WorkingDirectory=/app
Environment=PROTEAN_ENV=production
ExecStart=/app/.venv/bin/protean server --domain=my_domain
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

`TimeoutStopSec=30` gives the engine up to 30 seconds to stop
subscriptions, drain in-flight handlers (bounded at 10s), and close
providers, brokers, caches, and the event store before systemd escalates
to `SIGKILL`. See [Shut down gracefully](./hardening.md#shut-down-gracefully).

## Docker

Expose port `8080` so the orchestrator can reach the built-in health
server:

```dockerfile
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY . .
RUN uv sync

ENV PROTEAN_ENV=production
EXPOSE 8080
CMD ["uv", "run", "protean", "server", "--domain=my_domain"]
```

Docker sends `SIGTERM` by default and waits for
`--stop-timeout` (default 10s). Raise it for heavier workloads:

```bash
docker run --stop-timeout 30 my-app:latest
```

## Kubernetes

The engine embeds a health server on port `8080` by default. Wire
`livenessProbe` and `readinessProbe` to `/livez` and `/readyz`, and
set `terminationGracePeriodSeconds` long enough for the shutdown
sequence to complete:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: protean-server
spec:
  replicas: 3
  selector:
    matchLabels:
      app: protean-server
  template:
    metadata:
      labels:
        app: protean-server
    spec:
      terminationGracePeriodSeconds: 30
      containers:
      - name: server
        image: my-app:latest
        command: ["protean", "server", "--domain=my_domain"]
        env:
        - name: PROTEAN_ENV
          value: "production"
        ports:
        - name: health
          containerPort: 8080
        livenessProbe:
          httpGet: { path: /livez, port: health }
          periodSeconds: 10
          failureThreshold: 3
        readinessProbe:
          httpGet: { path: /readyz, port: health }
          periodSeconds: 5
          failureThreshold: 2
        lifecycle:
          preStop:
            exec:
              command: ["sleep", "5"]
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
```

The `preStop` hook gives the service mesh or load balancer a moment to
drain connections before the engine starts shutting down. For the full
probe reference — response bodies, status codes, and how to move the
port — see
[Server Hardening reference](../../reference/server/hardening.md#health-checks).

!!! warning "`replicas: 3` is only safe for stream/broker-backed domains"

    The `replicas: 3` above runs three independent server processes against the
    same event store. That is safe for stream subscriptions and cluster-aware
    brokers, but a domain with any **event-store** subscription would
    double-process every event across the replicas, and the per-process
    `--workers` guard cannot catch it. Set `replicas: 1` for such domains. See
    [Scaling Considerations](#scaling-considerations) below.

### FastAPI apps

API pods serving HTTP traffic should mount the equivalent router on
their FastAPI app:

```python
from fastapi import FastAPI
from protean.integrations.fastapi.health import create_health_router

app = FastAPI()
app.include_router(create_health_router(domain))
```

Point the probes at the same ports your API already exposes — no
separate health server is needed.

## Scaling Considerations

**StreamSubscription** supports horizontal scaling:

- Multiple server instances can run concurrently
- Messages are distributed across consumers via Redis consumer groups
- Each message is processed by exactly one consumer

**EventStoreSubscription** is single-writer:

- It reads directly from the event store with no cluster-wide ownership, so
  every worker reading a stream processes the same events.
- Because of this, `protean server --workers N` refuses to start with more than
  one worker when any handler resolves to an event-store subscription. The
  error names the offending handlers and offers three ways forward: run a
  single worker, switch those handlers to stream subscriptions
  (`subscription_type = "stream"`), or pass `--allow-event-store-multiworker` to
  override (you accept that events will be double-processed).
- Use it for a single worker, or for projections where idempotency is
  guaranteed; consider StreamSubscription for scalable workloads.

!!! warning "The single-writer guard is per-process, not cluster-wide"

    The `--workers` guard only sees the workers inside one `protean server`
    process. It **cannot** detect a second `protean server` running elsewhere.
    Running two processes, two containers, or two Kubernetes replicas against
    the same event store, each with the default `--workers 1`, sails past the
    guard and double-processes every event-store subscription just as surely as
    `--workers 2` would.

    Until cluster-wide ownership lands (a database-backed lease, planned for a
    future release), a domain with any event-store subscription must run as
    **exactly one process for the whole cluster**: `replicas: 1`, a single
    worker, no horizontal scaling. To scale horizontally, move those handlers to
    stream subscriptions (`subscription_type = "stream"`), which coordinate
    across processes via Redis consumer groups. The Kubernetes example above
    (`replicas: 3`) is safe only for stream/broker-backed domains; set
    `replicas: 1` for any domain that keeps event-store subscriptions.

For connection pool sizing across workers, DLQ retention, and OTEL
metric emission, follow the full production checklist in
[Harden the Server](./hardening.md).
