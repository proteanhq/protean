# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [0.18.0] - 2026-10-21

### Upgrade Notes

Read the [0.18 migration guide](https://docs.proteanhq.com/reference/migration/v0-18/) before you upgrade. These changes can need action:

<details markdown="1">
<summary>48 breaking changes</summary>

- [Right-size the runtime dependency surface](https://docs.proteanhq.com/reference/migration/v0-18/#what-moved-behind-extras) (#1000)
- [cffi and greenlet left the core install](https://docs.proteanhq.com/reference/migration/v0-18/#cffi-and-greenlet-left-the-core-install) (#1376)
- [PostgreSQL defaults to psycopg 3](https://docs.proteanhq.com/reference/migration/v0-18/#postgresql-defaults-to-psycopg-3) (#1689)
- [werkzeug left the core install](https://docs.proteanhq.com/reference/migration/v0-18/#werkzeug-left-the-core-install) (#1375)
- [`check` and `verify` machine output changed shape and exit codes](https://docs.proteanhq.com/reference/migration/v0-18/#check-and-verify-machine-output-changed-shape-and-exit-codes) (#1329)
- [`events catalog`, `subscriptions status`, and `projection status` JSON moved onto the envelope](https://docs.proteanhq.com/reference/migration/v0-18/#events-catalog-subscriptions-status-and-projection-status-json-moved-onto-the-envelope) (#1394)
- [The memory cache no longer raises on an absent key](https://docs.proteanhq.com/reference/migration/v0-18/#the-memory-cache-no-longer-raises-on-an-absent-key) (#1391)
- [`get_ttl` returns None or math.inf instead of a raw sentinel](https://docs.proteanhq.com/reference/migration/v0-18/#get_ttl-returns-none-or-mathinf-instead-of-a-raw-sentinel) (#1392)
- [Cache key patterns are a glob on every adapter](https://docs.proteanhq.com/reference/migration/v0-18/#cache-key-patterns-are-a-glob-on-every-adapter) (#1393)
- [Cache `get_all` is now the private, unpaginated `_get_all`](https://docs.proteanhq.com/reference/migration/v0-18/#cache-get_all-is-now-the-private-unpaginated-_get_all) (#1401)
- [`flush_all()` on a Redis cache clears only its database](https://docs.proteanhq.com/reference/migration/v0-18/#flush_all-on-a-redis-cache-clears-only-its-database) (#1880)
- [The IR schema is now v0.2.0](https://docs.proteanhq.com/reference/migration/v0-18/#the-ir-schema-is-now-v020) (#1433)
- [The IR schema is now v0.3.0](https://docs.proteanhq.com/reference/migration/v0-18/#the-ir-schema-is-now-v030) (#1723)
- [`diff_ir()` checks every field of a published event](https://docs.proteanhq.com/reference/migration/v0-18/#diff_ir-checks-every-field-of-a-published-event) (#1781)
- [Diagnostic and CLI messages no longer contain em-dashes](https://docs.proteanhq.com/reference/migration/v0-18/#diagnostic-and-cli-messages-no-longer-contain-em-dashes) (#1863)
- [`protean ir` rejects an unknown format value](https://docs.proteanhq.com/reference/migration/v0-18/#protean-ir-rejects-an-unknown-format-value) (#1435)
- [`protean new .` and `protean new ..` are rejected](https://docs.proteanhq.com/reference/migration/v0-18/#protean-new-and-protean-new-are-rejected) (#1466)
- [`protean new` refuses a target symlinked out of the output directory](https://docs.proteanhq.com/reference/migration/v0-18/#protean-new-refuses-a-target-symlinked-out-of-the-output-directory) (#1466)
- [String and Text no longer sanitize by default](https://docs.proteanhq.com/reference/migration/v0-18/#string-and-text-no-longer-sanitize-by-default) (#1455)
- [`choices` fields map to their declared column type](https://docs.proteanhq.com/reference/migration/v0-18/#choices-fields-map-to-their-declared-column-type) (#1791)
- [The InlineBroker no longer dead-letters a message its subscription owns](https://docs.proteanhq.com/reference/migration/v0-18/#the-inlinebroker-no-longer-dead-letters-a-message-its-subscription-owns) (#1265)
- [Replay hazards on an event-sourced aggregate are now breaking](https://docs.proteanhq.com/reference/migration/v0-18/#replay-hazards-on-an-event-sourced-aggregate-are-now-breaking) (#841)
- [Removing a field from an event-sourced aggregate needs `reserved`](https://docs.proteanhq.com/reference/migration/v0-18/#removing-a-field-from-an-event-sourced-aggregate-needs-reserved) (#1584)
- [A RawIndex with an unknown dialect now raises](https://docs.proteanhq.com/reference/migration/v0-18/#a-rawindex-with-an-unknown-dialect-now-raises) (#1585)
- [The test-mode engine stops as soon as it is idle](https://docs.proteanhq.com/reference/migration/v0-18/#the-test-mode-engine-stops-as-soon-as-it-is-idle) (#1617)
- [`assert_valid` and `assert_invalid` are removed](https://docs.proteanhq.com/reference/migration/v0-18/#assert_valid-and-assert_invalid-are-removed) (#1622)
- [`protean server` and `protean observatory` apply the logging section](https://docs.proteanhq.com/reference/migration/v0-18/#protean-server-and-protean-observatory-apply-logging) (#1635)
- [The lint and observatory tables now load](https://docs.proteanhq.com/reference/migration/v0-18/#lint-and-observatory-tables-now-load) (#1629)
- [A zero read timeout on Redis no longer waits](https://docs.proteanhq.com/reference/migration/v0-18/#a-zero-read-timeout-on-redis-no-longer-waits) (#1660)
- [The memory provider's `raw()` raises `DatabaseError`, and some error logs drop the exception text](https://docs.proteanhq.com/reference/migration/v0-18/#the-memory-providers-raw-raises-databaseerror-and-some-error-logs-drop-the-exception-text) (#1714)
- [Some internal fallbacks let unexpected errors through](https://docs.proteanhq.com/reference/migration/v0-18/#some-internal-fallbacks-let-unexpected-errors-through) (#1715, #1716, #1730)
- [A `ValueError` at commit is no longer reported as a version conflict](https://docs.proteanhq.com/reference/migration/v0-18/#a-valueerror-at-commit-is-no-longer-reported-as-a-version-conflict) (#1682)
- [A synchronous event handler's version conflict no longer reruns the command](https://docs.proteanhq.com/reference/migration/v0-18/#a-synchronous-event-handlers-version-conflict-no-longer-reruns-the-command) (#1883)
- [An omitted value object argument gets the value object's default](https://docs.proteanhq.com/reference/migration/v0-18/#an-omitted-value-object-argument-gets-the-value-objects-default) (#1686)
- [A domain with no environment set logs at INFO](https://docs.proteanhq.com/reference/migration/v0-18/#a-domain-with-no-environment-set-logs-at-info) (#1747)
- [A non-dict positional argument raises `TypeError`](https://docs.proteanhq.com/reference/migration/v0-18/#a-non-dict-positional-argument-raises-typeerror) (#1717)
- [`sequential_by` on a handler or projector must be a field name](https://docs.proteanhq.com/reference/migration/v0-18/#sequential_by-on-a-handler-or-projector-must-be-a-field-name) (#1649)
- [A non-boolean `sequential_by` on a process manager is deprecated](https://docs.proteanhq.com/reference/migration/v0-18/#a-non-boolean-sequential_by-on-a-process-manager-is-deprecated) (#1787)
- [An integer identity under the `uuid` strategy is refused on SQL](https://docs.proteanhq.com/reference/migration/v0-18/#an-integer-identity-under-the-uuid-strategy-is-refused-on-sql) (#1586)
- [Saving the same aggregate instance again writes a new version](https://docs.proteanhq.com/reference/migration/v0-18/#saving-the-same-aggregate-instance-again-writes-a-new-version) (#1744)
- [A failed IR build now fails `check`](https://docs.proteanhq.com/reference/migration/v0-18/#a-failed-ir-build-now-fails-check) (#1685)
- [Domain traversal loads modules in name order](https://docs.proteanhq.com/reference/migration/v0-18/#domain-traversal-loads-modules-in-name-order) (#1664)
- [The `database_model` element option is removed](https://docs.proteanhq.com/reference/migration/v0-18/#the-database_model-element-option-is-removed) (#1607)
- [mypy sees decorated elements as subclasses of their base](https://docs.proteanhq.com/reference/migration/v0-18/#mypy-sees-decorated-elements-as-subclasses-of-their-base) (#1874)
- [A value object's string `part_of` must name an aggregate](https://docs.proteanhq.com/reference/migration/v0-18/#a-value-objects-string-part_of-must-name-an-aggregate) (#1897)
- [The multi-worker Supervisor waits for the drain window](https://docs.proteanhq.com/reference/migration/v0-18/#the-multi-worker-supervisor-waits-for-the-drain-window) (#1896)
- [`protean new --pretend` is now `--dry-run`, and it writes nothing](https://docs.proteanhq.com/reference/migration/v0-18/#protean-new-pretend-is-now-dry-run-and-it-writes-nothing) (#1466, #1473)
- [`protean schema render --indexes` rejects an unknown dialect](https://docs.proteanhq.com/reference/migration/v0-18/#protean-schema-render-indexes-rejects-an-unknown-dialect) (#1580)

</details>

To find deprecated calls before the release that removes them, run `protean check`, or run your tests with `ProteanDeprecationWarning` promoted to an error.

### Added

- [Examples] Added `examples/reference_app/blog.py`, the golden-path blog domain showing the full write-then-read arc, runnable with `python blog.py`. (#1483)
- [Examples] Added `examples/reference_app/app/`, a runnable FastAPI app over the blog domain with `POST /posts` and `GET /posts`, on SQLite and the inline broker. (#1484)
- [CLI] Added `protean verify`, which runs init, `protean check` and the project's pytest suite in order and returns one verdict, with `--json` and a stable exit-code contract. (#1323)
- [Testing] Added an end-to-end test that runs `protean verify --json` on a freshly generated project and asserts a green verdict. (#1324)
- [IR] Added `protean.ir.diagnostics`, the registry holding every diagnostic code and its metadata; codes are now a stable public identifier guarded by a golden snapshot test. (#1326)
- [IR] Init-time and runtime raises now carry a stable diagnostic `code`, plus `location`, `rationale` and `fix`, cataloged in the [Init-time and Runtime Diagnostics](https://docs.proteanhq.com/reference/init-diagnostics/) reference. (#1331)
- [IR] A failed `@invariant.pre` or `@invariant.post` now raises a `ValidationError` carrying a stable diagnostic `code` (or `codes`), with its `rationale` and `fix`; stamp your own with `code=`. (#1332)
- [IR] A diagnostic can now name the command that fixes it through `resolving_operation`; the first is `IR_STALE`, resolved by `protean-check-staleness --fix`. (#1333)
- [CLI] Added `protean docs generate --type=event-model`, an EventModeling slice timeline rendered from the IR, as one `flowchart LR` (`--format=mermaid`) or a fence per slice (`--format=markdown`). (#1335)
- [Check] Added `UNRAISED_EVENT`, an info-level fitness function flagging a domain event no aggregate or entity method raises, the producer-side mirror of `UNHANDLED_EVENT`. (#1337)
- [CLI] Added an annotation layer to `protean docs generate --type=event-model`: notes in `.protean/annotations.toml`, keyed by element FQN, merge into each slice that draws the element, with unmatched keys reported. (#1338)
- [IR] Materialized approximate `raises` and `invokes` edges under a new `method_edges` key and bumped the IR schema to v0.2.0; both are read from source as written, so treat them as a guide. (#1433)
- [Check] Added `UNSOURCED_PROJECTION_FIELD`, which flags a projection field no projector write fills. It reads observed writes, so it is advisory. (#1434)
- [IR] `protean ir diff --format=event-model` renders a diff in EventModeling slice vocabulary, over the same snapshot loaders and exit codes as the text format. (#1435)
- [Scaffold] Added a `protean.scaffold` package with a versioned `ChangePlan`: a serializable, previewable description of a change that round-trips through JSON and touches no files. (#1327)
- [Scaffold] `protean new` now writes a derived manifest at `.protean/project.json`, and `check_manifest_drift` recomputes it to report where a stored file disagrees with the code (ADR-0034). (#1328)
- [CLI] Added `protean add <element-type> <name>`, which computes a create-only ChangePlan for one aggregate slice and previews it without writing. (#1340)
- [CLI] Added `protean docs generate --type=llms`, which emits a versioned `llms.txt` context pack: a framework layer plus, when given a domain, that project's own elements. (#1344)
- [CLI] Added `protean docs generate --type=agents`, which emits a versioned `AGENTS.md` with one hard rule per error-level diagnostic code; `protean new` now writes it at the project root. (#1346)
- [Scaffold] Added `protean.scaffold.model_parser`, the ADR-0041 text event-model grammar: `parse_model` reads a one-slice model into an IR fragment, and `emit_model` writes grammar text back, refusing anything it cannot express. (#1471)
- [Scaffold] Added a slice generator behind `protean add` that writes a full vertical slice (aggregate, command, event, handler, projection, projector) from an IR fragment, deriving the read side when you omit it. (#1472)
- [CLI] Added `protean new --from-model <file>`, which parses a text event model, creates the project, writes the slice, and runs the same checks as `protean verify`, in one step. (#1473)
- [DX] The `protean` wheel now bundles a versioned developer-experience pack (an AGENTS.md source and the teaching skills) under `protean.dx`, so agent guidance always matches the installed version. (#1463)
- [DX] Added `protean.dx`, an idempotent managed-file writer that re-writes a generated artifact without clobbering the user's own edits, through a managed-block or managed-JSON-keys merge (ADR-0037). (#1464)
- [DX] Added the `protean dx` command group: `install` writes an `AGENTS.md` and a `CLAUDE.md` bridge composed from the installed version, `diff` previews, and `check` exits non-zero on drift. (#1465)
- [Scaffold] Added `protean.scaffold.create_project`, which scaffolds a project from Python with a `dry_run=True` preview; `protean new` is now a thin wrapper over it. (#1466)
- [MCP] Added `protean mcp`, a Model Context Protocol server exposing `validate`, `check`, `introspect`, `explain` and `scaffold` as tools, on stdio or `--http`, behind the `protean[mcp]` extra. (#1467)
- [DX] A DX-pack skill can now declare the diagnostic codes it teaches in its `SKILL.md` frontmatter, read back through `skill_diagnostic_codes` and `diagnostic_code_skills`. (#1468)
- [DX] `protean dx install` now also writes Cursor's `.cursor/rules/protean.mdc`, Copilot's `.github/copilot-instructions.md` and opencode's `opencode.json`, all idempotent and covered by `dx check`. (#1474)
- [DX] `protean dx install` now writes a `.mcp.json` registering Protean's MCP server under `mcpServers.protean`, preserving every other server you configured. (#1475)
- [CLI] Added `protean docs generate --type=llms --check`, which compares a committed `llms.txt` snapshot byte for byte and exits non-zero on drift, with a `[tool.protean.docs].domain_snapshot` config key. (#1516)
- [DX] The `protean dx` pack now ships all 35 teaching skills and their 12 pattern-reference rules, relicensed to Apache-2.0 and travelling in the wheel as package data. (#1521)
- [DX] Added `protean dx build-plugin`, which renders the packaged teaching skills into a Claude Code plugin, with `--check` as the drift guard. (#1522)
- [Event store] Added `read_all` on the event-store port, a generator that pages through a whole stream in bounded batches; projection rebuilds now read through it, so a rebuild past the old read cap replays completely. (#1358)
- [Event store] Added `verify()` on `BaseEventStore` and a `protean eventstore verify` command: a read-only integrity check over row shape, per-stream positions, global position, message ids and snapshots. (#1359)
- [Event store] Added `protean recover --verify-checkpoints`, a read-only check reporting each subscription whose checkpoint is ahead of its stream head after a restore. (#1361)
- [Event store] Added `protean recover --reset-beyond-head`, which snaps each beyond-head checkpoint back to the stream head; it needs `--verify-checkpoints` to find what to reset. (#1446)
- [Event store] `protean recover --verify-checkpoints` now also flags recovery-tracking entries whose message a restore removed, and `--reset-beyond-head` clears them so the recovery pass stops retrying them forever. (#1529)
- [Event store] `protean subscriptions status --json` and the Observatory subscription payload now carry `recovery_checkpoint_stream` and `failed_positions_stream`, both `null` for non-event-store subscriptions. (#1529)
- [Event store] Added a `protean eventstore dlq` command group: `list` shows the positions a subscription exhausted, grouped by subscription, and `inspect <position>` re-reads the failing event. (#1364)
- [Event store] Added `protean eventstore dlq replay` and `purge`: `replay` re-drives a failing event through its handler once without moving the read cursor, and `purge` appends a terminal marker that survives a rebuild. (#1365)
- [Server] Added a graceful drain window and a `POST /drainz` endpoint: the engine stops pulling new batches while in-flight handlers finish, and `server.drain_timeout` (default 10 seconds) sets how long shutdown waits. (#1366)
- [Observability] Event-store subscriptions now report `lag_seconds` alongside the message-count lag, reaching `protean subscriptions status`, `/readyz`, the OTel gauge, the Prometheus fallback and the Observatory. (#1367)
- [Observability] Added `lag_drain_rate` to each subscription row in `/readyz`, the change in `lag_seconds` per second: negative while a backlog drains, positive while it grows. (#1368)
- [DX] Added the `add-saga-flow` teaching skill, which sequences the `process-manager` skill into an end-to-end order-fulfillment saga with a compensating path, with runnable before and after assets. (#1555)
- [DX] Added the `split-aggregate` teaching skill, which walks through splitting an oversized aggregate along its consistency boundary and linking the halves by identity and an event. (#1556)
- [DX] Added the `extract-bounded-context` teaching skill, which takes a set of aggregates into a second `Domain` and wires the two by events across the seam, clearing `CIRCULAR_CLUSTER_DEPENDENCY`. (#1557)
- [MCP] Added `teaching_skills` to the `explain` tool's result, plus a coverage guard that fails the suite when a new lint code ships with no teaching skill and no documented exemption. (#1558)
- [Check] Added `HANDLER_PERSISTS_AND_CALLS_OUT`, reported when one handler method both persists through a repository and calls an external system. It is advisory; silence it with `suppress_checks`. (#1408)
- [Docs] Added a pattern page, "Calling External Systems from Handlers", documenting the rule that a handler method persists or calls out, never both. (#1409)
- [Types] A query can declare its handler's return type by subscripting the base (`class GetOrderSummary(BaseQuery[OrderSummary])`), so `domain.dispatch` resolves to that type instead of `Any` (ADR-0043). (#1118)
- [Fields] Added `Custom`, a field factory over a custom Python type: pass the validators and serializers it needs, and it behaves like a built-in field, round-tripping through save, reload and event replay (ADR-0044). (#1119)
- [CLI] Added `protean upgrade-check --opportunities`, which reports shipped capability the domain still hand-rolls, with three deterministic detectors each naming the release its capability arrived in. (#1294)
- [Docs] Added an [Applicability Charter](https://docs.proteanhq.com/reference/applicability/) covering what Protean fits, what it does not, what you keep control of, and how it scales, so a prospective user can self-qualify. (#1354)
- [Docs] ADR-0040 writes down the schema-evolution ladder: weak schema for additive and rename changes, versioning plus an upcaster for structural ones, and an operator migration for a long chain. (#1400)
- [CI] Added Python 3.15 to the supported versions, in the PyPI classifiers, the Nox sessions and CI; both 3.15 legs are non-blocking while it is a prerelease. (#1426)
- [Docs] Added a [Security Considerations](https://docs.proteanhq.com/reference/security/) reference: field validation is not an injection boundary, raw queries are the operator's boundary, and the four shipped network services do not authenticate the caller. (#1482)
- [Database] Added a `mysql` provider serving both MySQL and MariaDB through SQLAlchemy and PyMySQL, installed with `pip install "protean[mysql]"`. See the [MySQL reference](https://docs.proteanhq.com/reference/adapters/database/mysql/). (#1580)
- [Projections] Projectors accept the `sequential_by` option, with the same meaning as on event handlers, so a category only a projector consumes can be processed in per-key order. (#1649)
- [Event store] Added `get_or_none()` to the event-sourced repository, which takes the same arguments as `get()` and returns `None` where `get()` would raise `ObjectNotFoundError`. (#1659)
- [CLI] Added `protean verify --env NAME`, which sets the environment init, check and tests all run under (default `test`), ignoring `PROTEAN_ENV` and any `--protean-env` in pytest addopts. (#1662)
- [IR] The IR now records `auto_now` and `auto_now_add` on `Date` and `DateTime` fields and lists registered enrichers in a new top-level `enrichers` section, both reported by `protean ir diff`. (#1664)
- [Testing] `DomainFixture.setup()` now pings every configured broker once and warns for each one that does not answer, naming the broker and its URI with any password masked. (#1916)

### Changed

- [Docs] Every runnable example in the docs now lives in `docs_src`, with a test that runs it and checks what the page says it does. (#1671)
- [Docs] Rewrote the quickstart around the canonical `Post` domain, pulling every snippet from `examples/reference_app/blog.py` with `--8<--` so the page shows the code the tests run, and closing the write-then-read arc with the projection. (#1485)
- [Docs] Replaced the README "Quick Start" block with the canonical `Post` domain, with a guard test that compares it against the reference module verbatim and fails on drift. (#1486)
- [Docs] Pointed the README and the docs at the runnable reference application and the Shopstream example, reference app first. (#1487)
- [Scaffold] `protean new` now scaffolds a minimal walking skeleton instead of a broad demo: one slice from command to projector, plus a smoke test and two passing tests, so `pytest` runs green on a fresh project. (#1321)
- [Scaffold] The generated `tests/conftest.py` initialises the domain through a session-scoped autouse fixture instead of `pytest_sessionstart`, so a plain `pytest` sets up the domain context. (#1321)
- [CLI] **Breaking (machine output and exit codes).** `protean check --format json` and `protean verify --json` now emit one shared, versioned result envelope (`{version, status, data, diagnostics}`) with a pinned JSON Schema, and both adopt one exit-code convention. (#1329)
- [CLI] **Breaking (machine output).** `protean events catalog --json`, `protean subscriptions status --json` and `protean projection status --json` now emit the shared result envelope instead of a bare JSON array, with the list under `data`. (#1394)
- [CLI] Each Markdown slice of `protean docs generate --type=event-model` now leads with a structural Given-When-Then derived from the IR; the `--format=mermaid` output is unchanged. (#1336)
- [IR] **Breaking.** The IR schema moved from `0.1.0` to `0.2.0` to carry the new `method_edges` key, so a committed `.protean/ir.json` baseline reports a version mismatch until you regenerate it. (#1433)
- [IR] `--format` is now validated on `protean ir diff`, `ir show` and `ir check`; an invalid value fails with the valid formats listed, where it used to fall through to the default silently. (#1435)
- [CLI] `protean add` now splits the aggregate it plans across a generation-gap seam, a generated base and a hand-owned subclass, with each planned file marked `generated` or `hand_owned`. (#1341)
- [CLI] `protean add <element> <name>` now writes the slice to disk by default, create-only and rolling back a partial write; pass `--dry-run` for the old preview-only behavior. (#1342)
- [CLI] **Breaking.** `protean new`'s dry-run flag is `--dry-run`. `--pretend` and its `-p` short form are gone, and passing either is a usage error. (#1473)
- [CLI] **Breaking.** `protean new`'s dry run no longer touches the target directory: it renders into a temp directory and prints the project-relative paths it would create. (#1466)
- [DX] `protean new` now ships a dx-managed project, writing the same managed-block `AGENTS.md` and `CLAUDE.md` bridge that `protean dx install` writes and recording them in `.protean/dx-state.json`. (#1515)
- [DX] `protean dx check` now verifies a required baseline (`AGENTS.md` and the `CLAUDE.md` bridge) plus whatever optional target is present on disk or recorded in `.protean/dx-state.json`, so an editor file you never chose is no longer counted as drift. (#1515)
- [DX] `protean dx refresh` now writes only what a project already has, sharing one scope with `check`, where it used to write all six targets the way `install` does. (#1515)
- [DX] Hardened the twelve building-block teaching skills and wired them to the diagnostic contract: the six that teach a coded convention declare their codes under `metadata.diagnostic_codes`, and several statements about the framework and about what the checks measure are corrected. (#1552)
- [DX] Hardened the event-driven and CQRS teaching skills, fixing drift against the current API (`event_sourced=True`, value objects allowed in projections, `BaseEventSourcedRepository`) and declaring the codes each one teaches. (#1553)
- [DX] Hardened the DX-pack workflow, refactor and analysis skills: six declare the `check` codes they teach the fix for, a test fails a skill that declares a code it never mentions, and a drifted upcaster example is corrected. (#1554)
- [Event store] Removing a field from an event-sourced aggregate can now be earned safe by naming it in `reserved`: during replay an assignment to a reserved name is dropped instead of raising, and `protean ir diff` downgrades the removal to safe. (#1584)
- [Types] Under the mypy plugin, a class decorated with an element decorator is now a subclass of its Protean base class, as it is at runtime, so it is accepted wherever a signature names the base. (#1874)
- [Packaging] **Breaking.** Right-sized the runtime dependency surface: `fastapi`, `uvicorn`, `jinja2`, `ipython` and `copier` moved out of the core install into feature extras (`protean[server]`, `protean[shell]`, `protean[scaffold]`), with `protean[cli]` and `protean[all]` bundles. (#1000)
- [Packaging] **Breaking.** Replaced Werkzeug's `LocalProxy`/`LocalStack` with stdlib `contextvars` for `current_domain`, `current_uow` and `g`, so the active context follows asyncio tasks and `werkzeug` is no longer a core dependency. (#1375)
- [Packaging] **Breaking.** `cffi` and `greenlet` are no longer core dependencies; nothing in Protean imports either, and their floors moved to the extras that pull them. (#1376)
- [Cache] `get_ttl(key)` now answers the same three cases on every adapter: `None` when there is no such key, `math.inf` when the key never expires, and the seconds remaining otherwise. (#1392)
- [Cache] **Breaking (both cache adapters).** `BaseCache.get_ttl` now returns `float | None` where it returned `float`; `BaseCache` is a Provisional API, so the change lands in a minor release with no deprecation period. (#1392)
- [Cache] The `key_pattern` argument to `_get_all`, `count` and `remove_by_key_pattern` is now a glob on every adapter; the memory cache used to compile it as a Python regular expression while Redis read it as a glob. (#1393)
- [Cache] **Breaking (memory cache).** A `key_pattern` that leaned on regular-expression behaviour selects differently now: `.` is a literal dot, and anchors and character-class escapes are gone. Rewrite such patterns as globs. (#1393)
- [Cache] `Cache.get_all` is now the private, unpaginated `Cache._get_all`: it returns matching entries in key order up to a fixed cap of 1000 and no longer takes `last_position` or `size`. (#1401)
- [Fields] **Breaking.** String and Text fields no longer sanitize by default: pass `sanitize=True` on a field rendered as HTML without output encoding, or set `[field_defaults] sanitize` for a whole domain. (#1455)
- [Docs] The schema-evolution guides now point at the snapshot caveat: upcasters run on replayed events, not on snapshots. (#1526)
- [CLI] `protean schema render --indexes` now rejects an unknown `--dialects` value instead of quietly rendering it with the SQLite dialect. The accepted values are `postgresql`, `sqlite`, `mssql`, `mysql` and `mariadb`. (#1580)
- [Event store] The `reserved` option now also covers the generated `add_<name>` and `remove_<name>` helpers of a removed association: during replay the call does nothing instead of raising `AttributeError`. (#1592)
- [Database] The MySQL and MSSQL providers now check for their driver at `domain.init()`, raising a `ConfigurationError` that names the database, the driver and the extra to install. (#1593)
- [Testing] **Breaking (test mode only).** `Engine(test_mode=True).run()` and `protean server --test-mode` now stop as soon as every subscription has run out of work, instead of always running eleven 0.1-second cycles. (#1617)
- [Scaffold] Projects generated by `protean new` now set up their test domain with `DomainFixture`, so each test runs in its own domain context and every database, broker and event store is reset after each test. (#1633)
- [Handlers] **Breaking.** `domain.init()` now rejects a `sequential_by` value that is not a non-empty field name on an event handler, command handler or projector; the boolean form is for process managers. (#1649)
- [IR] **Breaking.** Domain traversal now loads modules in a fixed order, the root directory's files first then each subdirectory by name, where it used the order `os.listdir` returned. (#1664)
- [Check] `protean check --domain=<file>` no longer crashes with a `FileNotFoundError` on a file that declares `Domain(__name__)`, and a module that raises during traversal now ends the command with a one-line error instead of a traceback. (#1685)
- [Check] **Breaking.** A failure to build the IR is now an error in the `Domain.check()` result, with status `fail` and `protean check` exiting 1, in place of a logged traceback beside a `pass`. (#1685)
- [Server] With priority lanes on and the Redis broker, an idle stream subscription now waits on the primary and the backfill stream in one read, through a new broker `read_blocking_streams` method. (#1687)
- [Database] **Breaking (driver).** The PostgreSQL provider defaults to psycopg 3: `protean[postgresql]` installs `psycopg[binary]`, and the new `protean[postgresql-psycopg2]` extra installs `psycopg2-binary`. (#1689)
- [Database] The memory provider's `raw()` raises `DatabaseError` for a malformed query, where it raised a bare `Exception`, and some error logs no longer repeat the exception text the traceback already shows. (#1714)
- [Internals] **Breaking.** Internal paths that caught every exception now catch only the errors they expect, so any other error reaches the caller or the next handler up. Ruff's `BLE001` now checks `src/` and `specs/` without per-file exceptions. (#1715)
- [Internals] **Breaking.** Paths that expect one kind of failure now handle only that failure, including no active domain context, a `[logging]` value that is not a table, and a closed health-check socket. (#1716)
- [Internals] **Breaking.** An element given a non-dict positional argument now raises `TypeError` instead of `AssertionError`, and a field's `renamed_from` given a value that is not a string, list or tuple raises `TypeError` instead of `ValueError`. (#1717)
- [IR] **Breaking.** The IR now records a `Decimal` field as `"type": "Decimal"` with its `precision` and `scale`, where it recorded `String` and dropped both. The schema moved to `0.3.0`, so a committed baseline reports a version mismatch until you regenerate it. (#1723)
- [Broker] **Breaking.** The Redis broker's `dlq_inspect()`, `dlq_replay()`, `dlq_replay_all()`, `dlq_purge()` and `dlq_depth()` no longer treat every Redis `ResponseError` as an empty DLQ; anything other than a missing stream or a malformed `dlq_id` reaches the caller. (#1730)
- [Observability] **Breaking.** A domain with no environment variable set (`PROTEAN_ENV`, `ENV` and `ENVIRONMENT` all unset) now logs at INFO with colored console output instead of DEBUG; only an explicit `development` value selects DEBUG. (#1747)
- [IR] **Breaking.** `diff_ir()` now applies the compatibility report's field rules to published events, so a field that changes type, or a required field added without a default, is listed as a contract break. (#1781)
- [CLI] Runtime messages no longer contain em-dashes, across `protean check` diagnostics, `protean dx`, `protean ir`, git-hook output, CLI table titles and some exception and log messages. A script matching the exact text of one of these needs the new wording. (#1863)
- [Event store] **Breaking (synchronous processing).** Under `event_processing = "sync"`, an `ExpectedVersionError` from an event handler now reaches the caller as a `TransactionError`, instead of triggering the command handler's version retry and saving its writes twice. (#1883)

### Deprecated

- [Database] Deprecated the patch-and-persist API: `DAO.update()` and `QuerySet.update()` now emit a `RemovedInProtean020Warning` and are removed in 0.20.0. Load the aggregate, call a behaviour method, and persist with `repository.add()`. (#1260)
- [Server] Deprecated the `debug` argument on `Supervisor` and `Reloader`, removed in 0.20.0; pass `log_level="DEBUG"` instead. Both classes also take `log_format` and `log_config`. (#1639)
- [Handlers] Deprecated a `sequential_by` value on a process manager that is not a boolean: `domain.init()` now emits a `RemovedInProtean020Warning` and stores it as a boolean, and the value raises in 0.20.0. (#1787)
- [Internals] Twelve deprecations that said they would be removed in 1.0.0 now name a planned release, with new `RemovedInProtean019Warning` and `RemovedInProtean020Warning` classes, and `protean check` reports the new versions. (#1868)

### Removed

- [Scaffold] Removed the `logging.toml` that `protean new` generated at the project root. Nothing in the framework read it; `[logging]` in `domain.toml` is the one config Protean loads. (#1320)
- [Database] **Breaking.** Removed the `database_model` option from `@domain.aggregate`, `@domain.entity` and `@domain.projection`, and from `domain.register()`; it never had any effect. Register a custom model with `@domain.database_model(part_of=<Element>)` instead. (#1607)
- [Testing] **Breaking.** Removed `protean.testing.assert_valid` and `assert_invalid`, deprecated since 0.16.1, along with the `RemovedInProtean018Warning` class. Use `pytest.raises(ValidationError, match=...)` in place of `assert_invalid`. (#1622)

### Fixed

- [Scaffold] Fixed the generated example project failing `domain.init()` and `protean check`: the scaffold shipped package re-exports that broke traversal, a missing-module import, an aggregate referenced by name instead of class, and no identifier field. (#1316)
- [Scaffold] Fixed the scaffold's `.env.example`, `README.md` and `docker-compose*.yml` setting the unread `LOG_LEVEL`/`LOG_FORMAT` instead of `PROTEAN_LOG_LEVEL`, so the documented env override never took effect. (#1320)
- [CLI] Fixed the `protean` CLI failing to start on a core-only install with `ModuleNotFoundError: No module named 'click'`; the `observatory` command's import is now lazy. (#1465)
- [CLI] **Breaking.** `protean new .` and `protean new ..` now raise `ValueError`. Both passed validation before and produced a project that could not be installed. (#1466)
- [Database] Fixed a standalone SQLAlchemy update that lost the version race raising a raw `StaleDataError`; it now surfaces as `ExpectedVersionError`, the error the UnitOfWork path already raises. (#1382)
- [Event store] Fixed loading an event-sourced aggregate failing when its snapshot predates the current schema; the snapshot is discarded, the aggregate is rebuilt from its event stream, and a warning is logged on `protean.snapshot`. (#1362)
- [Event store] Fixed `read("$all")` and `read_all("$all")` raising `TypeError` when the store holds snapshots; both readers now skip snapshot rows and yield events and commands only. (#1437)
- [Event store] Fixed the in-memory store's `_read_last_message` returning a stale record once a stream passed 1,000 rows; it now does a true descending tail read. (#1529)
- [Event store] Fixed async command handling reporting a succeeded command as failed: an unguarded `issubclass` check raised on a command stream's `CommandDispatcher`, and the swallowed error turned a committed command into a failed result. (#1365)
- [Server] Fixed `Engine` leaking the event loop it opens when construction then fails while wiring subscriptions, outbox processors or the DLQ task. (#1365)
- [Event store] Fixed `protean eventstore dlq inspect` showing an unrelated event when the message an exhausted position names is no longer in the store; `inspect` and `replay` now check the message against the record's global position. (#1365)
- [Event store] Fixed DLQ discovery skipping process managers, whose exhausted positions were invisible to `protean eventstore dlq` and whose DLQ stream was never trimmed. (#1365)
- [Types] Fixed field declarations under `mypy --strict`: `ValueObject` takes any class as its target, a required `ValueObject` or `Reference` resolves to `X` instead of `X | None`, and the annotation-only form no longer reports `valid-type` or `call-arg`. (#1495)
- [Types] Fixed the mypy plugin not building a keyword `__init__` for `@domain.query` classes, so `GetLeaderboard(account_id="a1")` type-checks and an unknown keyword is still an error. (#1873)
- [Types] Fixed `@domain.upcaster` inferring `type[Never]`: it now has overloads for the bare and the called form, and every element decorator's class-taking overload accepts options. (#1875)
- [Types] Fixed `@handle` rejecting a string target under mypy, so `"$any"` and event type strings type-check and the decorated method keeps its message and result types. (#1876)
- [Types] Fixed `HasMany`, `HasOne`, `Reference` and `ValueObject` fields declared in the typed-annotation style not behaving like the assignment style. (#1877)
- [Types] Fixed a `dict[...]` annotation inside a decorated element resolving `dict` to pydantic's `BaseModel.dict` method under the mypy plugin. (#1878)
- [Types] Fixed `QuerySet` chain methods not returning `Self`, so `view_for(X).query.filter(...)` stays a `ReadOnlyQuerySet` for type checkers. (#1879)
- [Types] Fixed `BaseAggregate._create_new()` and `from_events()` not returning `Self`, and made `ReadView` generic in its projection, so `domain.view_for(ProductCard).get(...)` returns `ProductCard`. (#1882)
- [Docs] Fixed code blocks that showed the wrong lines or did not parse, and examples that no longer ran. (#1690, #1691)
- [Docs] Fixed the examples in the domain definition guide and the fields and domain element reference. The fields pages no longer warn that `default=[]` shares one list across instances, because each instance gets its own copy. (#1692)
- [Docs] Fixed the examples in the change-state guides. (#1693)
- [Docs] Fixed the examples in the consume-state and compose-a-domain guides, evolving events, multi-domain applications, architecture fitness functions and the pathway pages. (#1694)
- [Docs] Fixed the examples in the Bookshelf and Fidelis tutorials, except Bookshelf chapter 13. (#1695)
- [Docs] Fixed the examples in Bookshelf chapter 13 and the domain services guide. (#1767)
- [Docs] Fixed the examples in the server, FastAPI and observability guides. (#1696)
- [Docs] Fixed the examples in the aggregate design pattern pages. (#1697)
- [Docs] Fixed the examples in the message handling reliability pattern pages. (#1698)
- [Docs] Fixed the examples in the adapter reference pages for brokers, caches, databases and the event store. (#1699)
- [Docs] Fixed the examples in the concepts pages. (#1700)
- [Docs] Fixed the examples in the domain behavior guides. (#1701)
- [Docs] Fixed the examples in the testing guide and the testing reference. (#1702)
- [Docs] Fixed the examples in the configuration, logging and server reference pages. (#1703)
- [Docs] Fixed the examples in the value and data modeling pattern pages. (#1704)
- [Docs] Fixed the examples in the application structure and testing pattern pages. (#1705)
- [Docs] Fixed the examples in the event design and integration pattern pages. (#1706)
- [Docs] Fixed the examples in the read side and operations pattern pages. (#1707)
- [Docs] Fixed the examples in the migration guides, the troubleshooting page, the remaining reference pages, and the projectors, process managers and entities guides. (#1708)
- [Docs] Fixed the remaining pages showing an event handler that changes its own aggregate from another aggregate's events. (#1743)
- [DX] Fixed the `domain-service` and `query-handler` skills' frontmatter not parsing, so Claude Code ignored them; their descriptions held an unquoted `: `. New tests parse every skill's frontmatter and run its fenced `python` blocks. (#1673)
- [DX] Fixed errors repeated across the teaching skills and the docs: every invariant example now raises `ValidationError({"<field>": ["<message>"]})`, imports come from `protean` instead of `protean.globals`, and queries go through `repo.find_by()` instead of the private `_dao`. (#1674)
- [DX] Fixed the aggregate, entity, value-object and add-field skills and their guides so every example meant to run now runs: decorator options only, keyword association helpers, `Identifier` in place of `Reference`, and `add()` in place of `save()`. (#1675)
- [DX] Fixed the event, command, add-event, add-command, add-use-case, event-sourced-aggregate and upcaster skills: commands catch `ValidationError`, events are raised from a factory classmethod, upcasters register with `@domain.upcaster`, and fact events go through `fact_events=True`. (#1676)
- [DX] Fixed the command-handler, event-handler, application-service, domain-service, add-domain-service-flow, repository and message-enrichment skills, so every non-fragment example runs and `check` finds no unexpected warning on their assets. (#1677)
- [DX] Fixed the skills, the pack rules and the event handlers guide teaching more than one way for one aggregate to react to another's event; the handler that listens on another cluster's stream now appears only as a mistake to avoid. (#1678)
- [DX] Fixed the projection, projector, query-handler, add-read-model, subscriber and process-manager skills and the projectors and process managers guides, so every example meant to run now runs. (#1679)
- [DX] Fixed the generate-test-scaffold, audit-domain, add-validation and refactor-extract-value-object skills, so every example meant to run now runs. (#1680)
- [DX] Rewrote the api-endpoint skill on `protean.integrations.fastapi`: one `create_app(domain)` factory, plain `def` endpoints so the blocking call runs in FastAPI's thread pool, and the status code and body for each exception the handlers map. (#1681)
- [DX] Fixed the add-saga-flow, add-subscriber-flow, custom-validator and query skills, so every example now runs without error. (#1764)
- [DX] Fixed the extract-bounded-context, refactor-introduce-events, refactor-move-logic-to-aggregate and split-aggregate skills, so every non-fragment example now runs, each page defining the names its "after" code uses. (#1765)
- [IR] **Breaking.** `protean ir diff` now reports the changes that stop an event-sourced aggregate being rebuilt from its events: turning event sourcing on or off, moving its `stream_category`, pointing its identity at another field, and dropping an `@apply` handler while its event survives. (#841)
- [Broker] **Breaking.** Reconciled the subscription and InlineBroker retry and DLQ layers so a subscription owns retry and dead-lettering end to end; the subscription's `{stream}:dlq` is now the single dead-letter destination for the streams it consumes. (#1265)
- [Cache] Fixed the memory cache's `remove`, `remove_by_key` and `set_ttl` raising `KeyError` on an absent key, where the Redis cache has always been silent, so the same call meant different things on each adapter. (#1391)
- [Cache] **Breaking (memory cache only).** Code that used the memory cache's `KeyError` as a presence check no longer takes its `except` branch, and the call succeeds quietly; nothing inside Protean relied on it. (#1391)
- [Cache] Fixed Redis' `remove_by_key_pattern` raising when a pattern matches no keys; it now skips the delete, matching the in-memory adapter's silent no-op. (#1399)
- [IR] Fixed `protean ir diff` downgrading an event's breaking changes to safe on upcaster coverage it has not earned; a bump is covered only when every version still in the event store reaches the new one. (#1572)
- [Database] Fixed `@domain.repository(database="mssql")` and `database="mysql"` being rejected, because the validating `Database` enum listed only elasticsearch, memory, postgresql and sqlite. (#1580)
- [Database] **Breaking.** A `RawIndex` that names a dialect the framework renders no index DDL for now raises `IncorrectUsageError` at `Domain.init()`, where it was accepted and then silently dropped at every call site. (#1585)
- [Database] `protean schema render --indexes --dialects=<name>` now rejects a dialect outside the set the framework renders, where `--dialects=oracle` used to write a file of SQLite DDL. (#1585)
- [Database] An element with `identity_type = "integer"` now builds its model on the SQLAlchemy providers, where it raised `TypeError: Integer() takes no arguments`. (#1586)
- [Database] **Breaking.** An integer identity under the `uuid` strategy is now refused at `Domain.init()`, since no SQL integer column holds a 128-bit number. (#1586)
- [Docs] Fixed four pages naming `NotImplementedError` as the exception an event-sourced aggregate raises when an event has no `@apply` handler; it is `IncorrectUsageError`. (#1589)
- [DX] Fixed three pack examples declaring a value object and never using it; the event-sourced order, the add-field customer and the test-scaffold order now embed `Money` and `ContactInfo`. (#1591)
- [DX] Fixed the projector skill catching the wrong exceptions for a missing projection record, the bare `Exception` in one snippet and a non-existent `NotFoundError` in the other; both now catch `ObjectNotFoundError`. (#1602)
- [DX] Fixed the add-field and add-validation skills not saying that `sanitize` is off by default for `String` and `Text` fields, and not describing what sanitizing does. (#1603)
- [DX] Fixed the custom-validator skill not saying that a field's validators run in list order and stop at the first failure, and that empty values skip them. (#1604)
- [DX] Fixed the value-object skill's seven example files not running as their `Usage:` line says; they imported from a package that does not exist, and six never set up their domain. (#1605)
- [DX] Fixed three dead links in the value-object and add-field skills, one a docs URL that returned 404 and one a relative path that led nowhere. (#1606)
- [Event store] Fixed `raise_()` on an event-sourced aggregate keeping an event when its `@apply` handler, an invariant check or an enricher raises; the pending events, `_version` and `_event_position` go back to their values from before the call. (#1612)
- [CLI] Fixed `protean test test-adapter` running the CORE suite first; it now starts its conformance run right away. (#1615)
- [Fields] Fixed a value object, command or event that declares a nested value object in assignment style writing that field onto `BaseValueObject`, `BaseCommand` or `BaseEvent`, so every element defined afterwards gained it. (#1617)
- [Testing] Fixed `Engine(test_mode=True).run()` and `protean server --test-mode` stopping while a subscription was backing off after an error. (#1620)
- [Event store] Fixed a stale write on an event-sourced aggregate with the outbox on failing with an outbox `ValidationError` or `IntegrityError` instead of `ExpectedVersionError`; the unit of work now appends to the event store before it saves the outbox rows. (#1628)
- [Check] Fixed top-level `[lint]` and `[observatory]` tables being silently dropped from `domain.toml`, from `[tool.protean]` in `pyproject.toml` and from a `Domain(config=...)` dict, because the config loader kept only the sections listed in its defaults. (#1629)
- [Check] **Breaking.** `[lint]` settings now apply, so `protean check` can start failing on a project that used to pass, and a malformed `[lint]` value fails `check` and `verify` instead of being ignored. (#1629)
- [Internals] Fixed the deprecation warnings for `is_event_sourced=`, the `published` command option and email element registration pointing at Protean's own registration code instead of the line in your code. (#1630)
- [Testing] Fixed `DomainFixture.domain_context()` resetting whichever domain was current at exit rather than its own, so a test that left another domain's context pushed wiped that other domain. (#1634)
- [Observability] **Breaking.** Single-worker `protean server` and `protean observatory` now apply the `[logging]` section of `domain.toml`; they used to set up console logging before the domain loaded, which made `Domain.init()` skip its own setup. (#1635)
- [Observability] Fixed log records from child loggers reaching the root logger's handlers without `correlation_id` and `causation_id`, and without `[logging].redact` masking; Protean's filters now attach to the root handlers too. (#1636)
- [Observability] Fixed `--log-level`, `--log-format` and `--log-config` not reaching the worker processes of `protean server --workers N` and `--reload`. (#1639)
- [Event store] Fixed `protean outbox reconcile` and the server's startup reconcile creating outbox rows for messages the domain never outboxes, then publishing them; it now repairs only events raised by this domain's aggregates on the reconciled provider. (#1648)
- [Docs] Fixed the `protean upgrade-check` reference and the 0.17 migration guide not stating what the Unit of Work source checks cover: explicit `with UnitOfWork()` blocks only, not the one `@handle` and `@use_case` methods run in. (#1652)
- [Event store] Fixed outbox reconciliation restoring only the internal-broker row of a `published` event, so the event never reached the brokers in `[outbox].external_brokers`. (#1653)
- [Observability] Fixed multi-worker and `--reload` workers logging at INFO until their domain loaded, so `PROTEAN_LOG_LEVEL=DEBUG` lost the DEBUG lines written during the load. (#1658)
- [Broker] Fixed an idle subscription with priority lanes on and the Redis Streams broker logging `broker.redis.read_blocking_failed` every 5 seconds and holding up its backfill lane; its non-blocking check sent `BLOCK 0`, which means wait forever. (#1660)
- [Broker] **Breaking.** On the Redis broker, `read_blocking(timeout_ms=0)` now returns at once where it waited until a message arrived, and `blocking_timeout_ms` must be positive, with `0` raising `ConfigurationError` at startup. (#1660)
- [CLI] Fixed `protean verify` taking its test counts from the first `<N> passed` or `<N> failed` text anywhere in pytest's output, so a message such as `port 15432 failed` could replace the real counts. (#1661)
- [Fields] Fixed an aggregate whose `@invariant.pre` rejects its current state failing to save when it has an `auto_now` field or a registered enricher; those save-time writes no longer run the pre-invariants. (#1663)
- [Observability] Fixed the stdlib redaction filter running before Protean's correlation and trace-context filters, so listing `correlation_id` or `trace_id` in `[logging].redact` left those record attributes unmasked for other formatters. (#1666)
- [Internals] **Breaking.** A `ValueError` raised while a unit of work commits is no longer reported as a version conflict; it raises `TransactionError` with the `ValueError` as its `__cause__`, so a handler's version retry no longer runs the handler again for it. (#1682)
- [Check] Fixed `AGGREGATE_TOO_LARGE` saying it counts fields when it counts the entities in a cluster, and `COMMAND_NOT_IMPERATIVE` reporting ordinary commands such as `CloseTicket` and `MakeDeposit`. (#1683)
- [Fields] Fixed building an element from only some of a value object's flattened arguments: Protean filled every missing argument with `None`, so `Customer(billing_address_street="1 Main St")` failed when `Address` had a field that does not accept it. (#1686)
- [Fields] **Breaking.** A value object field that accepts `None` but defaults to something else, such as `city: str | None = "Unknown"`, now gets its default when its flattened argument is left out. Pass `None` to keep the old value. (#1686)
- [Observability] Fixed the observatory failing a trace endpoint or stopping the live trace stream on a malformed trace entry; it now skips the entry and keeps reading, and a `duration_ms` that is infinite or NaN is left out of the latency figures instead of answering 500. (#1715)
- [Internals] Fixed some server, observatory, subscription and retry paths dropping errors without a trace; they now log them, at debug level for a skipped scrape and at warning for a failed cleanup, an invalid `server.version_retry` or an IR build that fails inside `Domain.check()`. (#1716)
- [DX] Fixed the persistence and handler rules telling agents to use `self.repository`, which handlers do not have; their examples now get a repository with `current_domain.repository_for(...)`. (#1736)
- [DX] Fixed the add-validation skill storing money as `Float`, so an order with subtotals of 0.1 and 0.2 and a total of 0.3 failed its own invariant; money fields are now `Decimal(precision=19, scale=4)`. (#1737)
- [Event store] **Breaking.** Saving the same aggregate instance again in a later transaction, without reloading it, now writes a new version. Before, the second save reused the version the instance already had, so handlers that deduplicate by event id dropped the second event. (#1744)
- [Event store] After a commit, `_version` and `_next_version` on each saved instance match what a reload returns, and after a rollback each instance gets back the version it had before the transaction. (#1744)
- [Internals] Inside a `UnitOfWork`, reading an aggregate the transaction has already loaded or saved returns that same instance with its later changes, where each read used to build a new copy and lose events raised on an earlier one. (#1744)
- [Event store] Event-sourced aggregates track their versions from their own events, so the version changes in this release do not apply to them. (#1744)
- [Event store] A fact event no longer moves the position of the aggregate's own event stream, so saving an aggregate with `fact_events=True` a second time no longer raises `ExpectedVersionError`. (#1744)
- [Fields] Fixed a failed post-invariant leaving the change that broke it in place; the field keeps its previous value and the entity's changed flag goes back, across every field kind and `add_` or `remove_` call. (#1746)
- [Fields] A failed check at the end of an `atomic_change` block now undoes every change made inside the block. (#1746)
- [Docs] Fixed the FastAPI lifespan recipes not calling `domain.close()` in a `finally` block, so provider, broker, cache and event store connections leaked when the app exited through an exception. (#1777)
- [IR] Fixed `domain.to_ir()` failing with a `TypeError` when a field declares a `decimal.Decimal` `min_value` or `max_value`; a decimal bound on a `Decimal` field now goes into the IR as a decimal string. (#1780)
- [IR] Fixed the v0.3.0 schema leaving `sequential_by` undeclared, so a validator that refuses undeclared keys rejected any IR that set it. (#1787)
- [Event store] Fixed an event or command rebuilt from a stored message taking the handled message's `correlation_id` or `causation_id` when its own stored value was empty. (#1789)
- [Database] **Breaking.** A field declared with `choices` now gets the column type its choice values share, so an `Integer` with `choices` loads back as an `int` and a `String` with string choices keeps its `max_length` instead of becoming `TEXT` on MySQL. (#1791)
- [Observability] Fixed each worker's queue handler under `--workers N` masking only the first redaction filter on the root logger, so keys from a second `configure_logging()` call left the worker unmasked. (#1803)
- [Internals] Fixed a possible segmentation fault at shutdown on Python 3.11 for a process that held stored messages until exit; datetimes Protean parses now carry a `datetime.timezone` instead of pydantic-core's own `TzInfo`. (#1806)
- [Event store] Fixed an event or command rebuilt from a stored message losing its stored `origin_stream` and taking the handled message's instead. (#1812)
- [Database] Fixed a QuerySet evaluated in one `UnitOfWork` handing out cached copies when read in a different transaction; it now runs its query again, so events raised on a copy are no longer lost. (#1842)
- [Cache] Fixed `RedisCache.flush_all()` sending `FLUSHALL`, which emptied every database on the server; it now sends `FLUSHDB`. (#1880)
- [Server] Fixed the multi-worker Supervisor killing a worker mid-drain; its shutdown budget is now the drain window plus 5 seconds, never less than 30. It also finds the project config for a dotted `--domain`. (#1896)
- [Fields] **Breaking.** A value object's string `part_of` now resolves to the aggregate class at `domain.init()`, so `IRBuilder(domain).build()` no longer raises `AttributeError` for one that no `ValueObject` field embeds, and a `part_of` naming no aggregate is rejected. (#1897)
- [Server] Fixed the engine running outbox processors for every managed provider, including `memory` and providers that hold only projections, whose outboxes nothing writes to. (#1923)

### Security

- [Scaffold] **Breaking, symlinked targets only.** `protean new` refuses a target directory that resolves outside the output directory. A symlinked `<output-dir>/<name>` used to be followed, so `--force` cleared files at the link target and the render wrote them there. (#1466)

## [0.17.1] - 2026-08-12

### Upgrade Notes

Read the [0.17 migration guide](https://docs.proteanhq.com/reference/migration/v0-17/) before you upgrade. These changes can need action:

- [A failing handler method no longer stops its siblings](https://docs.proteanhq.com/reference/migration/v0-17/#a-failing-handler-method-no-longer-stops-its-siblings) (#1406)
- [Sibling handler classes are independent in failure under synchronous dispatch](https://docs.proteanhq.com/reference/migration/v0-17/#sibling-handler-classes-are-independent-in-failure-under-synchronous-dispatch) (#1411)

### Added

- [Handlers] A handler method that reaches no repository now carries a stated guarantee that it opens no transaction and holds no pooled connection, so a call to an external system can sit in its own method. (#1407)

### Fixed

- [Handlers] **Breaking (event handlers and projectors).** A failing `@handle` method no longer stops its sibling methods from running, and when more than one fails the failures are raised together as an `ExceptionGroup`. (#1406)
- [Handlers] **Breaking (synchronous dispatch).** Under `event_processing = "sync"`, a failing event handler class no longer aborts the drain or discards the classes queued behind it, and the failures surface once the drain finishes. (#1411)

## [0.17.0] - 2026-08-04

### Upgrade Notes

Read the [0.17 migration guide](https://docs.proteanhq.com/reference/migration/v0-17/) before you upgrade. These changes can need action:

<details markdown="1">
<summary>14 breaking changes</summary>

- [The Unit of Work is a real transaction](https://docs.proteanhq.com/reference/migration/v0-17/#the-unit-of-work-is-a-real-transaction) (#1256)
- [`event_sourced` replaces `is_event_sourced`](https://docs.proteanhq.com/reference/migration/v0-17/#event_sourced-replaces-is_event_sourced) (#1107)
- [`is_fact_event` is now framework-internal](https://docs.proteanhq.com/reference/migration/v0-17/#is_fact_event-is-now-framework-internal) (#1107)
- [Email subsystem deprecation](https://docs.proteanhq.com/reference/migration/v0-17/#email-subsystem-deprecation) (#1115)
- [`identity_type = "uuid"` yields a string](https://docs.proteanhq.com/reference/migration/v0-17/#identity_type-uuid-yields-a-string) (#1235)
- [Data that used to fit may now be rejected](https://docs.proteanhq.com/reference/migration/v0-17/#data-that-used-to-fit-may-now-be-rejected) (#1253)
- [Streams are trimmed by default, and trimming can drop unread messages](https://docs.proteanhq.com/reference/migration/v0-17/#streams-are-trimmed-by-default-and-trimming-can-drop-unread-messages) (#1301)
- [`/readyz` reports an object where it reported a number](https://docs.proteanhq.com/reference/migration/v0-17/#readyz-reports-an-object-where-it-reported-a-number) (#832, #1288)
- [`update()` now goes through the same path as `save()`](https://docs.proteanhq.com/reference/migration/v0-17/#update-now-goes-through-the-same-path-as-save) (#1255)
- [Config that was silently ignored now stops start-up](https://docs.proteanhq.com/reference/migration/v0-17/#config-that-was-silently-ignored-now-stops-start-up) (#1299)
- [`protean check` reports more, so CI may go red](https://docs.proteanhq.com/reference/migration/v0-17/#protean-check-reports-more-so-ci-may-go-red) (#956)
- [`cache.get_ttl()` returns seconds on Redis, not milliseconds](https://docs.proteanhq.com/reference/migration/v0-17/#cacheget_ttl-returns-seconds-on-redis-not-milliseconds) (#1307)
- [Application services accept constructor arguments](https://docs.proteanhq.com/reference/migration/v0-17/#application-services-accept-constructor-arguments) (#1293)
- [Smaller changes worth knowing](https://docs.proteanhq.com/reference/migration/v0-17/#smaller-changes-worth-knowing) (#1089, #1104, #1159)

</details>

### Added

- [Fields] Fields accept `renamed_from=`, so a payload written under the old key deserializes into the renamed field without an upcaster and `protean ir diff` reports a safe `field_renamed` change. (#1139)
- [Events] Events accept `superseded_by` naming their replacement, and raising a deprecated event emits a `ProteanDeprecationWarning` once per event type. (#1133)
- [Events] Added opt-in lenient deserialization through the `lenient_deserialization` config key or a per-event `lenient` option, which drops fields no longer on the class instead of raising `DeserializationError`. (#1134)
- [Check] Added `UPCASTER_GAP`, which flags at build time an event whose `__version__` is above 1 with no upcaster path from an earlier version, instead of failing at read time. (#1131)
- [IR] The compatibility checker is now evolution-aware: deprecation grace applies to every persisted element, and a version bump covered by a registered upcaster chain is downgraded from breaking to safe. (#1132)
- [CLI] `protean schema generate` now emits Avro and Protobuf schemas alongside JSON Schema, through `--format avro|protobuf|json`. (#1137)
- [CLI] Added `protean events catalog`, which lists every concrete event with its version, deprecation status, upcaster chain and consumers, as a table or `--json`. (#1135)
- [IR] `protean ir diff` now reports an Avro-style compatibility verdict (`BACKWARD`, `FORWARD`, `FULL` or `NONE`) alongside its breaking classification, in text and JSON. (#1138)
- [Docs] Added an [Evolving events over time](docs/guides/evolving-events.md) guide walking the full v1 to vN workflow on one running example. (#1136)
- [Check] `protean check` diagnostics now carry a `category`, a `rule` with a rationale and a fix, and a `suggestion`, plus a per-element `suppress_checks` option and a `[lint.suppressions]` allow-list. (#774)
- [Check] Added four aggregate and value-object fitness functions: `CROSS_AGGREGATE_REFERENCE`, `ES_AGGREGATE_NO_EVENTS`, `VALUE_OBJECT_MUTABLE_FIELD` and `AGGREGATE_NO_INVARIANTS`. (#775)
- [Check] Added two bounded-context fitness functions: `CIRCULAR_CLUSTER_DEPENDENCY`, and `INFRA_IMPORT_IN_DOMAIN` behind `[lint].check_infra_imports`. (#776)
- [Check] Added five handler-completeness diagnostics: `QUERY_HANDLER_WITHOUT_QUERY`, `PROJECTOR_HANDLES_ORPHANED_EVENT`, `COMMAND_HANDLER_CROSS_CLUSTER`, `SUBSCRIBER_NO_STREAMS` and `PROCESS_MANAGER_UNCLOSED`. (#777)
- [Check] Added three info-level naming-convention diagnostics: `EVENT_NOT_PAST_TENSE`, `COMMAND_NOT_IMPERATIVE` and `AGGREGATE_NOT_NOUN`. (#778)
- [CLI] `protean check` gains `--format sarif` and `--format github-annotations`, so findings reach GitHub Code Scanning and pull-request annotations. (#779)
- [Docs] Documented the architecture fitness functions: a guide, a [Fitness Function Catalog](https://docs.proteanhq.com/reference/fitness-functions/) with every rule's rationale and fix, and a `protean check` CLI reference. (#780)
- [Check] Added `EVENT_HANDLER_FOREIGN_EVENT`, which flags an event handler whose `part_of` cluster differs from the cluster that owns an event it handles. (#824)
- [Server] Custom subscription profiles can now be defined under `[server.profiles.<name>]`, optionally inheriting from a built-in profile with `inherits`. (#827)
- [Server] Added `retention_maxlen`, which bounds a subscription's broker stream so processed messages do not accumulate forever; trimming is approximate and off by default. (#828)
- [Server] Added a per-subscription circuit breaker: after `circuit_breaker_threshold` consecutive failures it pauses reads for `circuit_breaker_reset_seconds`, then allows one probe. (#829)
- [Server] Added the publishing side of `sequential_by` per-key sequential processing, which validates the key at registration and routes an outbox row to `{stream_category}:{key}` (ADR-0028). (#830)
- [Server] Added the consumer side of `sequential_by` on the Redis broker: a `PartitionedStreamSubscription` drains each key strictly in order under an ownership lease and a fencing token. (#831)
- [Docs] Added a [Tuning Subscriptions](https://docs.proteanhq.com/guides/server/tuning-subscriptions/) guide covering profiles, `retention_maxlen`, the circuit breaker, `sequential_by` and reading consumer lag. (#833)
- [Testing] Added a cross-adapter conformance suite for the query-API primitives, so each adapter is held to the same behaviour for the capabilities it declares (ADR-0023). (#950)
- [Check] Added `UNINDEXED_FILTER_PATH`, which flags a repository query filtering on an aggregate field that no declared index covers. (#955)
- [Check] **Breaking.** Added `UNBOUNDED_INDEXED_STRING`, which flags an indexed field that is a `Text` or a `String` declared with `max_length=None`, so a domain that already declares such an index newly reports a finding. (#956)
- [CI] CI now enforces the quality gates that previously only ran in pre-commit: `ruff check`, `ruff format --check` and a 94% project coverage floor, plus a `dependency-review` supply-chain check. (#998)
- [Internals] Deprecations now flow through one mechanism that cites a removal version and emits `ProteanDeprecationWarning`, so a test config can fail CI on deprecated usage wherever it is raised. (#999)
- [CI] `mypy` now runs against `src/protean` in CI, with pre-existing type debt held in a shrinking module quarantine (ADR-0018). (#1001)
- [Fields] Added a `Decimal` field for fixed-precision values such as money, with optional `precision` and `scale` mapping to `NUMERIC`, string-encoded in payloads so it never round-trips through a float. (#1038)
- [Event store] Added outbox reconciliation for the event-store crash window: `protean outbox reconcile` re-derives missing outbox rows, and the server runs the same sweep at startup (ADR-0015). (#1040)
- [Projections] Projectors can opt into consume-side idempotency with `@domain.projector(idempotent=True)`, which records a `(message_id, handler)` marker in the same transaction as the read-model write (ADR-0017). (#1042)
- [CLI] Added `protean ir show --canonical`, which omits the volatile `generated_at` timestamp so a committed `.protean/ir.json` baseline diffs only when the domain contract changes. (#1064)
- [Testing] Added `protean.testing.process_and_wait` and `protean.testing.drain`, so one test body works under both synchronous and asynchronous processing. (#1065)
- [CLI] Added `protean idempotency cleanup`, which prunes consume-side idempotency markers older than a retention window in bounded batches (ADR-0017). (#1068)
- [CLI] `protean upgrade-check` now diffs a live `outbox` table for the two intra-0.16 structural migrations, emitting the exact SQL for your dialect. (#1093)
- [Testing] Added mutation testing for the core: a `make mutation` target that mutates a module and reports the surviving mutants its fast unit tests do not notice. (#1097)
- [Testing] Added upcaster registration tests for non-positive `from_version` and `to_version`, and wired an `upcaster` mutation-testing target. (#1101)
- [Internals] Added `event_sourced` as the canonical aggregate option for event-sourcing mode, following the convention that boolean element options are bare predicates. (#1107)
- [CLI] `protean ir check` now reports a baseline built against a different IR schema version as a version mismatch (exit code 3) rather than a generic stale result. (#1114)
- [Docs] Added a [stable surface](https://docs.proteanhq.com/reference/stable-surface/) reference listing every public export as Stable, Provisional or Internal, kept in step with the shipped `__all__` by a test. (#1116)
- [Check] `protean check` now detects every active framework-API deprecation through a declarative registry, adding `DEPRECATED_CONFIG`, `DEPRECATED_IMPORT` and `DEPRECATED_FIELD`. (#1121)
- [Docs] Added a [Consistency & Delivery Guarantees](docs/reference/guarantees.md) reference stating the ordering, delivery, consistency and isolation each port and adapter promises. (#1200)
- [Testing] Added a property-based serialization round-trip suite pinning that `to_dict()` and `Type(**data)` are inverses across every serializable field type. (#1201)
- [Testing] Added an injectable `domain.clock` seam, so a stub clock assigned within a pushed context can freeze or advance time without monkeypatching `datetime`. (#1202)
- [Check] Added the opt-in `ADAPTER_CALL_IN_DOMAIN` rule, enabled with `[lint].check_adapter_calls`, which flags a domain element whose method body calls a concrete adapter. (#1225)
- [Fields] Added a typed value-object dictionary field: `Dict(value_type=ValueObject(SomeVO))` declares a string-keyed map of value objects persisted as one JSON column. (#1236)
- [Fields] `DateTime` and `Date` gain `auto_now_add` and `auto_now`, and domains gain a pre-persist hook, `@domain.aggregate_enricher`, for cross-cutting fields such as `updated_by`. (#1237)
- [Testing] Added a property-based correctness suite that machine-checks the replay, checkpoint and concurrent-write guarantees over randomized histories. (#1251)
- [Database] Added `Repository.get_or_none(identifier)`, which behaves like `get()` but returns `None` instead of raising `ObjectNotFoundError`. (#1279)
- [Docs] Added a migration note for the 0.17 transaction change: a Unit of Work is one real database transaction, so a nested one joins the outer and external I/O inside one holds locks. (#1291)
- [CLI] `protean upgrade-check` now reports `NESTED_UNIT_OF_WORK` and `IO_INSIDE_UNIT_OF_WORK` for the 0.17 transaction change; both are read-only and advisory. (#1292)
- [Docs] Documented the [broker partitioning contract](https://docs.proteanhq.com/reference/adapters/broker/partitioning/), and filled reference gaps including twelve decorator options a test now keeps in step with the code. (#1306)

### Changed

- [Packaging] Relicensed Protean from BSD 3-Clause to the Apache License 2.0, which adds an explicit patent grant and clean inbound-contribution terms; existing usage is unaffected.
- [Check] The `protean check` exit code now honours a `[lint].level` key (default `"warn"`); errors always exit `1` and a gating non-error finding exits `2`. (#774)
- [Server] **Breaking (response shape).** The engine's `/readyz` probe reports `checks.subscriptions` as an object carrying `total` and a `details` row per subscription, instead of a bare integer. (#832)
- [Types] The whole of `src/protean` now passes `mypy --strict` and `pyright` in standard mode, which also surfaced and fixed about 22 latent runtime bugs (ADR-0018). (#997)
- [Server] The engine health-check server now binds loopback by default instead of `0.0.0.0`, and a new `[server.health] port_auto_increment` option lets an engine walk up from a taken port. (#1014)
- [Internals] **Breaking (synchronous processing).** A nested `current_domain.process(cmd, asynchronous=False)` now returns before its downstream event cascade runs; the state once a chain settles is unchanged (ADR-0016). (#1048)
- [CI] Added a weekly `mirror-images` workflow that mirrors the service container images into the project's GHCR namespace, so CI does not pull them from Docker Hub. (#1053)
- [CLI] Consolidated CLI domain loading onto the shared `load_domain` helper, so the abort path and the init ordering stay identical across every subcommand. (#1058)
- [Docs] Clarified that `protean-check-staleness --fix` writes a canonical IR baseline, byte-identical to `protean ir show --canonical`. (#1080)
- [Testing] Strengthened the in-memory descending `order_by` test, which compared results with a bare expression and no assertion, so a broken `-` prefix would have passed. (#1100)
- [Internals] Unified the two `deprecated` option normalizers, so an invalid `deprecated` value passed to a field now raises `ConfigurationError` instead of `ValueError`. (#1106)
- [Docs] Wrote down the [versioning policy](https://docs.proteanhq.com/reference/versioning-policy/): code that runs warning-free on 1.N runs unmodified on 1.N+1, and a minor release may remove an already-deprecated API. (#1120)
- [Packaging] Dropped the standalone `elasticsearch-dsl` dependency and raised the `elasticsearch` floor to `>=8.18.0`, where the DSL layer is bundled as `elasticsearch.dsl`. (#1142)
- [Packaging] Raised minimum runtime versions for `typer`, `fastapi`, `uvicorn` and OpenTelemetry, and `TraceParent` now masks the W3C trace-flags byte so a `RANDOM_TRACE_ID` flag reads as sampled. (#1181)
- [Packaging] Lowered the `>=` floors on runtime dependencies to the oldest versions Protean actually supports, with a CI leg that resolves them on every run (ADR-0020). (#1227)
- [Database] **Breaking (behaviour).** `update()` and `QuerySet.update()` now persist through the same path as `save()`, so an update refreshes `auto_now` timestamps and runs pre-persist enrichers; pass `apply_hooks=False` to opt out. (#1255)
- [Cache] `repository_for()` on a cache-backed projection now names the working API (`domain.cache_for` to write, `domain.view_for` to read) instead of failing with `No provider configured with name 'None'`. (#1286)
- [Cache] **Breaking (Redis only).** `cache.get_ttl()` returns seconds on the Redis cache, where it returned milliseconds, matching the memory cache and every other TTL on the port. (#1307)

### Deprecated

- [Fields] The `Method` and `Nested` serializer fields, and the `pickled` argument on `List`, are deprecated and will be removed in v1.0.0. (#1105)
- [Internals] Deprecated the `is_event_sourced` aggregate option in favour of `event_sourced`; the alias still works but warns and surfaces a `DEPRECATED_OPTION` diagnostic. (#1107)
- [Internals] The `published` option on a command is deprecated and will be removed in v1.0.0, since commands are internal to the bounded context and the option had no effect. (#1108)
- [Internals] Tightened the `import *` boundary of `protean.exceptions`, `protean.utils.globals`, `protean.testing` and `protean.utils`, and deprecated six `protean.utils` plumbing helpers. (#1110)
- [Internals] The built-in email subsystem is deprecated and will be removed in v1.0.0; handle the domain event from your own notification service instead. (#1115)

### Removed

- [Internals] Removed `is_fact_event` from the user-facing event and command option surface, so passing it now raises `ConfigurationError`, while `meta_.is_fact_event` stays readable. (#1107)
- [CLI] Removed `protean generate docker-compose`, a no-op stub, and the deprecated `--debug` flag on `protean server` and `protean observatory`; use `--log-level DEBUG` or `PROTEAN_LOG_LEVEL`. (#1113)

### Fixed

- [CLI] `protean check --format sarif` now links to `docs.proteanhq.com` instead of the retired `docs.protean.io`, so rule links resolve in GitHub Code Scanning. (#780)
- [IR] Handler resilience options (`timeout`, `retries`, `backoff`, `retry_exceptions`) now appear in the IR under a `resilience` key, visible to `protean ir diff` and the Observatory. (#1015)
- [Database] Fixed Elasticsearch setup crashing with `KeyError` when the domain registers a cache-backed projection; table ownership is now decided by one `BaseProvider.owns()` gate. (#1037)
- [Event store] Fixed the event-store append happening outside the aggregate and outbox transaction, which left a crash window that could corrupt event-sourced replay (ADR-0015). (#1040)
- [Internals] Multi-step process managers now cascade to completion under `event_processing = "sync"`, because synchronous dispatch is now breadth-first (ADR-0016). (#1048)
- [Event store] Fixed `reconcile_outbox` being a permanent no-op on Message-DB, where `read_last_message("$all")` returned `None` for category streams and reconciliation short-circuited. (#1073)
- [Database] Fixed a silent lost update in the SQLAlchemy adapter: the version check was a non-atomic read-compare-write, so two concurrent transactions could both pass it and both write. (#1087)
- [Event store] A `$all` subscription no longer silently skips an event whose `global_position` commits out of order; it holds at the first gap and abandons one left unfilled past `gap_timeout_seconds`. (#1088)
- [Server] **Breaking.** `protean server --workers N` now refuses to start more than one worker when a handler resolves to an event-store subscription, which previously double-processed events silently. (#1089)
- [Event store] Fixed an event-sourced `repository.get()` not returning the in-flight aggregate cached in the current Unit of Work, because the identity map was indexed with a flat key. (#1099)
- [Handlers] **Breaking.** `@handle` on a `BaseQueryHandler` method now raises `IncorrectUsageError` at `domain.init()` naming `@read`, and `ReadView.count()` issues a flat `SELECT COUNT(*)`. (#1104)
- [Docs] Fixed the v0.15 migration guide's value-object list example, which showed `ValueObjectList(content_type=OrderItem)` with a raw class; the supported form is `List(content_type=ValueObject(OrderItem))`. (#1105)
- [Check] A malformed upcaster chain no longer crashes `protean check` with a raw traceback, because `@domain.upcaster` now registers through the standard element lifecycle. (#1109)
- [Scaffold] Fixed `protean new` writing event-store config under `[event_stores]`, a section the framework never reads, so generated MessageDB projects silently ran on the in-memory store. (#1111)
- [Docs] Corrected the read-side documentation, so the three levels of read access now read the same on the query-handler and projection guides. (#1112)
- [Events] **Breaking.** The `version=` option on `@domain.event` and `@domain.command` is now honoured for classes that explicitly subclass `BaseEvent` or `BaseCommand`, where it was silently ignored. (#1159)
- [Testing] The core test suite no longer leaks file descriptors, so `protean test` runs under the default 1024 open-file limit. (#1168)
- [Internals] The engine's shutdown task now keeps a strong reference so it cannot be garbage-collected mid-flight, and failure-handling exceptions now chain their original cause. (#1196)
- [Types] **Breaking.** `identity_type = "uuid"` now yields a UUID string on every path, where it produced a native `uuid.UUID` that broke `to_dict()`, payloads and API responses (ADR-0021). (#1235)
- [Database] Editing a field of a child entity now advances the owning aggregate root's version, so two concurrent edits of the same child conflict instead of one overwriting the other. (#1245)
- [Event store] Category and `$all` reads now page by `global_position` consistently across the memory and MessageDB adapters, where the memory adapter paged by the per-stream ordinal. (#1248)
- [Fields] **Breaking.** `String` and `Text` now enforce their length bounds on the sanitized value, and `choices` fields are no longer sanitized, so a stored value cannot fail its own re-validation (ADR-0026). (#1253)
- [Database] **Breaking.** Fixed a silent lost update on the `update()` and `QuerySet.update()` path, which bypassed the optimistic-concurrency check; `update()` on a not-loaded entity now raises `ObjectNotFoundError`. (#1255)
- [Database] **Breaking.** On PostgreSQL and MSSQL a Unit of Work now runs as one real database transaction instead of buffering writes under AUTOCOMMIT, so reads inside it see its own pending writes (ADR-0027). (#1256)
- [Event store] Fixed an asynchronous event-store subscription dropping a failed message, by recording the failure durably before the read cursor advances. (#1257)
- [Database] Fixed the in-memory adapter silently losing concurrent updates; its optimistic-locking commit is now a real compare-and-set against the live store. (#1258)
- [Broker] Fixed broker and stream subscriptions dropping a message when its dead-letter-queue publish failed; the ACK now happens only after the DLQ publish succeeds. (#1263)
- [Internals] The outbox processor no longer holds a Unit of Work open across the broker-publish await; it publishes first, then records the status in a short transaction. (#1268)
- [Observability] **Breaking (reported values).** Fixed three gaps in subscription status reporting, and `lag` is now `int | None`, reporting `null` where it used to fall back to the pending count. (#1288)
- [Internals] **Breaking (error type).** `@domain.application_service` now accepts constructor arguments, and a `@use_case` called with no active domain context raises `ConfigurationError` instead of `AttributeError`. (#1293)
- [Server] **Breaking.** Fixed config guards that tested a value's truthiness before its type, so a falsy wrong value was ignored; `server.priority_lanes = false` or a `TTL` of `0` now fails at start-up. (#1299)
- [Scaffold] Fixed `protean new` generating projects that could not start, because it wrote unquoted environment substitutions, which is not valid TOML, plus several keys no adapter reads. (#1300)
- [Server] **Breaking (a dormant setting goes live).** `retention_maxlen` now works under `[server.stream_subscription]`, where the resolver never read it, so a value set on 0.16 takes effect on 0.17. (#1301)
- [Docs] Type unions in documentation tables now render as `str | None`, where 32 rows showed a literal backslash. (#1308)
- [Scaffold] Fixed four release-blocking issues: the generated Makefile called a removed CLI group, the generated README named undefined make targets, the version bump rewrote a `typer` pin, and the README linked to a missing contributing index. (#1309)

## [0.16.3] - 2026-07-15

### Changed

- [Testing] Added Redis broker DLQ tests (`dlq_list`, `dlq_inspect`, `dlq_replay`, `dlq_replay_all`, `dlq_purge`, `dlq_trim`, `dlq_depth`) against a real Redis, backfilling coverage for the `_client` accessor refactor. (#1090)

### Fixed

- [Database] Fixed foreign-key violations when saving an aggregate with `HasMany` or `HasOne` children in one `repository.add` inside a `UnitOfWork`; the parent row is now flushed into the transaction before its children are written. (#1043)
- [Database] A child-bearing aggregate save now emits its SQL at flush time rather than only at commit, so a constraint violation on such a save can surface at `add()` instead of `commit()`. (#1043)
- [Broker] The Redis Streams broker now reconnects when its connection was closed before a later operation runs, instead of raising `AttributeError` and killing a subscription's poll loop. (#1055)
- [Broker] Fixed a second `domain.init()` in a live process closing the running brokers out from under the Engine, which halted message consumption; a broker whose configuration is unchanged is now reused in place. (#1213)

## [0.16.2] - 2026-07-05

### Upgrade Notes

Read the [0.16 migration guide](https://docs.proteanhq.com/reference/migration/v0-16/) before you upgrade. This change can need action:

- [Outbox `target_broker` becomes NOT NULL](https://docs.proteanhq.com/reference/migration/v0-16/#outbox-target_broker-becomes-not-null) (#1041)

### Fixed

- [Database] Fixed `datetime` values in serialized payloads being encoded with `str()` instead of ISO-8601 on the JSON-backed stores (event store, Elasticsearch, outbox); records written before the fix stay readable. (#1039)
- [Fields] Fixed a `Date` field on a command or event raising `TypeError: Object of type date is not JSON serializable` when the message is processed; a plain `date` now serializes to ISO-8601. (#1046)
- [Database] Fixed `repository.add()` leaving an `Auto(increment=True)` identity as `None` on a store that assigns the value during create, such as the in-memory provider. (#1056)
- [Database] Fixed a database-assigned `Auto(increment=True)` identifier not reaching the aggregate through a relational adapter; the generated primary key now populates the instance after `add()`, including inside an outer `UnitOfWork`. (#1059)
- [Database] Reflecting a database-assigned identifier forces the insert to flush early, so a constraint violation on such an insert can surface at `add()` or `create()` rather than only at commit. (#1059)
- [Fields] Fixed an embedded `ValueObject` whose fields all hold falsy values being reconstructed as `None` after a save and reload; presence is now decided by identity rather than truthiness. (#1078)
- [Fields] `bool(vo)` still reports an all-default value object as falsy, so test presence with `agg.vo_field is not None`; a value object whose every field is `None` still reads back as `None`. (#1078)
- [Database] `Index(unique=True)` is now enforced in the in-memory repository: a save that violates a single-column or composite unique index raises `ValidationError`, with NULLs treated as distinct. (#1071)
- [Database] **Breaking.** `Outbox.target_broker` is now NOT NULL, closing the hole where a NULL row bypassed the `(message_id, target_broker)` unique index and reopened the duplicate-publish window. (#1041)
- [CLI] `protean upgrade-check` now diffs a live outbox table for a nullable `target_broker` and a legacy `message_id`-only unique index, alongside the VARCHAR-bounds check it already ran. (#1093)
- [Projections] Fixed projectors rejecting the `retries`, `backoff` and `retry_exceptions` options with `Unknown option(s)`; projectors now accept them, as event and command handlers do. (#1076)
- [Check] Fixed `protean check` raising a `PROJECTION_WITHOUT_PROJECTOR` false positive for a projection populated by a subscriber or event handler; declare it with `@domain.projection(externally_populated=True)`. (#1013)

## [0.16.1] - 2026-06-30

### Upgrade Notes

Read the [0.16 migration guide](https://docs.proteanhq.com/reference/migration/v0-16/) before you upgrade. This change can need action:

- [Outbox unique index becomes composite](https://docs.proteanhq.com/reference/migration/v0-16/#outbox-unique-index-becomes-composite) (#1009)

### Added

- [Event store] Added `OutboxRepository.find_all_by_message_id(message_id)`, which returns every outbox row sharing a `message_id`, and an optional `target_broker` argument on `find_by_message_id`. (#1009)

### Deprecated

- [Testing] Restored `assert_valid` and `assert_invalid` in `protean.testing` as deprecated shims; 0.16.0 removed them with no deprecation cycle, breaking downstream suites at import time. They go in v0.18.0. (#1011)

### Fixed

- [CLI] CLI commands no longer mix log lines into their machine-readable stdout: the console log handler writes to stderr, so the JSON from `protean ir show` and `protean schema show --raw` is safe to pipe. (#1010)
- [Event store] **Breaking.** The recommended unique index on the `Outbox` table is now composite over `(message_id, target_broker)`: an event is dual-written once per target broker, so an index on `message_id` alone rejected the framework's own write. (#1009)
- [IR] Fixed `protean ir check` reporting a domain as stale after an upgrade that only changes the IR schema version; the staleness checksum now covers domain content alone, matching what `ir diff` compares. (#1012)
- [IR] A baseline materialized before the staleness fix reports stale once; regenerate it with `protean ir show`. (#1012)
- [Handlers] Fixed `@handle("$any")` event handlers not firing under `event_processing="sync"`; wildcard handlers now run in synchronous dispatch, as they do under the async engine. (#1023)
- [Fields] Fixed per-field `validators=[...]` running against `None` on an optional field, so an unset field with a format validator raised a spurious error; empty values now short-circuit them. (#1025)
- [Event store] Fixed `domain.create_snapshots(Aggregate)` failing for an event-sourced aggregate declared with `fact_events=True`; it now skips the `{category}-fact-{id}` streams it mistook for real instances. (#1028)
- [Database] Fixed database setup failing for a domain that mixes a SQLAlchemy provider with a cache-backed projection; those projections are now skipped, since they persist to a cache rather than a table. (#1034)

## [0.16.0] - 2026-06-29

### Upgrade Notes

Read the [0.16 migration guide](https://docs.proteanhq.com/reference/migration/v0-16/) before you upgrade. These changes can need action:

- [Outbox column bounds](https://docs.proteanhq.com/reference/migration/v0-16/#outbox-column-bounds)
- [Elasticsearch 8.x client](https://docs.proteanhq.com/reference/migration/v0-16/#elasticsearch-8x-client)
- [Connection pool defaults](https://docs.proteanhq.com/reference/migration/v0-16/#connection-pool-defaults)
- [Health-check port](https://docs.proteanhq.com/reference/migration/v0-16/#health-check-port)
- [Observatory binds localhost](https://docs.proteanhq.com/reference/migration/v0-16/#observatory-binds-localhost)
- [Deprecations](https://docs.proteanhq.com/reference/migration/v0-16/#deprecations)

### Added

- [Observatory] Added the `/domain` page, the Domain Visualizer, with sidebar navigation and a `GET /api/domain/ir` endpoint that turns the domain IR into a graph of nodes, links, clusters, flows and projections.
- [Observatory] Added a force-directed aggregate topology graph on the `/domain` Topology tab, with cross-aggregate edges, zoom and pan, hover highlighting, a click-to-detail panel, a mini-map and a legend.
- [Observatory] Added the `/domain` aggregate detail panel, a slide-in panel with collapsible sections for fields, entities, value objects, commands, events, handlers, invariants and repository models.
- [Observatory] Added the `/domain` Event Flows tab, a directed graph of command-to-event-to-handler chains with cluster grouping, path highlighting and element type filters.
- [Observatory] Added the `/domain` Process Managers tab, a process manager state machine view, alongside a fuller domain stats summary.
- [Observatory] Added an interactive causation graph for a correlation chain, as a Graph View toggle beside the existing tree, chosen automatically for a chain deeper than two levels or longer than five events.
- [Observatory] The causation graph now groups nodes into swimlanes by stream category, with fan-out indicators, a timeline axis, a colour-coded legend, auto-collapsed deep branches past 50 nodes and a mini-map.
- [Observatory] A correlation chain now updates live over SSE: a message with a matching `correlation_id` animates into the graph, a Live badge marks recent activity, and bursts are debounced to 300ms.
- [Observatory] The correlation view now shows handler attribution, processing duration, inter-step latency and cross-aggregate boundary markers, plus End-to-End Duration and Streams Touched stat cards.
- [Observatory] Added a Traces tab on the Timeline page, with search by aggregate id, event type, command type and stream category, a recent traces table, and a deep link into each correlation chain.
- [Observatory] Added `GET /timeline/traces/recent` and `GET /timeline/traces/search`, which return the most recent correlation chains and query them by aggregate id, event type, command type or stream category.
- [Events] `CausationNode` now carries `handler`, `duration_ms` and `delta_ms`, the correlation chain response carries `total_duration_ms`, and `protean events trace` shows handler names, durations and latencies.
- [Types] Added `value_object_from_entity()`, which generates a `BaseValueObject` subclass mirroring an entity's fields, with custom naming, field exclusion and recursive conversion of `HasOne` and `HasMany`.
- [Fields] Added the `ValueObjectFromEntity` field descriptor for inline use in commands and events, as in `List(content_type=ValueObjectFromEntity(OrderItem))`.
- [Types] Added `BaseEntity.from_value_object()`, which converts a value object payload back into an entity instance and completes the round trip.
- [Types] Added `replace(**kwargs)` on `BaseValueObject`, which copies a value object with selected fields changed; it rejects an unknown field name and re-runs invariants on the new instance.
- [Events] Added `domain.correlation_trace(correlation_id)`, which returns a flat, causally ordered list of `CausationNode` objects for a correlation chain.
- [Testing] Added `assert_chain()` in `protean.testing`, which checks the sequence of message types in a correlation chain and accepts either type names or domain element classes.
- [Server] Every Protean exception handler now carries `correlation_id` in its JSON error body when a domain context is active, matching the `X-Correlation-ID` response header.
- [Server] Added graceful cleanup on shutdown: `Domain.close()` closes event store, brokers, caches and providers in reverse order, and `Engine.shutdown()` waits up to 10 seconds for in-flight handlers.
- [Server] Added Kubernetes-compatible health endpoints, `/healthz`, `/livez` and `/readyz` on the Engine and `create_health_router(domain)` for FastAPI, covering providers, brokers, event store, caches and subscriptions.
- [Server] **Breaking.** `protean server` now binds port 8080 for its health endpoints; it logs a warning and continues when the port is taken, and `[server.health]` turns the endpoints off or moves the port.
- [Server] Added a hot-reload mode for `protean server`: `--reload` watches the working directory and restarts the inner Engine on every edit, built on `watchfiles` from the new `protean[dev]` extra.
- [Observability] Added per-subscription OTel metrics: counters for messages processed, retries and DLQ routing, a processing-duration histogram, and engine gauges for up, uptime and active subscriptions.
- [Observability] Added connection pool and backpressure metrics: `BaseProvider.pool_stats()`, database pool gauges, a Redis broker pool gauge, and renamed outbox and subscription backpressure metrics.
- [Server] Added DLQ retention and alerting under `[server.dlq]`: configurable trimming, a depth threshold, per-subscription overrides, and the `protean.dlq.trimmed` and `protean.dlq.alerts` counters.
- [Docs] Added a server hardening guide and a reference page covering pool tuning, health probes, DLQ maintenance, subscription profiles, OTel metrics and graceful shutdown.
- [Server] Added a `[logging]` section in `domain.toml`, applied during `Domain.init()`, with `PROTEAN_NO_AUTO_LOGGING=1` as the escape hatch for an application that configures its own logging.
- [CLI] Added global `--log-level`, `--log-format` and `--log-config` options on every `protean` subcommand, and each command now logs its failure through a structured exception handler before exiting.
- [Observability] Added the `protean.access` wide event, one structured entry per handled message carrying the aggregate, events raised, repository operations, Unit of Work outcome and correlation ids.
- [Observability] Added `bind_event_context()` and `unbind_event_context()`, which let application code add business fields such as user tier or order total to a wide event.
- [Observability] OpenTelemetry `trace_id`, `span_id` and `trace_flags` are now injected into every log record when `telemetry.enabled=True`, so logs and traces line up in an APM tool.
- [Database] Added `slow_query` warnings and `query` debug events on the SQLAlchemy adapter, carrying the statement, parameters and duration, with the threshold and truncation set under `[logging]`.
- [Observability] Added opt-in tail sampling for wide events under `[logging.sampling]`: errors, slow requests and `critical_streams` matches are always kept, and the rest are sampled at `default_rate`, 5% by default.
- [Observability] Added the `protean.access.http` wide event, one per HTTP request, carrying method, path, status, duration, route, the commands dispatched, client IP, `request_id` and `correlation_id`.
- [Observability] Added the `[logging.http]` section, which tunes HTTP wide events through `enabled`, `exclude_paths`, `log_request_headers` and `log_response_headers`.
- [Docs] Added ADR-0010, which records the logging overhaul: the structlog bridge, wide events, the two-layer HTTP and domain split, tail sampling, redaction and the `protean.security` channel.
- [Projections] Added `protean projection status`, which reports per projection how far behind it is in time and in events, when it last advanced and its row count, with a staleness gauge for monitoring.
- [Handlers] A handler can now retry on a transient infrastructure failure: set `retries` and `backoff` on a command or event handler, or `server.transient_retry` domain-wide. Each attempt runs in a fresh `UnitOfWork`.
- [Handlers] Transient retries respect a command's deadline, so a retrying handler never runs past it, and each retry increments `protean.handler.retried`. The behaviour is opt-in and off by default.
- [Handlers] Commands now take a deadline: pass `deadline=` or `timeout=` to `domain.process()`. The deadline travels down the causal chain, and an expired command is rejected with `CommandExpiredError`.
- [Database] Added the `Q(field__isnull=True/False)` lookup on the SQLAlchemy, memory and Elasticsearch adapters; `isnull` is a required lookup, so a custom adapter that lacks it warns at domain init.
- [Database] `QuerySet.count()` now issues a flat `SELECT COUNT(*)`, or the adapter's equivalent, without projecting columns or building entities.
- [Database] Added `QuerySet.all(with_total=False)`, which skips the adapter's total-count round trip; the outbox poll uses it, so each poll issues a single `SELECT`.
- [Server] Added `outbox.max_tick_interval`, which doubles the outbox poll wait on an empty poll up to the cap and resets to `tick_interval` on a non-empty batch. It defaults to constant-rate polling.
- [Database] Added `BaseDAO._claim()`, an atomic find-and-claim primitive for queue-style consumers; PostgreSQL uses one `UPDATE … FOR UPDATE SKIP LOCKED … RETURNING`, and other backends a portable default.
- [Database] Added portable `Index` declarations through the `indexes=` option, covering composite, descending, unique, partial and covering indexes, with `Index.from_sql(dialect, ddl)` as the escape hatch.
- [Database] The `Outbox` aggregate now ships recommended indexes, and `protean schema render --indexes` writes per-dialect `CREATE INDEX` DDL to `.protean/schemas/`.
- [Database] Added `F()` expressions for column-to-column comparisons inside `Q` lookups; the in-memory and SQLAlchemy adapters resolve them natively, and the Elasticsearch adapter raises `NotImplementedError`.
- [Database] Added `QuerySet.only(*fields)`, which projects a query to a subset of columns and returns read-only `Record` objects: inert, running no invariants and unable to persist, so a read never yields a half-valid aggregate.
- [Database] Added `BaseDAO._delete_top(criteria, limit, order_by=None)`, which deletes up to `limit` rows and returns the count, so a large cleanup runs in bounded batches instead of one long-locking `DELETE`.
- [Database] The outbox cleanups now delete in batches sized by `[outbox.cleanup].batch_size`, 5000 by default, committing each batch before the next so a large backlog clears without one long-held lock.
- [Database] Brought the `any` and `overlap` array lookups to the Elasticsearch adapter and `overlap` to the in-memory adapter, so array-membership filters behave the same on every backend.
- [Testing] Added `assert_query_count`, `assert_no_subquery_wrap` and `assert_no_overfetch` to `protean.integrations.pytest`, context managers that fail on a query-cost regression against a real SQLAlchemy backend.
- [CLI] Added `protean upgrade-check`, a read-only diagnostic that reports what needs attention when upgrading to 0.16 and prints the outbox `ALTER` SQL to review. It applies nothing.

### Changed

- [Database] **Breaking.** SQLAlchemy pool defaults are now `pool_size=5` and `max_overflow=10` on PostgreSQL and MSSQL, so a deployment on the defaults opens up to `workers × 15` connections per domain where it opened `workers × 7`.
- [Database] The Redis broker, Redis cache and MessageDB event store now forward pool parameters from `conn_info`, and a `pool_size` below 5 raises a `LOW_POOL_SIZE` warning during domain validation.
- [Observability] Stdlib loggers now flow through the structlog pipeline, so framework and application code share one renderer; hot-path calls carry structured keywords, and lifecycle events moved from DEBUG to INFO.
- [Docs] Split the logging documentation into a task guide, a reference page listing every key, flag and framework logger, a concepts page on the wide event pattern, and a FastAPI HTTP wide events guide.
- [Database] `OutboxRepository.find_unprocessed` now pushes its status, lock-window and retry-window predicates into the query, removing a three-times over-fetch.
- [Database] `OutboxRepository.count_by_status` now issues flat `SELECT COUNT(*)` queries instead of subquery-wrapped projections.
- [Database] `OutboxRepository.cleanup_old_published` and `cleanup_old_abandoned` now issue a single `DELETE` and return the row count, instead of fetching the rows before deleting them.
- [Database] **Breaking.** `Outbox` string fields now declare `max_length`, so SQL providers emit `VARCHAR(N)` in place of `TEXT`, which unblocks indexes on the table; an existing deployment runs a one-time `ALTER TABLE`.
- [Database] **Breaking.** The Elasticsearch adapter now supports the 8.x client, which a fresh install resolves to, and that client needs an 8.x server; pin `elasticsearch<8` to stay on the 7.17 client.
- [Observatory] **Breaking.** `protean observatory` now binds loopback instead of `0.0.0.0`, since it is unauthenticated and exposes DLQ management; pass `--host 0.0.0.0` to reach it from another host.

### Deprecated

- [CLI] `--debug` on `protean server` and `protean observatory` is deprecated in favour of `--log-level DEBUG`; it still works, emits a `DeprecationWarning`, and goes in v0.17.0.

### Removed

- [Testing] **Breaking.** Removed `assert_valid` and `assert_invalid` from `protean.testing`: replace `assert_invalid(lambda: op(), message="X")` with `pytest.raises(ValidationError, match="X")`, and `assert_valid(lambda: op())` with a plain call.

### Fixed

- [Observatory] Fixed graph rendering showing black overlays after the DaisyUI 4 to 5 upgrade, by moving every `oklch(var(--b1))` reference to its DaisyUI 5 equivalent.
- [Observatory] Fixed the causation graph treating an aggregate's command and event streams as separate swimlanes; the `:command` suffix is now stripped, so both share one.
- [Events] Fixed a subscriber setting `causation_id` to the Redis Stream delivery id instead of the source event's `message_id`, so a command dispatched from a subscriber now carries the right causation link.
- [Observatory] Fixed the Observatory labelling every event with the first domain's name when several domains share one MessageDB; attribution now comes from the stream name prefix.
- [Database] Fixed a check-then-act race in optimistic locking: the version check is now atomic with the write across the SQLAlchemy, memory and Elasticsearch repositories and the memory event store.
- [Check] Two command handler classes claiming the same command now raise `IncorrectUsageError` at `Domain.init()` and are reported by `protean check`, instead of colliding at dispatch time.
- [Database] Fixed a race where two workers could claim and publish the same outbox message; a batch is now claimed in one round trip through `OutboxRepository.claim_batch()`.
- [Internals] `command_handler`, `event_handler` and `repository` now accept a string `part_of` reference and resolve it like every other element, instead of raising at registration.

### Security

- [Server] Sensitive fields are now masked in log output by `ProteanRedactionFilter` and `make_redaction_processor()`, configured under `[logging].redact`; operator keys union with the defaults, which cannot be turned off.
- [Server] `protean server --workers N` with more than one worker now installs a `QueueHandler` and `QueueListener`, so JSON log lines never interleave across worker processes.
- [Server] Added the `protean.security` logger for domain-boundary failures: invalid operation and state errors, invariant violations and boundary command validation errors emit WARNING events for SIEM use.

## [0.15.0] - 2026-04-10

### Upgrade Notes

Read the [0.15 migration guide](https://docs.proteanhq.com/reference/migration/v0-15/) before you upgrade. These changes can need action:

- [Install Pydantic v2](https://docs.proteanhq.com/reference/migration/v0-15/#1-install-pydantic-v2)
- [Wrap value object lists in a `ValueObject` descriptor](https://docs.proteanhq.com/reference/migration/v0-15/#2-wrap-vo-lists-in-a-valueobject-descriptor)
- [Remove extra keyword arguments from value object constructors](https://docs.proteanhq.com/reference/migration/v0-15/#3-remove-extra-kwargs-from-value-object-constructors)
- [Replace `domain.publish` with broker access](https://docs.proteanhq.com/reference/migration/v0-15/#4-replace-domainpublish-with-broker-access)
- [Update `Message` imports and method names](https://docs.proteanhq.com/reference/migration/v0-15/#5-update-message-class-imports-and-method-names)
- [Update message metadata access](https://docs.proteanhq.com/reference/migration/v0-15/#6-update-message-metadata-access)
- [Add `@apply` handlers for every event-sourced event](https://docs.proteanhq.com/reference/migration/v0-15/#7-add-apply-handlers-for-every-event-sourced-event)
- [Handle `from __future__ import annotations`](https://docs.proteanhq.com/reference/migration/v0-15/#8-handle-from-__future__-import-annotations)
- [`to_dict()` replaces `model_dump()`](https://docs.proteanhq.com/reference/migration/v0-15/#to_dict-vs-model_dump)
- [Invariants skip when field validation fails](https://docs.proteanhq.com/reference/migration/v0-15/#invariants-skip-when-field-validation-fails)
- [`HasMany` `add_` and `remove_` trigger pre-invariants](https://docs.proteanhq.com/reference/migration/v0-15/#hasmany-add_remove_-trigger-pre-invariants)
- [Elasticsearch needs explicit field mappings and a re-index](https://docs.proteanhq.com/reference/migration/v0-15/#elasticsearch-explicit-field-mappings-and-re-indexing)

### Added

- [CLI] Added `--fix` on the `protean-check-staleness` pre-commit hook, which regenerates stale IR and stages it with `git add`, so the commit goes through without a manual step.
- [CLI] Both pre-commit hooks now read a `[domains]` section in `.protean/config.toml` that maps domain names to module paths, so one hook entry checks every bounded context, each with its own IR file.
- [Observability] Added `protean.integrations.logging`, whose correlation filter and structlog processor inject `correlation_id` and `causation_id` into every log record, both wired by `domain.configure_logging()`.
- [Observatory] `MessageTrace` and `TraceEmitter.emit()` now carry `correlation_id` and `causation_id`, so handler, process manager, outbox and ack trace events can be grouped and linked by correlation chain.
- [Observability] Added `protean.correlation_id` and `protean.causation_id` attributes on the handler, Unit of Work commit and outbox spans, so a whole chain can be filtered by correlation id in an APM tool.
- [Server] `DomainContextMiddleware` now reads `X-Correlation-ID`, falling back to `X-Request-ID`, as the default correlation id for command processing, and echoes the id it used on every response.
- [Testing] Added end-to-end tests for correlation and causation propagation across a command, event, handler and projection chain, covering external ids, broker propagation and OTel span attributes.
- [IR] Added deprecation support for elements and fields: a `deprecated` option on every element type and a `deprecated` parameter on fields, with `DEPRECATED_ELEMENT` and `DEPRECATED_FIELD` diagnostics in `protean check`.
- [IR] Contract diffing is now deprecation-aware: it reads the declared removal version and classifies a removal as expected, premature or unexpected.
- [IR] Added `.protean/config.toml` support for compatibility checking through `CompatConfig` and `load_config()`, covering strictness, excluded FQN patterns, minimum versions before removal and staleness.
- [Docs] Added a compatibility checking guide covering the `.protean/` layout, the `config.toml` reference, the breaking-change rules, the CLI commands, pre-commit setup, CI patterns and the deprecation lifecycle.
- [Docs] Added a guide to correlation and causation ids covering the out-of-the-box guarantee, external callers, the propagation flow, cross-service boundaries, the OTel relationship and structured logging.
- [CLI] Added `.pre-commit-hooks.yaml` and the `protean-check-staleness` and `protean-check-compat` console scripts, so a downstream project can add either one as a pre-commit hook.
- [IR] `protean ir diff` now loads `.protean/ir.json` as the baseline when only `--domain` is given, reads that baseline from any commit with `--base`, and exits 0, 1 or 2 for no, breaking or non-breaking changes.
- [IR] Added `check_staleness()`, which compares the live domain's IR checksum against the materialized `.protean/ir.json`, exposed as `protean ir check` with fresh, stale and missing exit codes.
- [IR] Added `classify_changes()`, which walks every persisted IR section and applies the breaking-change rules: a removal, a type change or a required field with no default breaks, an addition or a defaulted field is safe.
- [Observatory] The Timeline page now updates live over SSE: a new event prepends with a highlight, a toast offers to scroll to the top when you are further down, and the stat cards refresh on each trace event.
- [Observatory] Added correlation chain and aggregate history sub-views on the Timeline page, with a causation tree, a version-labelled aggregate history, clickable ids, deep links and back navigation.
- [Observatory] Added the Timeline page, a chronological event browser with filters, cursor-based pagination, an event detail panel, summary stat cards, deep links and a `g→t` keyboard shortcut.
- [Docs] Added an OpenTelemetry guide covering configuration, the span and metric catalogs, TraceParent propagation, FastAPI auto-instrumentation, APM setup, and how the Observatory and OTel relate.
- [Testing] Added end-to-end tests for the span hierarchy from command to handler to Unit of Work to repository to event store, checking the parent-child links and that Observatory traces fire alongside.
- [Observability] Added the OpenTelemetry foundation: an optional `telemetry` extra, a `[telemetry]` config section, and lazy `Domain.tracer` and `Domain.meter`, all no-ops when the packages are absent.
- [Observability] Added spans for command processing and handler dispatch, covering command handlers, event handlers, projectors and process managers, with the exception recorded and an ERROR status on failure.
- [Observability] Added spans for infrastructure work: Unit of Work commits, repository `add` and `get` on both standard and event-sourced repositories, and event store appends, all in the originating trace.
- [Observability] Added spans for subscriptions and the outbox processor, per message and per batch, with exceptions recorded and a parent-child link between a batch and the messages it publishes.
- [Observability] W3C TraceParent headers now bridge to OpenTelemetry context: an incoming trace parents the processing span, and outgoing commands and events carry the active span's traceparent forward.
- [Observability] Added `instrument_app(app, domain)` in `protean.integrations.fastapi`, which instruments FastAPI with domain-scoped providers so an HTTP request span parents the command processing span.
- [Observability] Added OpenTelemetry metrics for domain operations: counters for commands, handler invocations, commits and outbox publishes, and histograms for command, handler and outbox latency.
- [Observatory] The `/metrics` endpoint now serves OTel-generated Prometheus text when the Prometheus exporter is installed and telemetry is on, and falls back to the hand-rolled implementation otherwise.
- [Observatory] Added correlation chain and aggregate history API endpoints, returning every event in a chain with its causation tree, and the full event history of one aggregate instance with versions.
- [Observatory] Added event store timeline API endpoints: a paginated, filterable list from the `$all` stream, one event's full detail, and summary statistics for events, active streams and throughput.
- [IR] Added a JSON Schema generator that converts IR element dicts into Draft 2020-12 schemas, with `x-protean-*` extension metadata, for every data-carrying element.
- [IR] Added a schema file writer that materializes the generated schemas into `.protean/schemas/`, grouped by aggregate cluster, with versioned filenames and deterministic output.
- [CLI] Added `protean schema generate`, which writes JSON Schema files for every data-carrying element from a live domain or an IR file, to `.protean/schemas/` by default.
- [CLI] Added `protean schema show`, which prints one element's JSON Schema by name or FQN, syntax-highlighted by default and raw with `--raw` for piping.
- [Testing] Added meta-schema validation of every generated schema against JSON Schema Draft 2020-12, and payload validation tests that check sample payloads against the generated schemas.
- [Docs] Added ADR-0005 on IR-first schema generation and ADR-0006 on standard JSON Schema with `x-protean-*` extensions, alongside a schema generation guide.

### Changed

- [Docs] The documentation now names `to_dict()` as the only recommended way to serialize a domain element and warns against Pydantic's `model_dump()`, which mishandles Reference fields, shadow fields and datetimes.
- [Fields] **Breaking.** A status field's self-transition is now checked against the transition map: assigning a status its current value is rejected unless the state lists itself as a target, and a terminal state rejects it too.

### Fixed

- [Database] Fixed persistence ordering in `BaseRepository`: the aggregate root is saved before its children and children before grandchildren, so a database that enforces foreign keys immediately accepts the writes.
- [Docs] The pre-commit documentation now recommends `repo: local` with `language: system`, since the hooks call `derive_domain()`, which imports user code that pre-commit's isolated virtualenv does not have.
- [CLI] Fixed unreadable handler wiring and event flow diagrams by splitting them into one diagram per concern in the Markdown output. (#821)
- [CLI] Fixed Mermaid parse errors in cluster diagrams when an invariant name contains a comma or is left unquoted.
- [Database] Fixed `TypeError: can't compare offset-naive and offset-aware datetimes` in outbox retry, which blocked all outbox processing; a naive datetime from an adapter is now normalized before comparison.
- [Testing] Fixed the flaky `test_mixed_error_scenarios` by raising the test-mode processing cycles from 3 to 10, so every subscription type has time to process its messages under CI load.
- [Events] An external broker message's `correlation_id` now reaches the commands a subscriber dispatches, and a fresh id is generated when the message carries none, so the cross-service chain survives.
- [Internals] `CommandProcessor.process()` now saves and restores the outer `g.message_in_context` instead of clearing it, so a subscriber dispatching several commands in one handler no longer loses the correlation id.

## [0.15.0rc1] - 2026-03-11

### Added

- **Pydantic v2** as the validation and serialization engine — all domain
  elements inherit from Pydantic's `BaseModel` with Rust-powered validation
- Three field definition styles: annotation (recommended), assignment
  (backward-compatible), and raw Pydantic (escape hatch)
- `FieldSpec` abstraction — Protean's field functions (`String`, `Integer`,
  etc.) return `FieldSpec` objects resolved into Pydantic `Annotated[type,
  Field(...)]` at class creation time
- JSON Schema generation via `model_json_schema()` on all domain elements
- Native serialization via `model_dump()` and `model_dump_json()`
- mypy plugin (`protean.ext.mypy_plugin`) resolving FieldSpec return types to
  Python types (`String` → `str`, `Integer` → `int`, etc.)
- `py.typed` marker for PEP 561 compliance
- `pyrightconfig.json` to suppress `reportInvalidTypeForm` for
  annotation-style fields
- `ValueObjectList` field for embedding Value Object lists (replaces old `List`
  descriptor behavior)
- Outbox pattern for reliable message delivery — events persisted in the same
  transaction as aggregate changes, delivered by `OutboxProcessor`
- Message format versioning with `specversion`, `checksum`, and
  `MessageHeaders`
- Redis Streams for async event/command processing
- Broker registry for runtime broker discovery and management
- Subscription configuration system with priority hierarchy
- Command idempotency with Redis-backed deduplication
- Intermediate Representation (IR) — `domain.to_ir()` captures complete domain
  topology as JSON
- `protean check` CLI — validates domain definitions and reports errors,
  warnings, and diagnostics with severity levels
- Architecture documentation generation — `protean docs generate` produces
  Mermaid diagrams for aggregate clusters, event flows, handler wiring, and
  event catalogs
- IR metadata enrichment — contracts with language-neutral keys, version, and
  field schemas; description and repository database in IR output
- IR diff engine — `protean ir diff` detects breaking changes between IR
  snapshots
- Testing DSL — `protean.testing` module with `given()`, `EventSequence`,
  `ProjectionResult`, `ProcessManagerSetup`, `ProcessManagerResult`
- Snapshot testing — JSON snapshot files with `assert_snapshot()` and
  `--update-snapshots` pytest flag
- Process managers — `@domain.process_manager` for multi-aggregate process
  coordination with state transitions
- Query handlers — `@domain.query_handler` and `domain.dispatch()` for
  read-side CQRS
- First-class `@domain.query` element for read-side CQRS
- `ReadView` via `domain.view_for()` for read-only projection access
- `ReadOnlyQuerySet` via `domain.query_for()` for CQRS read-side queries
- ValueObject support in Projections
- Status field with state transition enforcement
- Event upcasters — `@domain.upcaster` for transparent event schema evolution
- Priority lanes — two-lane event routing through Redis Streams (primary +
  backfill)
- Multi-worker supervisor for the Protean Engine
- Observatory dashboard — `protean observatory` for real-time domain monitoring
- Dead letter queue management — inspect, replay, and purge failed messages
- Subscription lag monitoring via Observatory, Prometheus, and CLI
- Database lifecycle API — `domain.create_database()`,
  `domain.drop_database()`, `domain.truncate_database()` with CLI commands
- Database capability system — `DatabaseCapabilities` enum with
  capability-based pytest markers
- Entry-points adapter discovery — provider registry migrated from hardcoded
  dict to `entry_points`
- Adapter conformance testing — `protean test-adapter` CLI with generic test
  suites
- Structured logging with `structlog` integration
- FastAPI middleware for `DomainContext` propagation
- Correlation and causation IDs — end-to-end message tracing
- Causation chain API for traversing command/event causal relationships
- Message enrichment hooks for events and commands
- Event store inspection CLI — read, stats, search, history
- Temporal queries for event-sourced aggregates
- Projection rebuilding — CLI command and domain API
- Manual snapshot triggers for event-sourced aggregates
- Python 3.14 support; multi-version testing via `nox`
- pytest plugin — `DomainFixture` and auto-env configuration
- Enhanced domain linting with unified diagnostic model and severity levels
- `protean shell` interactive shell with domain context
- CloudEvents v1.0 serialization as boundary contract
- Multi-tenancy documentation and context propagation pattern
- ADR practice established in `docs/adr/`
- Documentation: defining fields guide, field system internals, migration guide
  for 0.12–0.14 → 0.15, quickstart, long-form tutorial (Online Bookstore),
  testing guide, application services guide, subscribers guide, patterns &
  recipes, and landing page revamp

### Changed

- `List` field is now a `FieldSpec` factory for generic typed lists (use
  `ValueObjectList` for the old Value Object list descriptor)
- Event/command `__version__` is now an integer, not a string
- Metadata attributes restructured across commands and events; `message.py`
  folded into `eventing.py`
- `DeserializationError` introduced for enhanced error handling context
- Domain class refactored into 7 focused helper classes using composition
- Async message processing improvements and Engine lifecycle hardening
- Invariants checked only when there are no field-level errors

### Deprecated

- `from protean.fields import List` as Value Object list descriptor — use
  `ValueObjectList` instead

### Removed

- `MessageRecord` — metadata attributes restructured
- `update_all` and `delete_all` from `QuerySet` public API

### Fixed

- Mark aggregate dirty when ValueObject field is updated
- Rebind `__class__` cells in `derive_element_class`
- Sorting by `referenced_as` attributes

## [0.14.2] - 2025-08-24

### Added

- `via` parameter support on Reference and Association fields

### Changed

- Entity and model conversion methods refactored to use `referenced_as`
  attributes
- Documentation on entity relationships, per-aggregate CQRS/ES pattern choice,
  and deciding between aggregates and entities

## [0.14.1] - 2025-08-14

### Added

- Schema support in MSSQL connection string

## [0.14.0] - 2025-08-13

### Added

- Microsoft SQL Server support
- Python 3.13 support
- Outbox processor for reliable message delivery
- `has_table` inspection method on all DAO implementations

## [0.13.1] - 2025-06-03

### Fixed

- Keep server running by gracefully logging exceptions

## [0.13.0] - 2025-03-09

### Added

- Multi-environment configuration support (dev, staging, prod) driven by TOML
- `Field.clone()` helper for programmatically copying field definitions

### Changed

- Major event-sourcing overhaul — unified event-sourced and regular Aggregates,
  making them interchangeable in client code
- Stream subsystem refinements reducing boilerplate and improving performance
- Domain initialized before the Engine starts; explicit check for compatible
  database provider at initialization
- Simplified Broker and Subscriber APIs; subscribers now run inside the Engine
  event loop
- Exceptions hierarchy streamlined
- `Options` refactored to subclass `dict` for easier introspection
- Application-service enhancements: stricter invariants and clearer lifecycle
  hooks

## [0.12.1] - 2024-06-20

### Added

- Constants under `[custom]` section available directly on the domain

### Changed

- Simplified domain traversal logic with improved performance
- Optimized handler fetching for domain events

### Removed

- `clone` method from Entity/Aggregate
- `provider` meta option from Entities

## [0.12.0] - 2024-06-17

### Added

- `protean shell` CLI command
- Support for different identity types in `Identifier` field
- Specifying child entities during Aggregate initialization
- Nesting of associations
- `@invariant` decorator — runs on initialization and attribute changes
- Domain config in TOML with environment variable support
- Domain Service enhancements with `pre` and `post` invariant structures
- Filtering on `HasMany` entities
- Lists as field value choices along with Enums
- Custom identity function support
- Identity generation customization in Auto field
- Publishing multiple events in a single call

### Changed

- Switched from Copier to Typer for project generation with comprehensive tests
- Switched docs to Material for MkDocs (https://docs.proteanhq.com)
- Domain name initialized to domain's module name when not provided
- CLI module refactoring for Typer
- Commands and Events are now immutable
- Replaced `flake8` + `black` + `isort` with `ruff`
- Identity generated as first step during entity initialization
- Auto-add reference fields in child entities
- Associations can only link to other entities
- References resolved when initializing Domain
- `aggregate_cls` renamed to `part_of`
- Owner and root linkages preserved in child entities
- `Entity.defaults` runs before validations
- SQLAlchemy upgraded to 2.0.x
- BaseModel revamped for parity with other domain elements
- Events registered only on Aggregates
- Aggregate cluster tracked for element membership
- Naked `Repository.add` calls enclosed within UoW

### Removed

- Support for inner Meta class
- `all` method from repository
- `current_domain` usage where domain is readily accessible
- `via` param for associations (re-added in 0.14.2)

## [0.11.0] - 2024-03-16

### Added

- Python 3.12 support

### Changed

- Moved to Poetry for dependency management
- Domain directory traversal controlled explicitly in `init()`
- Domain traversal refactoring

## [0.10.0] - 2023-11-16

### Changed

- `domain.init` enhanced as the way to activate a domain
- Introduced `WITH_COVERAGE` test category for GitHub Actions

### Removed

- Dynamic initializations in providers, brokers, caches, and event stores

## [0.9.1] - 2022-02-23

### Fixed

- Use Domain's EventStore connection details for clearing events after test
  runs

## [0.9.0] - 2022-02-17

### Added

- MessageDB Event store adapter
- Memory Event store (stand-in)
- EventSourced Aggregates and Event Handlers
- EventSourced Repositories
- Filtering messages from their origin stream
- Event Handlers can listen to other streams and ALL streams
- Command Handler methods can handle any event
- Synchronous event and command processing mode
- Asynchronous command processing by submitting commands to domain
- `autoflake` added to pre-commit
- `any` filter and scalar values for `in` operator in Memory DB
- Support for inter-attribute dependencies in Option defaults
- Caching for registry, repositories, DAOs, and models via `@cache`

### Changed

- Value Object values output as nested dicts instead of forced flat structure
- DAOs enclosed within repositories — DB interaction solely through repos
- Aggregate versions for concurrency management
- EventHandler and CommandHandler methods execute within UnitOfWork
- Commands and Events associated with streams (explicit and via Aggregates)
- Empty string treated as None in Date and DateTime Fields

### Removed

- `remove` method from repository (to discourage hard deletes)

### Fixed

- Sorting issue with null values in Memory DB

## [0.8.2] - 2023-04-26

### Fixed

- Get index name during Elasticsearch connection
- Attach new engine to metadata
- Scope schema inclusion in metadata and engine to Postgres alone

## [0.8.1] - 2022-01-13

### Added

- Custom separator support in Elasticsearch namespaces

## [0.8.0] - 2021-10-07

### Added

- `List` fields can contain `Dict` objects
- Stateful views for persistence and retrieval
- Auto-generated `message_id` on Events
- Pickling support for Protean exceptions

### Changed

- `fields` module moved under main package

### Fixed

- Fetch projection objects instead of IDs in `cache.get_all()`
- Generate embedded ValueObject data properly in `to_dict()`
- Derive SQLAlchemy field types correctly for embedded value object fields
- Elasticsearch adapter bugfixes and model enhancements

[Unreleased]: https://github.com/proteanhq/protean/compare/v0.18.0...HEAD
[0.18.0]: https://github.com/proteanhq/protean/compare/v0.17.1...v0.18.0
[0.17.1]: https://github.com/proteanhq/protean/compare/v0.17.0...v0.17.1
[0.17.0]: https://github.com/proteanhq/protean/compare/v0.16.3...v0.17.0
[0.16.3]: https://github.com/proteanhq/protean/compare/v0.16.2...v0.16.3
[0.16.2]: https://github.com/proteanhq/protean/compare/v0.16.1...v0.16.2
[0.16.1]: https://github.com/proteanhq/protean/compare/v0.16.0...v0.16.1
[0.16.0]: https://github.com/proteanhq/protean/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/proteanhq/protean/compare/v0.15.0rc1...v0.15.0
[0.15.0rc1]: https://github.com/proteanhq/protean/compare/v0.14.2...v0.15.0rc1
[0.14.2]: https://github.com/proteanhq/protean/compare/v0.14.1...v0.14.2
[0.14.1]: https://github.com/proteanhq/protean/compare/v0.14.0...v0.14.1
[0.14.0]: https://github.com/proteanhq/protean/compare/v0.13.1...v0.14.0
[0.13.1]: https://github.com/proteanhq/protean/compare/v0.13.0...v0.13.1
[0.13.0]: https://github.com/proteanhq/protean/compare/v0.12.1...v0.13.0
[0.12.1]: https://github.com/proteanhq/protean/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/proteanhq/protean/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/proteanhq/protean/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/proteanhq/protean/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/proteanhq/protean/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/proteanhq/protean/compare/v0.8.2...v0.9.0
[0.8.2]: https://github.com/proteanhq/protean/compare/v0.8.1...v0.8.2
[0.8.1]: https://github.com/proteanhq/protean/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/proteanhq/protean/compare/v0.7.1...v0.8.0
