# Protean FastAPI Server

The Protean framework provides a built-in FastAPI server that allows you to quickly expose your domain through a REST API. This guide covers how to start, access, and customize the server for your application.

## Starting the Server

Protean provides a CLI command called `server` that starts a FastAPI server. You can run it from the command line:

```bash
protean server --domain=path/to/domain --port=8000
```

### Command Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--domain` | Path to the domain | `.` (current directory) |
| `--host` | Host to bind to | `0.0.0.0` |
| `--port` | Port to bind to | `8000` |
| `--debug` | Enable debug mode | `False` |
| `--cors` | Enable CORS | `True` |
| `--cors-origins` | Comma-separated list of allowed CORS origins | `*` |

### Domain Discovery

The `--domain` parameter can be specified in several formats:

- **Module in current folder**: `--domain=my_domain`
- **Module in a subfolder**: `--domain=src/my_domain`
- **Module string**: `--domain=my_package.my_domain`
- **Specific instance**: `--domain=my_domain:app2`

The server attempts to locate your domain in the following order:

1. Check the `PROTEAN_DOMAIN` environment variable (if set)
2. Use the path provided in the `--domain` parameter
3. Look for a `domain.py` or `subdomain.py` file in the current directory

When a module is found, the server looks for a domain in the following order:

1. Variable named `domain` or `subdomain`
2. Any variable that is an instance of `Domain`
3. If multiple instances are found, an error is raised

Example:

```bash
# Using a specific module
protean server --domain=my_app.domain

# Using a specific instance in a module
protean server --domain=my_app.domain:my_domain_instance

# Using environment variable (alternative)
export PROTEAN_DOMAIN=my_app.domain
protean server
```

## Accessing the FastAPI Server

Once the server is running, you can access the root endpoint at `http://localhost:8000/` (or whatever host and port you've configured). This endpoint returns basic information about your domain:

```json
{
  "status": "success",
  "message": "Protean API server running with domain: YourDomainName",
  "data": {
    "domain": {
      "name": "YourDomainName",
      "normalized_name": "your_domain_name"
    }
  }
}
```

## Customizing the FastAPI App

The Protean server is built on FastAPI, which means you can leverage all FastAPI features for your API. You can customize the FastAPI application using the `create_app` factory function:

```python
from protean.server.fastapi_server import create_app
from protean.utils.domain_discovery import derive_domain

# Get your domain
domain = derive_domain("./my_domain")

# Create the FastAPI app
app = create_app(
    domain=domain,
    debug=True,
    enable_cors=True,
    cors_origins=["http://localhost:3000"]
)

# Add custom routes, middleware, etc.
@app.get("/custom")
async def custom_endpoint():
    return {"message": "Custom endpoint"}

# Add custom middleware
@app.middleware("http")
async def custom_middleware(request, call_next):
    # Do something before the request is processed
    response = await call_next(request)
    # Do something after the request is processed
    return response

# Run with uvicorn
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8000)
```

This approach gives you full control over the FastAPI application while still ensuring the Protean domain context is properly set up.

## Server Functionality

The Protean FastAPI server provides several important functions:

1. **Domain Context**: The server sets up a domain context for each request, ensuring that domain operations execute in the correct context.

2. **CORS Support**: Built-in CORS middleware that can be configured based on your application's needs.

3. **API Documentation**: Since it's built on FastAPI, you automatically get interactive API documentation at `/docs` and `/redoc` endpoints.

4. **Error Handling**: The server provides consistent error responses for domain exceptions.

## Advanced Configuration

For more advanced use cases, you might want to configure logging, add authentication middleware, or integrate with other FastAPI extensions. These can all be accomplished by accessing the underlying FastAPI application.

## Event Handling and Message Processing

The Protean server plays a crucial role in the event-driven architecture by managing subscriptions and processing messages:

### Subscription Management

When the server starts, it automatically:

1. **Collects Subscriptions**: The server scans your domain for defined event and command handlers.

2. **Initializes Subscribers**: Each handler is initialized as a polling subscriber and registered with the event store.

3. **Manages Subscription Lifecycle**: The server handles the lifecycle of subscriptions, including starting, stopping, and error handling.

### Event Store Polling

The server continuously polls the event store for new messages:

1. **Command Processing**: Incoming commands are routed to their appropriate handlers.

2. **Event Handling**: Domain events are distributed to all interested handlers.

3. **Message Ordering**: Messages are processed in the order they were published to maintain consistency.

### Configuring Subscription Behavior

You can configure how subscriptions work through your domain configuration:

```python
# Example domain configuration
domain = Domain(
    name="example",
    # Configure event store and its subscriptions
    config={
        "event_store": {
            "provider": "message_db",
            "database_uri": "postgresql://message_store@localhost:5433/message_store",
            "polling_interval": 1.0,  # Poll interval in seconds
            "max_retry_count": 3,     # Number of retries for failed processing
        }
    }
)
```
