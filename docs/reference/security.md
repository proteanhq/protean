# Security considerations

This page states Protean's security posture: what the framework does for you,
what it does not, and the settings that affect it. Read it before you run Protean
in production so you know where each responsibility sits.

It is the companion to the project's `SECURITY.md`, which covers how to report a
vulnerability and which release lines get security patches. This page covers
posture, not reporting.

Protean is a domain framework, not a security product. It applies a few safe
defaults, such as bound query values and structural field validation. It does not
replace authentication, transport security, or output escaping. The sections below
say where each responsibility sits.

## Input handling

Protean validates every field value through Pydantic v2: types, `choices`,
length and range constraints, and required or empty checks. This is structural
validation. It keeps malformed or wrongly typed data out of your aggregates.

Structural validation is not an injection boundary. A value that is a valid
string is still just a string; Protean does not know whether you will render it
into HTML, pass it to a shell, or write it into a SQL string you built by hand.
Escaping for the place a value is used stays with you, at the output or sink
where it is used.

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
through `bleach.clean()`, which strips HTML tags and script.

Sanitization is a convenience for text you render as HTML. It is not a general
input firewall, and turning it on domain-wide does not make untrusted input safe
to use everywhere.

## Persistence

The bundled SQLAlchemy and Elasticsearch adapters build queries through their
client libraries with bound values. Ordinary repository use, saving an aggregate,
filtering a query, does not assemble SQL by string concatenation, so your field
values do not reach the database as raw query text.

There is one escape hatch. A provider's `raw()` method (and the repository's raw
query path) runs a query string you supply as is. The SQLAlchemy adapter passes
it straight to `text()` with no binding. If you build that string by pasting user
input into it, you own that boundary. Use bound parameters there too.

## Secrets in configuration

Protean reads broker URLs, database credentials, and similar values from your
domain configuration and the environment. It does not encrypt them, store them in
a vault, or manage their rotation. They live wherever you put them.

Keep secrets out of source control. Supply them through the environment or a
secret manager and let the configuration read them from there.

For logs specifically, Protean's logging can mask values whose keys look
sensitive. The default redact list covers keys like `password`, `token`,
`secret`, and `authorization`, and you can extend it. See
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
