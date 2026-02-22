# `protean docs`

The `protean docs preview` command starts a live preview server for Protean
documentation. This allows you to view changes in real-time as you edit.

## Usage

```shell
protean docs preview [OPTIONS]
```

## Options

- `--help`: Shows the help message and exits.

## Running a Preview Server

To start the live preview server for your project's documentation, simply run
the command without any additional options:

```shell
protean docs preview`
```

This will start a local server, usually accessible via a web browser at a URL
such as `http://localhost:8000`. The exact URL will be displayed in your
command line interface once the server is running:

```shell
INFO    -  Building documentation...
INFO    -  Cleaning site directory
INFO    -  Documentation built in 0.56 seconds
INFO    -  [09:45:08] Watching paths for changes: 'docs', 'mkdocs.yml'
INFO    -  [09:45:08] Serving on http://127.0.0.1:8000/
```