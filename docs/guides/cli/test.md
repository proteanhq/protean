# `protean test`

The `protean test` command is used to run unit tests. You can specify the
category of tests to run using the `--category` option.

## Usage

```shell
protean test [OPTIONS]
```

## Options

| Option              | Description                               | Default |
|---------------------|-------------------------------------------|---------|
| `--category`, `-c`  | Specifies the category of tests to run.  |         |
| `--help`            | Shows the help message and exits.         |         |


Category Options:

- `CORE`: Runs core framework tests. This is the default category if none is specified.
- `EVENTSTORE`: Runs tests related to the event store functionalities.
- `DATABASE`: Runs database-related tests.
- `FULL`: Runs all available tests, including core, event store, and database tests.

## Examples

### Run core framework tests (the default)

```shell
protean test
```

### Run database related tests

```shell
protean test --category DATABASE
```

### Run all tests with coverage

```shell
protean test --category FULL
```
