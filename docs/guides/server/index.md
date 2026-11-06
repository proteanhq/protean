# Run the Server

Protean's async processing server is the background process that runs event
handlers, command handlers, and projectors. You can start the server from the
CLI or from your own Python code.

For the conceptual architecture behind the server, see
[Async Processing](../../concepts/async-processing/index.md).

## Use the `protean server` command

Start the server using the `protean server` command:

```bash
protean server [OPTIONS]
```

### Choose the command options

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Path to domain module | `.` (current directory) |
| `--test-mode` | Run in test mode | `False` |
| `--workers` | Number of worker processes | `1` |
| `--reload` | Auto-reload on Python source changes (development only) | `False` |
| `--help` | Show help message | |

## Set up the database first

Before starting the server, ensure your database tables are created:

```bash
# Create all tables (aggregates, entities, projections, outbox)
protean db setup --domain=my_domain

# Create only outbox tables (useful when migrating to stream subscriptions)
protean db setup-outbox --domain=my_domain

# Drop all tables (requires confirmation)
protean db drop --domain=my_domain
protean db drop --domain=my_domain --yes  # Skip confirmation

# Delete all data, preserving schema (requires confirmation)
protean db truncate --domain=my_domain
protean db truncate --domain=my_domain --yes  # Skip confirmation
```

See [Database Commands](../../reference/cli/data/database.md) for the full reference.

## Run the server in common setups

### Starting the Server

```bash
# Start with domain in current directory
protean server

# Start with specific domain path
protean server --domain=src/my_domain

# Start with module path
protean server --domain=my_package.my_domain

# Start with specific instance
protean server --domain=my_domain:custom_domain
```

### Run multiple workers

Run multiple Engine processes from a single command using `--workers`:

```bash
# Start 4 worker processes
protean server --domain=my_domain --workers 4
```

Multi-worker mode requires stream subscriptions so that Redis consumer groups
can distribute messages across workers. Set this in your `domain.toml`:

```toml
[server]
default_subscription_type = "stream"
```

See [Configuration Reference](../../reference/configuration/index.md#server) for
the full list of server options.

Workers coordinate through Redis consumer groups (for stream message
distribution) and database-level locking (for outbox processing). No IPC or
shared memory is needed between workers.

For the full multi-worker guide including architecture, coordination details,
and deployment patterns, see [Multi-Worker Mode](../../reference/server/supervisor.md).

### How does the server find your domain?

The server discovers your domain in this order:

1. The `PROTEAN_DOMAIN` environment variable, if set
2. **--domain parameter**: Path or module specified
3. The current directory, where the server looks for `domain.py` or
   `subdomain.py`

Within a module, the server looks for:

1. Variable named `domain` or `subdomain`
2. Any variable that is a `Domain` instance
3. Raises error if multiple instances found

### Turn on debug logging

Enable verbose logging for troubleshooting with the global `--log-level DEBUG`
flag:

```bash
protean --log-level DEBUG server --domain=my_domain
```

Debug logging includes:

- Subscription registration details
- Message processing events
- Position updates
- Configuration resolution

### Reload on code changes during development

Pass `--reload` to watch the working directory and restart the Engine
on every Python source change:

```bash
pip install "protean[dev]"
protean server --domain=my_domain --reload
```

An outer process watches the working directory with
[`watchfiles`](https://watchfiles.helpmanual.io/) and replaces the inner Engine
worker when sources change. It uses `watchfiles.PythonFilter` to skip `.pyc`,
`__pycache__`, `.venv`, and `node_modules`, and it also excludes the
`.protean/` cache directory. `--reload` requires the `dev` extra (`pip install
"protean[dev]"`). You cannot combine `--reload` with `--workers > 1`.

!!! warning "Never enable `--reload` in production"
    Hot reload spawns a second Python process. It restarts the Engine on every
    file change, with no condition. It is a development ergonomics feature, not
    a deployment strategy.

### Run in test mode

Test mode processes available messages and exits, useful for integration tests:

```bash
protean server --domain=my_domain --test-mode
```

In test mode, the server:

1. Starts all subscriptions and processors
2. Processes messages, including the messages that handlers raise while
   processing
3. Shuts down as soon as no subscription finds more work. If a subscription
   keeps finding work, or a partitioned stream subscription is present, the
   server shuts down after about a second. A partitioned stream subscription
   cannot report that it is idle, so with one present the server always waits
   the full second. The server does not wait for a broker to redeliver a nacked
   message.

For examples of using test mode in your test suite, see
[Integration Tests](../testing/integration-tests.md).

## Start the engine from Python code

You can also start the engine programmatically. Here `domain` is your
`Domain` object:

```python
--8<-- "guides/server/index/001.py:engine"
```

### Pass custom options

```python
--8<-- "guides/server/index/001.py:options"
```

## How does the server respond to shutdown signals?

The server handles shutdown signals gracefully:

| Signal | Behavior |
|--------|----------|
| `SIGINT` (Ctrl+C) | Graceful shutdown |
| `SIGTERM` | Graceful shutdown |
| `SIGHUP` | Graceful shutdown |

During graceful shutdown:

1. Stop accepting new messages
2. Complete processing of current batch
3. Persist subscription positions
4. Clean up resources
5. Exit with appropriate code

## What do the exit codes mean?

| Code | Meaning |
|------|---------|
| 0 | Normal shutdown (signal or test mode completion) |
| 1 | Error during processing |

## Where to go next

- [Error Handling](./error-handling.md): Retry logic, dead letter queues, and recovery mechanisms
- [Dead Letter Queues](./dead-letter-queues.md): Discover, inspect, replay, and purge failed messages
- [Using the Outbox](./outbox.md): Reliably publish domain events via the outbox pattern
- [Production Deployment](./production-deployment.md): Process management, Docker, Kubernetes, scaling, and health checks
- [Harden the Server](./hardening.md): Raise pool limits, enable K8s health probes, run DLQ maintenance, pick subscription profiles, and emit OTEL metrics
- [Tuning Subscriptions](./tuning-subscriptions.md): Pick a profile, cap stream growth, use the circuit breaker, order events per entity, and check consumer lag
- [Logging](./logging.md): Configure structured logging, enrich wide events with business context, disable auto-configuration
- [Monitoring](./monitoring.md): Observatory dashboard, Prometheus metrics, and subscription lag tracking
- [Multi-Worker Mode](../../reference/server/supervisor.md): Run multiple Engine processes for higher throughput
- [Engine Architecture](../../concepts/async-processing/engine.md): Understand engine internals
- [Configuration](../../reference/server/configuration.md): Full configuration reference
- [Subscription Types](../../reference/server/subscription-types.md): Choose the right subscription
- [Using Priority Lanes](using-priority-lanes.md): Route background workloads through the backfill lane
- [External Event Dispatch](external-event-dispatch.md): Deliver published events to external brokers
