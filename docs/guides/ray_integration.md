# Using Ray for Distributed Event/Command Processing

Protean uses [Ray](https://docs.ray.io/) to process events and commands in a distributed manner. Ray is a high-performance, distributed computing framework that makes it easy to scale your Python workloads from a single machine to a large cluster.

## Overview

Ray integration in Protean allows you to:

1. Process events and commands concurrently using Ray actors
2. Distribute processing across multiple machines in a cluster
3. Leverage Ray's fault tolerance and performance optimization capabilities
4. Monitor processing using Ray's dashboard

The implementation is designed to be simple and robust, with excellent error handling to ensure that failures in individual handlers don't bring down the entire system.

## Installation

Ray is included as a dependency in Protean. For development, this default installation is sufficient. For production environments, you might want to install additional features:

```bash
pip install "ray[default,dashboard]"
```

## Running the Server

The simplest way to start the Protean server with Ray is using the CLI:

```bash
protean server --domain=your_domain
```

### Development Setup

For development, the default Ray configuration is optimized for ease of use:

```bash
protean server --domain=your_domain --debug
```

This will:
- Start a local Ray cluster on your machine
- Enable the Ray dashboard for monitoring and debugging
- Provide detailed logging of events and commands

### Production Setup

For production deployments, you can configure Ray more extensively:

```bash
protean server --domain=your_domain \
  --ray-num-cpus=8 \
  --ray-memory=16GB \
  --ray-object-store-memory=4GB
```

To connect to an existing Ray cluster:

```bash
protean server --domain=your_domain --ray-address="ray://192.168.1.100:10001"
```

### All Available Options

Here are all the available Ray configuration options:

| Option | Description | Default |
|--------|-------------|---------|
| `--ray-dashboard / --no-ray-dashboard` | Enable/disable Ray dashboard | `True` |
| `--ray-dashboard-port` | Ray dashboard port | `8265` |
| `--ray-num-cpus` | Number of CPUs for Ray workers | `None` (auto) |
| `--ray-num-gpus` | Number of GPUs for Ray workers | `None` (auto) |
| `--ray-memory` | Memory limit for Ray (e.g., '4GB') | `None` (auto) |
| `--ray-object-store-memory` | Object store memory limit (e.g., '1GB') | `None` (auto) |
| `--ray-address` | Ray cluster address to connect to | `None` (local) |

## How Ray Integration Works

The Ray integration is designed to be simple and transparent. All your existing event handlers and command handlers work without any changes.

### Architecture

Ray integration consists of three main actor types:

1. **Handler Actors**: Responsible for executing your command and event handlers
2. **Subscription Actors**: Poll the event store for new events/commands and forward them to Handler Actors
3. **Broker Subscription Actors**: Poll message brokers for new messages

```
┌─────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│                     │     │                      │     │                      │
│  Event Store/Broker │◄────┤  SubscriptionActor   │────►│    HandlerActor      │
│                     │     │                      │     │                      │
└─────────────────────┘     └──────────────────────┘     └──────────────────────┘
```

### Non-Async Design

All Ray actors use a simple, non-async design. This means:

1. Your handlers remain simple, synchronous functions
2. No `async`/`await` complexity
3. Easier debugging and reasoning about the code

### Error Handling

The Ray integration provides robust error handling:

1. **Isolated Failures**: Errors in one handler don't affect others
2. **Detailed Logging**: All errors are logged with full traceback
3. **Continued Processing**: After an error, the system continues processing new messages
4. **Custom Error Handling**: Your handlers can implement `handle_error()` for custom error processing

## Creating Event and Command Handlers

Your event and command handlers work exactly the same with Ray as they did before:

```python
from protean.core.event_handler import BaseEventHandler
from protean.utils.mixins import handle

class UserEventHandler(BaseEventHandler):
    @handle(UserRegistered)
    def user_registered(self, event):
        """Handle UserRegistered event."""
        logger.info(f"User registered: {event.name} ({event.email})")
        # Your business logic here
        
    @handle(UserActivated)
    def user_activated(self, event):
        """Handle UserActivated event."""
        logger.info(f"User activated: {event.id}")
        # Your business logic here
        
    def handle_error(self, exception, message):
        """Optional custom error handling"""
        logger.error(f"Error handling {message.type}: {str(exception)}")
        # Custom error handling logic
```

## Advanced Configuration

### Domain Configuration

You can configure Ray in your domain configuration:

```python
from protean.domain import Domain

# Create a domain
domain = Domain("example")

# Configure Ray
domain.config["ray"] = {
    "init_args": {
        "num_cpus": 4,
        "memory": "8GB",
        "object_store_memory": "2GB",
        "dashboard_port": 8265,
        "include_dashboard": True,
    }
}

# Initialize the domain
domain.init()
```

### Ray Clusters

For large-scale deployments, you can deploy a Ray cluster and connect to it:

1. Deploy a Ray cluster following the [Ray Cluster documentation](https://docs.ray.io/en/latest/cluster/getting-started.html)
2. Connect your Protean application to the cluster using `--ray-address`

```bash
protean server --domain=your_domain --ray-address="ray://head-node-ip:10001"
```

## Debugging and Monitoring

### Ray Dashboard

The Ray dashboard is a powerful tool for monitoring your application. Access it at:

```
http://localhost:8265
```

The dashboard shows:
- Actor statistics and memory usage
- CPU and memory utilization
- Logs and errors
- Task execution timeline

### Logging

Enable debug logging for more detailed information:

```bash
protean server --domain=your_domain --debug
```

## Conclusion

Ray integration provides a powerful way to scale your Protean applications with minimal code changes. The simplified, non-async implementation makes it easy to understand and use, while the robust error handling ensures your system remains resilient in the face of failures.

For most applications, the default configuration is sufficient, but the extensive configuration options available ensure you can optimize for your specific needs as your application grows. 