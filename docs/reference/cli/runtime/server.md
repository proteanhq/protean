# `protean server`

The `server` command runs an asynchronous background server for your Protean application. This server initializes your domain and prepares it to handle requests, running the Protean Engine with the specified configuration.

## Usage

```shell
protean server [OPTIONS]
```

## Options

| Option                          | Description                                                                 | Default |
|---------------------------------|-----------------------------------------------------------------------------|---------|
| `--domain`                      | Sets the domain context for the server.                                     | `.`     |
| `--test-mode`                   | Runs the server in test mode.                                               | `False` |
| `--debug`                       | Enables debug mode for verbose logging.                                    | `False` |
| `--workers`                     | Number of worker processes to spawn.                                       | `1`     |
| `--reload`                      | Auto-reload on file changes (development only; cannot combine with `--workers > 1`). | `False` |
| `--acknowledge-event-store-risk`| Allow `--workers > 1` even with event-store subscriptions (see below).      | `False` |
| `--help`                        | Shows the help message and exits.                                          |         |

### Multiple workers and the event-store single-writer boundary

`--workers N` spawns `N` independent worker processes. Stream subscriptions
distribute messages across workers via Redis consumer groups, so they scale
horizontally.

Event-store subscriptions are single-writer: they read directly from the event
store with no cluster-wide ownership, so every worker would process the same
events. When any handler resolves to an event-store subscription, `protean
server --workers N` (with `N > 1`) refuses to start and names the offending
handlers. Resolve it by running a single worker, switching those handlers to
stream subscriptions (`subscription_type = "stream"`), or passing
`--acknowledge-event-store-risk` to override (accepting that events will be
double-processed).

## Starting the Server

To launch the async server with default settings:

```shell
protean server
```

### Specifying a Domain

To run the server within a specific domain context, use the `--domain` option followed by the domain path:

```shell
protean server --domain auth
```

This command will initiate the server in the context of the `auth` domain. Read [Domain Discovery](../project/discovery.md) for options to specify the domain.

### Test Mode

To run the server in test mode, which may alter certain behaviors to facilitate testing:

```shell
protean server --test-mode
```

### Debug Mode

To enable debug mode with additional logging and information:

```shell
protean server --debug
```

You can combine these options as needed:

```shell
protean server --domain auth --debug
```
