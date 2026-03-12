# Production Deployment

This guide covers deploying the Protean server in production — process
management, containerization, scaling strategies, and health checks.

For basic server usage, see [Run the Server](./index.md).

## Process Management

Use a process manager like systemd, supervisord, or Docker:

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

[Install]
WantedBy=multi-user.target
```

## Docker

```dockerfile
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY . .
RUN uv sync

ENV PROTEAN_ENV=production
CMD ["uv", "run", "protean", "server", "--domain=my_domain"]
```

## Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: protean-server
spec:
  replicas: 3  # Multiple workers for scaling
  selector:
    matchLabels:
      app: protean-server
  template:
    metadata:
      labels:
        app: protean-server
    spec:
      containers:
      - name: server
        image: my-app:latest
        command: ["protean", "server", "--domain=my_domain"]
        env:
        - name: PROTEAN_ENV
          value: "production"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
```

## Scaling Considerations

**StreamSubscription** supports horizontal scaling:

- Multiple server instances can run concurrently
- Messages are distributed across consumers via Redis consumer groups
- Each message is processed by exactly one consumer

**EventStoreSubscription** has limited scaling:

- Multiple instances will process the same messages
- Use for projections where idempotency is guaranteed
- Consider using StreamSubscription for scalable workloads

## Health Checks

Add health checks for production deployments:

```python
# health_check.py
import sys
from my_domain import domain

def check_health():
    try:
        # Verify domain can activate
        with domain.domain_context():
            # Check broker connectivity
            broker = domain.brokers.get("default")
            if broker:
                broker.ping()  # If supported

            # Check event store connectivity
            if domain.event_store:
                domain.event_store.store.ping()  # If supported

        return 0
    except Exception as e:
        print(f"Health check failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(check_health())
```
