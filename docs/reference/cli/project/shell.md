# `protean shell`

The `shell` command starts an interactive shell with your Protean application
pre-loaded. The `shell` command runs on `ipython`. If you have used `ipython`
before, the shell works the way you expect. This is useful for testing out
quick ideas with code and changing data server-side without using an interface.

## Run the command

```shell
protean shell [OPTIONS]
```

## Choose the options

| Option        | Description                               | Default |
|---------------|-------------------------------------------|---------|
| `--domain`    | Sets the domain context for the shell.    | `.`     |
| `--traverse`  | Auto-traverse domain elements             | `False` |
| `--help`      | Shows the help message and exits.         |         |

## Launching the Shell

To launch the interactive shell with default settings:

```shell
protean shell
```

### Specifying a Domain

To launch the shell within a specific domain context, use the `--domain` option
followed by the domain name:

```shell
protean shell --domain auth
```

This command starts the shell in the context of the `auth` domain, so you can
run domain-specific operations more easily. Read [Domain
Discovery](discovery.md) for options to specify the domain.

### Traversing subdirectories

By default, the shell loads only the domain and the elements in the specified
module into the shell context. If you want traverse files in the folder and its
subdirectories, you can specify the `--traverse` option.

```shell
protean shell --domain auth --traverse
```
