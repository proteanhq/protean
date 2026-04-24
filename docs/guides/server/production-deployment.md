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

**EventStoreSubscription** has limited scaling:

- Multiple instances will process the same messages
- Use for projections where idempotency is guaranteed
- Consider using StreamSubscription for scalable workloads

For connection pool sizing across workers, DLQ retention, and OTEL
metric emission, follow the full production checklist in
[Harden the Server](./hardening.md).
