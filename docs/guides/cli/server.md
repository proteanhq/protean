# `protean server`

The `server` command runs an asynchronous background server for your Protean application. This server initializes your domain and prepares it to handle requests, running the Protean Engine with the specified configuration.

## Usage

```shell
protean server [OPTIONS]
```

## Options

| Option        | Description                                  | Default |
|---------------|----------------------------------------------|---------|
| `--domain`    | Sets the domain context for the server.      | `.`     |
| `--test-mode` | Runs the server in test mode.                | `False` |
| `--debug`     | Enables debug mode for verbose logging.      | `False` |
| `--help`      | Shows the help message and exits.            |         |

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

This command will initiate the server in the context of the `auth` domain. Read [Domain Discovery](discovery.md) for options to specify the domain.

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
