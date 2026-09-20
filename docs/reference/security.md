# Security considerations

Read this before you run Protean in production. It covers what the framework
does about security, what it leaves to you, and the settings that affect it.

The project's `SECURITY.md` covers how to report a vulnerability and which
release lines get security patches.

Protean applies a few safe defaults. It validates the structure of every field
value, and the bundled adapters build queries without concatenating your field
values into the query text. It does not handle authentication, transport
security, or output escaping. The sections below say where each responsibility
sits.

## Input handling

Protean validates every field value through Pydantic v2: types, `choices`,
length and range constraints, and required or empty checks. This is structural
validation. It keeps malformed or wrongly typed data out of your aggregates.

Structural validation is not an injection boundary. A value that passes
validation is still just a string. It may end up in HTML, in a shell command, or
in a SQL string you built by hand. Escaping a value for the place it is used
stays with you, at that output or sink.

## Field sanitization

`String` and `Text` fields do not sanitize their input by default. The stored
value is the raw input you gave them. This is a deliberate default: sanitizing at
input mangles data that was never meant for HTML, and the real fix for an HTML
sink is encoding the output where it is rendered.

You can opt in when a field's value really is HTML that gets rendered without
output encoding. There are two ways:

- Per field, pass `sanitize=True` on the `String` or `Text` field.
- Across the domain, set `sanitize = true` under `[field_defaults]` in
  `domain.toml`. Individual fields can still override it.

Precedence runs field keyword argument, then domain default, then the framework
default of off. When sanitization is on for a field, Protean runs the value
through `bleach.clean()`. This keeps a small set of safe tags and escapes the
rest, so markup like `<script>` becomes inert text instead of active HTML.

Sanitization is a convenience for text you render as HTML. It does not make
untrusted input safe to use everywhere, and turning it on domain-wide does not
change that.

## Persistence

The bundled SQLAlchemy adapter builds queries through SQLAlchemy with bound
parameters. The Elasticsearch adapter builds structured query objects. Neither
assembles a query by concatenating your field values into a query string, so
ordinary repository use, saving an aggregate or filtering a query, does not send
your field values to the database as raw query text.

Raw queries are the exception. A provider's `raw()` method runs a query string
you supply. On the SQLAlchemy provider, `raw(query, data)` binds the values in
`data` to named placeholders in the query, so pass user input through `data`
rather than formatting it into the query string. The repository's raw query path
runs your string as is and does not bind interpolated values. Either way, if you
build the query string by pasting user input into it, you own that boundary.

## Secrets in configuration

Protean reads broker URLs, database credentials, and similar values from your
domain configuration and the environment. It does not encrypt them, store them in
a vault, or manage their rotation. They live wherever you put them.

Keep secrets out of source control. Supply them through the environment or a
secret manager and let the configuration read them from there.

For logs specifically, Protean's logging can mask the values of named keys in log
output. The default redact list covers keys such as `password`, `token`,
`secret`, and `authorization`, and you can add to it. See
[Redaction](logging.md#redaction) for the list and how it works. That filter acts
on log output only. It does not protect a secret you place under an unrecognized
key, and it does not cover secrets that reach an error message or a traceback. You
control what your code logs and what your error output exposes.

## Left to the operator

Protean leaves the following to you and the platform you run on. None of it ships
in the framework:

- **Transport security.** TLS to brokers and databases is configured in the
  connection settings you provide. Protean does not add or require it.
- **Authentication and authorization.** Protean ships no auth primitive. Deciding
  who may call a command or read a projection is your application's job, at the
  edge in front of the domain.
- **Rate limiting and denial-of-service protection.** These belong at your API
  gateway, proxy, or framework layer.
- **Output escaping.** Escaping a value for HTML, SQL, shell, or any other sink
  happens where the value is used, not where it is stored.

One network service does ship: the Observatory. `protean observatory` runs a
FastAPI server that exposes domain internals and dead-letter-queue management
endpoints. It has no authentication and binds to loopback (`127.0.0.1`) by
default. If you bind it to any other address, put it behind an authenticating
reverse proxy on a trusted network. See
[`protean observatory`](cli/runtime/observatory.md).
