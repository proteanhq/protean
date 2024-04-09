
# `protean new`

The `protean new` command initializes a new project with a given name. 

## Usage

```shell
protean new [OPTIONS] PROJECT_NAME
```

## Arguments

| Argument       | Description             | Default | Required |
|----------------|-------------------------|---------|----------|
| `PROJECT_NAME` | Name of the new project | None    | Yes      |

## Options

- `--output-dir`, `-o`: Specifies the directory where the project should be 
created. If not provided, the current directory is used.

!!! note
    Throws an error if the output directory is not found or not empty.
    Combine with `--force` to overwrite existing directory.

- `--data`, `-d`: Accepts one or more key-value pairs to be included in
the project's configuration.
- `--help`: Shows the help message and exits.

### Behavior Modifiers

- `--pretend`, `-p`: Runs the command in a "dry run" mode, showing what
would be done without making any changes.
- `--force`, `-f`: Forces the command to run even if it would overwrite
existing files.

## Examples

### Creating a New Project

To create a new project named "authentication" in the current directory:

```shell
protean new authentication
```

### Specifying an Output Directory

To create a new project in a specific directory:

```shell
protean new authentication -o /path/to/directory
```

### Using Configuration Data

To pass key-value pairs for project configuration:

```shell
protean new authentication -d key1 value1 -d key2 value2
```