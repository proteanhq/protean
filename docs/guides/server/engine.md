# Engine Architecture

The `Engine` class is the core of Protean's async message processing system. It
manages subscriptions, coordinates message handling, and provides graceful
lifecycle management.

## Responsibilities

The Engine is responsible for:

1. **Registering handler subscriptions** - Creating subscriptions for event
   handlers, command handlers, and projectors
2. **Managing broker subscriptions** - Handling external message consumers
3. **Running outbox processors** - Publishing messages from the transactional
   outbox
4. **Coordinating lifecycle** - Starting, running, and gracefully shutting down
   all components
5. **Emitting trace events** - Publishing structured `MessageTrace` events at
   each stage of message processing for real-time observability

## Engine Initialization

When you create an Engine instance, it automatically discovers and registers all
handlers from your domain:

```python
from protean.server import Engine

# Create an engine for your domain
engine = Engine(domain)

# Or with options
engine = Engine(
    domain,
    test_mode=False,  # Set True for deterministic testing
    debug=False,      # Set True for verbose logging
)
```

## Subscription Registration

The Engine associates subscriptions with each handler during initialization. The factory determines the subscription type based on the [configuration hierarchy](#configuration-hierarchy).

### Handler Subscriptions

For each event handler and projector, the Engine creates one subscription per
handler, inferring the stream category and resolving configuration:

1. Infers the stream category from handler metadata or associated aggregate
2. Resolves subscription configuration using the priority hierarchy
3. Initializes the right [Subscription Type](subscription-types.md), either
a `StreamSubscription` or an `EventStoreSubscription`, for the handler.

```python
# Example: How the engine registers an event handler
handler_cls = OrderEventHandler
stream_category = engine._infer_stream_category(handler_cls)  # e.g., "orders"

subscription = engine.subscription_factory.create_subscription(
    handler=handler_cls,
    stream_category=stream_category,
)
```

### Command dispatch

When multiple command handlers belong to the same aggregate (and therefore the
same stream category), the Engine consolidates them into a single subscription
using a `CommandDispatcher`. Instead of creating N separate subscriptions that
would compete for the same messages, the dispatcher reads each command once and
routes it to the correct handler based on the command type:

```python
# Two command handlers for the same aggregate
@domain.command_handler(part_of=User)
class RegisterUserHandler:
    @handle(RegisterUser)
    def register(self, command): ...

@domain.command_handler(part_of=User)
class DeactivateUserHandler:
    @handle(DeactivateUser)
    def deactivate(self, command): ...

# The engine creates ONE subscription keyed as "commands:{stream_category}"
# that routes RegisterUser → RegisterUserHandler
# and DeactivateUser → DeactivateUserHandler
```

The `CommandDispatcher` caches the deserialized domain object between handler
resolution and execution to avoid double deserialization.

### Broker Subscriptions

For external message subscribers, the Engine creates `BrokerSubscription`
instances that connect to the configured message broker:

```python
@domain.subscriber(broker="default", stream="external_events")
class ExternalEventSubscriber:
    @handle("OrderCreated")
    def handle_order_created(self, event):
        ...
```

### Outbox Processors

When the outbox is enabled (via `default_subscription_type = "stream"`), the
Engine creates an `OutboxProcessor` for each database provider to publish
messages to the configured broker:

```toml
# Configuration in domain.toml
[server]
default_subscription_type = "stream"   # Enables outbox

[outbox]
broker = "default"
messages_per_tick = 10
tick_interval = 1
```

## Configuration Hierarchy

When registering subscriptions, the Engine consults a hierarchy of configuration sources to determine the appropriate subscription type and options for each handler. The resolution process typically follows this order of precedence:

1. **Handler-level configuration**: Explicit parameters set on the handler, such as stream name, broker, or processing options.
2. **Domain element metadata**: Values inferred from associated aggregate, event, or command definitions.
3. **Profile or role defaults**: Settings derived from the active configuration profile (e.g., "production", "projection") or handler role (such as projector vs. handler).
4. **Domain/global configuration**: Defaults specified in the domain configuration files (`domain.toml` or equivalent).

This means that explicit intent at the handler level takes priority, but system-wide defaults provide sensible behavior when specifics are not set.

For example, if a handler specifies a custom stream name, it will be used; otherwise, the engine will infer the relevant category from the handler’s associated aggregate or fall back to profile/domain defaults.

## Tracing

The Engine initializes a `TraceEmitter` at startup that publishes structured
`MessageTrace` events as messages flow through the pipeline. Trace events are
emitted at three points during `handle_message`:

- `handler.started` -- Before the handler processes the message
- `handler.completed` -- After successful processing (includes `duration_ms`)
- `handler.failed` -- When the handler raises an exception (includes `error`)

Additional trace events are emitted by `StreamSubscription` (`message.acked`,
`message.nacked`, `message.dlq`) and `OutboxProcessor` (`outbox.published`,
`outbox.failed`).

### Dual-channel output

The TraceEmitter writes to two Redis channels:

- **Pub/Sub** (`protean:trace`) -- Real-time fan-out for SSE clients. The
  emitter checks subscriber count and skips when nobody is listening.
- **Stream** (`protean:traces`) -- Time-bounded history for the Observatory
  dashboard and REST API. Old entries are automatically trimmed based on the
  configured retention period.

### Trace retention

The Engine reads `trace_retention_days` from the domain's `[observatory]`
configuration (default: 7 days). When set to `0`, Stream persistence is
disabled and only Pub/Sub broadcasting is available. If the configuration value
is missing or invalid, the Engine falls back to the 7-day default.

The emitter adds zero overhead when no monitoring tools are subscribed and
persistence is disabled -- see [Observability](observability.md) for the full
design, the Observatory monitoring server, and trace API endpoints.

## Running the Engine

For comprehensive information on how to start, configure, and operate the engine, including:

- CLI commands and options
- Test mode for deterministic testing
- Debug mode for troubleshooting
- Programmatic usage
- Production deployment strategies
- Signal handling and graceful shutdown
- Monitoring, health checks, and observability

See the [Running the Server](running.md) guide.

## Next Steps

- [Subscriptions](subscriptions.md): Learn how handlers connect to message sources and react to events.
- [Subscription Types](subscription-types.md): Compare StreamSubscription and EventStoreSubscription, and choose the right one for your workload.
- [Configuration](configuration.md): Dive deeper into configuring engine profiles, subscriptions, and runtime options.
- [Outbox Pattern](outbox.md): Understand reliable message publishing and transactional outbox processing.
- [Observability](observability.md): Real-time tracing, the Observatory server, SSE streaming, and Prometheus metrics.
- [Running the Server](running.md): Explore how to deploy, operate, and monitor the server in different environments.
