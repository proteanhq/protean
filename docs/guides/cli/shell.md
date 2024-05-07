# `protean shell`

The `shell` command starts an interactive shell with your Protean application 
pre-loaded. On the underside, the console command uses `ipython`, so if you've 
ever used it, you'll be right at home. This is useful for testing out quick 
ideas with code and changing data server-side without using an interface.

## Usage

```shell
protean shell [OPTIONS]
```

## Options

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

This command will initiate the shell in the context of `auth` domain, allowing
you to perform domain-specific operations more conveniently. Read [Domain 
Discovery](discovery.md) for options to specify the domain.

### Traversing subdirectories

By default, only the domain and elments in the specified module will be loaded
into the shell context. If you want traverse files in the folder and its
subdirectories, you can specify the `--traverse` option.

```shell
protean shell --domain auth --traverse
```
