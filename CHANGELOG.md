# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [0.18.0] - 2026-10-21

### Upgrade Notes

Read the [0.18 migration guide](https://docs.proteanhq.com/reference/migration/v0-18/) before you upgrade. These changes can need action, in the order the guide covers them:

<details markdown="1">
<summary>48 breaking changes, in the order the guide covers them</summary>

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
  **Migration:** [`check` and `verify` machine output changed shape and exit codes](https://docs.proteanhq.com/reference/migration/v0-18/#check-and-verify-machine-output-changed-shape-and-exit-codes)
- [CLI] **Breaking (machine output).** `protean events catalog --json`, `protean subscriptions status --json` and `protean projection status --json` now emit the shared result envelope instead of a bare JSON array, with the list under `data`. (#1394)
  **Migration:** [`events catalog`, `subscriptions status`, and `projection status` JSON moved onto the envelope](https://docs.proteanhq.com/reference/migration/v0-18/#events-catalog-subscriptions-status-and-projection-status-json-moved-onto-the-envelope)
- [CLI] Each Markdown slice of `protean docs generate --type=event-model` now leads with a structural Given-When-Then derived from the IR; the `--format=mermaid` output is unchanged. (#1336)
- [IR] **Breaking.** The IR schema moved from `0.1.0` to `0.2.0` to carry the new `method_edges` key, so a committed `.protean/ir.json` baseline reports a version mismatch until you regenerate it. (#1433)
  **Migration:** [The IR schema is now v0.2.0](https://docs.proteanhq.com/reference/migration/v0-18/#the-ir-schema-is-now-v020)
- [IR] `--format` is now validated on `protean ir diff`, `ir show` and `ir check`; an invalid value fails with the valid formats listed, where it used to fall through to the default silently. (#1435)
  **Migration:** [`protean ir` rejects an unknown format value](https://docs.proteanhq.com/reference/migration/v0-18/#protean-ir-rejects-an-unknown-format-value)
- [CLI] `protean add` now splits the aggregate it plans across a generation-gap seam, a generated base and a hand-owned subclass, with each planned file marked `generated` or `hand_owned`. (#1341)
- [CLI] `protean add <element> <name>` now writes the slice to disk by default, create-only and rolling back a partial write; pass `--dry-run` for the old preview-only behavior. (#1342)
- [CLI] **Breaking.** `protean new`'s dry-run flag is `--dry-run`. `--pretend` and its `-p` short form are gone, and passing either is a usage error. (#1473)
  **Migration:** [`protean new --pretend` is now `--dry-run`, and it writes nothing](https://docs.proteanhq.com/reference/migration/v0-18/#protean-new-pretend-is-now-dry-run-and-it-writes-nothing)
- [CLI] **Breaking.** `protean new`'s dry run no longer touches the target directory: it renders into a temp directory and prints the project-relative paths it would create. (#1466)
  **Migration:** [`protean new --pretend` is now `--dry-run`, and it writes nothing](https://docs.proteanhq.com/reference/migration/v0-18/#protean-new-pretend-is-now-dry-run-and-it-writes-nothing)
- [DX] `protean new` now ships a dx-managed project, writing the same managed-block `AGENTS.md` and `CLAUDE.md` bridge that `protean dx install` writes and recording them in `.protean/dx-state.json`. (#1515)
- [DX] `protean dx check` now verifies a required baseline (`AGENTS.md` and the `CLAUDE.md` bridge) plus whatever optional target is present on disk or recorded in `.protean/dx-state.json`, so an editor file you never chose is no longer counted as drift. (#1515)
- [DX] `protean dx refresh` now writes only what a project already has, sharing one scope with `check`, where it used to write all six targets the way `install` does. (#1515)
- [DX] Hardened the twelve building-block teaching skills and wired them to the diagnostic contract: the six that teach a coded convention declare their codes under `metadata.diagnostic_codes`, and several statements about the framework and about what the checks measure are corrected. (#1552)
- [DX] Hardened the event-driven and CQRS teaching skills, fixing drift against the current API (`event_sourced=True`, value objects allowed in projections, `BaseEventSourcedRepository`) and declaring the codes each one teaches. (#1553)
- [DX] Hardened the DX-pack workflow, refactor and analysis skills: six declare the `check` codes they teach the fix for, a test fails a skill that declares a code it never mentions, and a drifted upcaster example is corrected. (#1554)
- [Event store] Removing a field from an event-sourced aggregate can now be earned safe by naming it in `reserved`: during replay an assignment to a reserved name is dropped instead of raising, and `protean ir diff` downgrades the removal to safe. (#1584)
  **Migration:** [Removing a field from an event-sourced aggregate needs `reserved`](https://docs.proteanhq.com/reference/migration/v0-18/#removing-a-field-from-an-event-sourced-aggregate-needs-reserved)
- [Types] Under the mypy plugin, a class decorated with an element decorator is now a subclass of its Protean base class, as it is at runtime, so it is accepted wherever a signature names the base. (#1874)
  **Migration:** [mypy sees decorated elements as subclasses of their base](https://docs.proteanhq.com/reference/migration/v0-18/#mypy-sees-decorated-elements-as-subclasses-of-their-base)
- [Packaging] **Breaking.** Right-sized the runtime dependency surface: `fastapi`, `uvicorn`, `jinja2`, `ipython` and `copier` moved out of the core install into feature extras (`protean[server]`, `protean[shell]`, `protean[scaffold]`), with `protean[cli]` and `protean[all]` bundles. (#1000)
  **Migration:** [Right-size the runtime dependency surface](https://docs.proteanhq.com/reference/migration/v0-18/#what-moved-behind-extras)
- [Packaging] **Breaking.** Replaced Werkzeug's `LocalProxy`/`LocalStack` with stdlib `contextvars` for `current_domain`, `current_uow` and `g`, so the active context follows asyncio tasks and `werkzeug` is no longer a core dependency. (#1375)
  **Migration:** [werkzeug left the core install](https://docs.proteanhq.com/reference/migration/v0-18/#werkzeug-left-the-core-install)
- [Packaging] **Breaking.** `cffi` and `greenlet` are no longer core dependencies; nothing in Protean imports either, and their floors moved to the extras that pull them. (#1376)
  **Migration:** [cffi and greenlet left the core install](https://docs.proteanhq.com/reference/migration/v0-18/#cffi-and-greenlet-left-the-core-install)
- [Cache] `get_ttl(key)` now answers the same three cases on every adapter: `None` when there is no such key, `math.inf` when the key never expires, and the seconds remaining otherwise. (#1392)
  **Breaking (both cache adapters).** `BaseCache.get_ttl`'s signature changes from `-> float` to `-> float | None`. `BaseCache` is a Provisional API, so this lands in a minor release with no deprecation period.
  **Migration:** [`get_ttl` returns None or math.inf instead of a raw sentinel](https://docs.proteanhq.com/reference/migration/v0-18/#get_ttl-returns-none-or-mathinf-instead-of-a-raw-sentinel).
- [Cache] The `key_pattern` argument to `_get_all`, `count` and `remove_by_key_pattern` is now a glob on every adapter; the memory cache used to compile it as a Python regular expression while Redis read it as a glob. (#1393)
  **Breaking (memory cache).** A pattern that leaned on regex behaviour selects differently now: `.` was "any character" and is now a literal dot, and anchors and character-class escapes are gone. Rewrite regex patterns as globs.
  **Migration:** [Cache key patterns are a glob on every adapter](https://docs.proteanhq.com/reference/migration/v0-18/#cache-key-patterns-are-a-glob-on-every-adapter).
- [Cache] `Cache.get_all` is now the private, unpaginated `Cache._get_all`: it returns matching entries in key order up to a fixed cap of 1000 and no longer takes `last_position` or `size`. (#1401)
  **Migration:** [Cache `get_all` is now the private, unpaginated `_get_all`](https://docs.proteanhq.com/reference/migration/v0-18/#cache-get_all-is-now-the-private-unpaginated-_get_all)
- [Fields] **Breaking.** String and Text fields no longer sanitize by default: pass `sanitize=True` on a field rendered as HTML without output encoding, or set `[field_defaults] sanitize` for a whole domain. (#1455)
  **Migration:** [String and Text no longer sanitize by default](https://docs.proteanhq.com/reference/migration/v0-18/#string-and-text-no-longer-sanitize-by-default)
- [Docs] The schema-evolution guides now point at the snapshot caveat: upcasters run on replayed events, not on snapshots. (#1526)
- [CLI] `protean schema render --indexes` now rejects an unknown `--dialects` value instead of quietly rendering it with the SQLite dialect. The accepted values are `postgresql`, `sqlite`, `mssql`, `mysql` and `mariadb`. (#1580)
  **Migration:** [`protean schema render --indexes` rejects an unknown dialect](https://docs.proteanhq.com/reference/migration/v0-18/#protean-schema-render-indexes-rejects-an-unknown-dialect)
- [Event store] The `reserved` option now also covers the generated `add_<name>` and `remove_<name>` helpers of a removed association: during replay the call does nothing instead of raising `AttributeError`. (#1592)
- [Database] The MySQL and MSSQL providers now check for their driver at `domain.init()`, raising a `ConfigurationError` that names the database, the driver and the extra to install. (#1593)
- [Testing] **Breaking (test mode only).** `Engine(test_mode=True).run()` and `protean server --test-mode` now stop as soon as every subscription has run out of work, instead of always running eleven 0.1-second cycles. (#1617)
  **Migration:** [The test-mode engine stops as soon as it is idle](https://docs.proteanhq.com/reference/migration/v0-18/#the-test-mode-engine-stops-as-soon-as-it-is-idle)
- [Scaffold] Projects generated by `protean new` now set up their test domain with `DomainFixture`, so each test runs in its own domain context and every database, broker and event store is reset after each test. (#1633)
- [Handlers] **Breaking.** `domain.init()` now rejects a `sequential_by` value that is not a non-empty field name on an event handler, command handler or projector; the boolean form is for process managers. (#1649)
  **Migration:** [`sequential_by` on a handler or projector must be a field name](https://docs.proteanhq.com/reference/migration/v0-18/#sequential_by-on-a-handler-or-projector-must-be-a-field-name)
- [IR] **Breaking.** Domain traversal now loads modules in a fixed order, the root directory's files first then each subdirectory by name, where it used the order `os.listdir` returned. (#1664)
  **Migration:** [Domain traversal loads modules in name order](https://docs.proteanhq.com/reference/migration/v0-18/#domain-traversal-loads-modules-in-name-order)
- [Check] `protean check --domain=<file>` no longer crashes with a `FileNotFoundError` on a file that declares `Domain(__name__)`, and a module that raises during traversal now ends the command with a one-line error instead of a traceback. (#1685)
  **Breaking.** A failure to build the IR is now an error in the `Domain.check()` result (status `fail`, `protean check` exits 1) in place of a logged traceback beside a `pass`.
  **Migration:** [A failed IR build now fails `check`](https://docs.proteanhq.com/reference/migration/v0-18/#a-failed-ir-build-now-fails-check)
- [Server] With priority lanes on and the Redis broker, an idle stream subscription now waits on the primary and the backfill stream in one read, through a new broker `read_blocking_streams` method. (#1687)
- [Database] **Breaking (driver).** The PostgreSQL provider defaults to psycopg 3: `protean[postgresql]` installs `psycopg[binary]`, and the new `protean[postgresql-psycopg2]` extra installs `psycopg2-binary`. (#1689)
  **Migration:** [PostgreSQL defaults to psycopg 3](https://docs.proteanhq.com/reference/migration/v0-18/#postgresql-defaults-to-psycopg-3)
- [Database] The memory provider's `raw()` raises `DatabaseError` for a malformed query, where it raised a bare `Exception`, and some error logs no longer repeat the exception text the traceback already shows. (#1714)
  **Migration:** [The memory provider's `raw()` raises `DatabaseError`, and some error logs drop the exception text](https://docs.proteanhq.com/reference/migration/v0-18/#the-memory-providers-raw-raises-databaseerror-and-some-error-logs-drop-the-exception-text)
- [Internals] **Breaking.** Internal paths that caught every exception now catch only the errors they expect, so any other error reaches the caller or the next handler up. Ruff's `BLE001` now checks `src/` and `specs/` without per-file exceptions. (#1715)
  **Migration:** [Some internal fallbacks let unexpected errors through](https://docs.proteanhq.com/reference/migration/v0-18/#some-internal-fallbacks-let-unexpected-errors-through)
- [Internals] **Breaking.** Paths that expect one kind of failure now handle only that failure, including no active domain context, a `[logging]` value that is not a table, and a closed health-check socket. (#1716)
  **Migration:** [Some internal fallbacks let unexpected errors through](https://docs.proteanhq.com/reference/migration/v0-18/#some-internal-fallbacks-let-unexpected-errors-through)
- [Internals] **Breaking.** An element given a non-dict positional argument now raises `TypeError` instead of `AssertionError`, and a field's `renamed_from` given a value that is not a string, list or tuple raises `TypeError` instead of `ValueError`. (#1717)
  **Migration:** [A non-dict positional argument raises `TypeError`](https://docs.proteanhq.com/reference/migration/v0-18/#a-non-dict-positional-argument-raises-typeerror)
- [IR] **Breaking.** The IR now records a `Decimal` field as `"type": "Decimal"` with its `precision` and `scale`, where it recorded `String` and dropped both. The schema moved to `0.3.0`, so a committed baseline reports a version mismatch until you regenerate it. (#1723)
  **Migration:** [The IR schema is now v0.3.0](https://docs.proteanhq.com/reference/migration/v0-18/#the-ir-schema-is-now-v030)
- [Broker] **Breaking.** The Redis broker's `dlq_inspect()`, `dlq_replay()`, `dlq_replay_all()`, `dlq_purge()` and `dlq_depth()` no longer treat every Redis `ResponseError` as an empty DLQ; anything other than a missing stream or a malformed `dlq_id` reaches the caller. (#1730)
  **Migration:** [Some internal fallbacks let unexpected errors through](https://docs.proteanhq.com/reference/migration/v0-18/#some-internal-fallbacks-let-unexpected-errors-through)
- [Observability] **Breaking.** A domain with no environment variable set (`PROTEAN_ENV`, `ENV` and `ENVIRONMENT` all unset) now logs at INFO with colored console output instead of DEBUG; only an explicit `development` value selects DEBUG. (#1747)
  **Migration:** [A domain with no environment set logs at INFO](https://docs.proteanhq.com/reference/migration/v0-18/#a-domain-with-no-environment-set-logs-at-info)
- [IR] **Breaking.** `diff_ir()` now applies the compatibility report's field rules to published events, so a field that changes type, or a required field added without a default, is listed as a contract break. (#1781)
  **Migration:** [`diff_ir()` checks every field of a published event](https://docs.proteanhq.com/reference/migration/v0-18/#diff_ir-checks-every-field-of-a-published-event)
- [CLI] Runtime messages no longer contain em-dashes, across `protean check` diagnostics, `protean dx`, `protean ir`, git-hook output, CLI table titles and some exception and log messages. A script matching the exact text of one of these needs the new wording. (#1863)
  **Migration:** [Diagnostic and CLI messages no longer contain em-dashes](https://docs.proteanhq.com/reference/migration/v0-18/#diagnostic-and-cli-messages-no-longer-contain-em-dashes)
- [Event store] **Behavioural break, synchronous processing only.** Under `event_processing = "sync"`, an `ExpectedVersionError` from an event handler now reaches the caller as a `TransactionError` with it as `__cause__`, instead of triggering the command handler's version retry and saving the command's writes a second time. (#1883)
  **Migration:** [A synchronous event handler's version conflict no longer reruns the command](https://docs.proteanhq.com/reference/migration/v0-18/#a-synchronous-event-handlers-version-conflict-no-longer-reruns-the-command)

### Deprecated

- [Database] Deprecated the patch-and-persist API: `DAO.update()` and `QuerySet.update()` now emit a `RemovedInProtean020Warning` and are removed in 0.20.0. Load the aggregate, call a behaviour method, and persist with `repository.add()`. (#1260)
- [Server] Deprecated the `debug` argument on `Supervisor` and `Reloader`, removed in 0.20.0; pass `log_level="DEBUG"` instead. Both classes also take `log_format` and `log_config`. (#1639)
- [Handlers] Deprecated a `sequential_by` value on a process manager that is not a boolean: `domain.init()` now emits a `RemovedInProtean020Warning` and stores it as a boolean, and the value raises in 0.20.0. (#1787)
  **Migration:** [A non-boolean `sequential_by` on a process manager is deprecated](https://docs.proteanhq.com/reference/migration/v0-18/#a-non-boolean-sequential_by-on-a-process-manager-is-deprecated)
- [Internals] Twelve deprecations that said they would be removed in 1.0.0 now name a planned release, with new `RemovedInProtean019Warning` and `RemovedInProtean020Warning` classes, and `protean check` reports the new versions. (#1868)

### Removed

- [Scaffold] Removed the `logging.toml` that `protean new` generated at the project root. Nothing in the framework read it; `[logging]` in `domain.toml` is the one config Protean loads. (#1320)
- [Database] **Breaking.** Removed the `database_model` option from `@domain.aggregate`, `@domain.entity` and `@domain.projection`, and from `domain.register()`; it never had any effect. Register a custom model with `@domain.database_model(part_of=<Element>)` instead. (#1607)
  **Migration:** [The `database_model` element option is removed](https://docs.proteanhq.com/reference/migration/v0-18/#the-database_model-element-option-is-removed)
- [Testing] **Breaking.** Removed `protean.testing.assert_valid` and `assert_invalid`, deprecated since 0.16.1, along with the `RemovedInProtean018Warning` class. Use `pytest.raises(ValidationError, match=...)` in place of `assert_invalid`. (#1622)
  **Migration:** [`assert_valid` and `assert_invalid` are removed](https://docs.proteanhq.com/reference/migration/v0-18/#assert_valid-and-assert_invalid-are-removed)

### Fixed

- [Scaffold] Fixed the generated example project failing `domain.init()` and `protean check`: the scaffold shipped package re-exports that broke traversal, a missing-module import, an aggregate referenced by name instead of class, and no identifier field. (#1316)
- [Scaffold] Fixed the scaffold's `.env.example`, `README.md` and `docker-compose*.yml` setting the unread `LOG_LEVEL`/`LOG_FORMAT` instead of `PROTEAN_LOG_LEVEL`, so the documented env override never took effect. (#1320)
- [CLI] Fixed the `protean` CLI failing to start on a core-only install with `ModuleNotFoundError: No module named 'click'`; the `observatory` command's import is now lazy. (#1465)
- [CLI] **Breaking.** `protean new .` and `protean new ..` now raise `ValueError`. Both passed validation before and produced a project that could not be installed. (#1466)
  **Migration:** [`protean new .` and `protean new ..` are rejected](https://docs.proteanhq.com/reference/migration/v0-18/#protean-new-and-protean-new-are-rejected)
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
- [DX] Fixed the aggregate, entity, value-object and add-field skills and the entities and value objects guides, so every example meant to run now runs: decorator options only, keyword association helpers, an `Identifier` field instead of a `Reference`, and `add()` instead of the non-existent `save()`. (#1675)
- [DX] Fixed the event, command, add-event, add-command, add-use-case, event-sourced-aggregate and upcaster skills: commands catch `ValidationError`, events are raised from a factory classmethod, upcasters register with `@domain.upcaster`, and fact events go through `fact_events=True`. (#1676)
- [DX] Fixed the command-handler, event-handler, application-service, domain-service, add-domain-service-flow, repository and message-enrichment skills, so every non-fragment example runs and `check` finds no unexpected warning on their assets. (#1677)
- [DX] Fixed the skills, the pack rules and the event handlers guide teaching more than one way for one aggregate to react to another's event; the handler that listens on another cluster's stream now appears only as a mistake to avoid. (#1678)
- [DX] Fixed the projection, projector, query-handler, add-read-model, subscriber and process-manager skills and the projectors and process managers guides, so every example meant to run now runs. (#1679)
- [DX] Fixed the generate-test-scaffold, audit-domain, add-validation and refactor-extract-value-object skills, so every example meant to run now runs. (#1680)
- [DX] Rewrote the api-endpoint skill on `protean.integrations.fastapi`: one `create_app(domain)` factory, plain `def` endpoints so the blocking call runs in FastAPI's thread pool, and the status code and body for each exception the handlers map. (#1681)
- [DX] Fixed the add-saga-flow, add-subscriber-flow, custom-validator and query skills, so every example now runs without error. (#1764)
- [DX] Fixed the extract-bounded-context, refactor-introduce-events, refactor-move-logic-to-aggregate and split-aggregate skills, so every non-fragment example now runs, each page defining the names its "after" code uses. (#1765)
- [IR] **Breaking.** `protean ir diff` now reports the changes that stop an event-sourced aggregate being rebuilt from its events: turning event sourcing on or off, moving its `stream_category`, pointing its identity at another field, and dropping an `@apply` handler while its event survives. (#841)
  **Migration:** [Replay hazards on an event-sourced aggregate are now breaking](https://docs.proteanhq.com/reference/migration/v0-18/#replay-hazards-on-an-event-sourced-aggregate-are-now-breaking)
- [Broker] **Breaking.** Reconciled the subscription and InlineBroker retry and DLQ layers so a subscription owns retry and dead-lettering end to end; the subscription's `{stream}:dlq` is now the single dead-letter destination for the streams it consumes. (#1265)
  **Migration:** [The InlineBroker no longer dead-letters a message its subscription owns](https://docs.proteanhq.com/reference/migration/v0-18/#the-inlinebroker-no-longer-dead-letters-a-message-its-subscription-owns)
- [Cache] Fixed the memory cache's `remove`, `remove_by_key` and `set_ttl` raising `KeyError` on an absent key, where the Redis cache has always been silent, so the same call meant different things on each adapter. (#1391)
  **Breaking (memory cache only).** Code that used the `KeyError` as a presence check no longer takes its `except` branch, and the call succeeds quietly. Nothing inside Protean relied on it.
  **Migration:** [The memory cache no longer raises on an absent key](https://docs.proteanhq.com/reference/migration/v0-18/#the-memory-cache-no-longer-raises-on-an-absent-key)
- [Cache] Fixed Redis' `remove_by_key_pattern` raising when a pattern matches no keys; it now skips the delete, matching the in-memory adapter's silent no-op. (#1399)
- [IR] Fixed `protean ir diff` downgrading an event's breaking changes to safe on upcaster coverage it has not earned; a bump is covered only when every version still in the event store reaches the new one. (#1572)
- [Database] Fixed `@domain.repository(database="mssql")` and `database="mysql"` being rejected, because the validating `Database` enum listed only elasticsearch, memory, postgresql and sqlite. (#1580)
- [Database] **Breaking.** A `RawIndex` that names a dialect the framework renders no index DDL for now raises `IncorrectUsageError` at `Domain.init()`, where it was accepted and then silently dropped at every call site. (#1585)
  The same name check now guards the rendering path. `protean schema render --indexes --dialects=<name>` rejects a name outside the set, where `--dialects=oracle` used to write a file of SQLite DDL.
  **Migration:** [A RawIndex with an unknown dialect now raises](https://docs.proteanhq.com/reference/migration/v0-18/#a-rawindex-with-an-unknown-dialect-now-raises)
- [Database] **Breaking.** An element with `identity_type = "integer"` now builds its model on the SQLAlchemy providers, where it raised `TypeError: Integer() takes no arguments`; an integer identity under the `uuid` strategy is refused at `Domain.init()`, since no SQL integer column holds a 128-bit number. (#1586)
  **Migration:** [An integer identity under the `uuid` strategy is refused on SQL](https://docs.proteanhq.com/reference/migration/v0-18/#an-integer-identity-under-the-uuid-strategy-is-refused-on-sql)
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
  **Breaking.** `[lint]` settings now apply, so `protean check` can start failing on a project that used to pass, and a malformed `[lint]` value now fails `check` and `verify` instead of being ignored. `[observatory] trace_retention_days` applies too.
  **Migration:** [The lint and observatory tables now load](https://docs.proteanhq.com/reference/migration/v0-18/#lint-and-observatory-tables-now-load)
- [Internals] Fixed the deprecation warnings for `is_event_sourced=`, the `published` command option and email element registration pointing at Protean's own registration code instead of the line in your code. (#1630)
- [Testing] Fixed `DomainFixture.domain_context()` resetting whichever domain was current at exit rather than its own, so a test that left another domain's context pushed wiped that other domain. (#1634)
- [Observability] **Breaking.** Single-worker `protean server` and `protean observatory` now apply the `[logging]` section of `domain.toml`; they used to set up console logging before the domain loaded, which made `Domain.init()` skip its own setup. (#1635)
  **Migration:** [`protean server` and `protean observatory` apply the logging section](https://docs.proteanhq.com/reference/migration/v0-18/#protean-server-and-protean-observatory-apply-logging)
- [Observability] Fixed log records from child loggers reaching the root logger's handlers without `correlation_id` and `causation_id`, and without `[logging].redact` masking; Protean's filters now attach to the root handlers too. (#1636)
- [Observability] Fixed `--log-level`, `--log-format` and `--log-config` not reaching the worker processes of `protean server --workers N` and `--reload`. (#1639)
- [Event store] Fixed `protean outbox reconcile` and the server's startup reconcile creating outbox rows for messages the domain never outboxes, then publishing them; it now repairs only events raised by this domain's aggregates on the reconciled provider. (#1648)
- [Docs] Fixed the `protean upgrade-check` reference and the 0.17 migration guide not stating what the Unit of Work source checks cover: explicit `with UnitOfWork()` blocks only, not the one `@handle` and `@use_case` methods run in. (#1652)
- [Event store] Fixed outbox reconciliation restoring only the internal-broker row of a `published` event, so the event never reached the brokers in `[outbox].external_brokers`. (#1653)
- [Observability] Fixed multi-worker and `--reload` workers logging at INFO until their domain loaded, so `PROTEAN_LOG_LEVEL=DEBUG` lost the DEBUG lines written during the load. (#1658)
- [Broker] Fixed an idle subscription with priority lanes on and the Redis Streams broker logging `broker.redis.read_blocking_failed` every 5 seconds and holding up its backfill lane; its non-blocking check sent `BLOCK 0`, which means wait forever. (#1660)
  **Breaking.** On the Redis broker, `read_blocking(timeout_ms=0)` used to wait until a message arrived and now returns at once. The `blocking_timeout_ms` subscription setting must be positive, and `0` raises `ConfigurationError` at startup.
  **Migration:** [A zero read timeout on Redis no longer waits](https://docs.proteanhq.com/reference/migration/v0-18/#a-zero-read-timeout-on-redis-no-longer-waits)
- [CLI] Fixed `protean verify` taking its test counts from the first `<N> passed` or `<N> failed` text anywhere in pytest's output, so a message such as `port 15432 failed` could replace the real counts. (#1661)
- [Fields] Fixed an aggregate whose `@invariant.pre` rejects its current state failing to save when it has an `auto_now` field or a registered enricher; those save-time writes no longer run the pre-invariants. (#1663)
- [Observability] Fixed the stdlib redaction filter running before Protean's correlation and trace-context filters, so listing `correlation_id` or `trace_id` in `[logging].redact` left those record attributes unmasked for other formatters. (#1666)
- [Internals] **Breaking.** A `ValueError` raised while a unit of work commits is no longer reported as a version conflict; it raises `TransactionError` with the `ValueError` as its `__cause__`, so a handler's version retry no longer runs the handler again for it. (#1682)
  **Migration:** [A `ValueError` at commit is no longer reported as a version conflict](https://docs.proteanhq.com/reference/migration/v0-18/#a-valueerror-at-commit-is-no-longer-reported-as-a-version-conflict)
- [Check] Fixed `AGGREGATE_TOO_LARGE` saying it counts fields when it counts the entities in a cluster, and `COMMAND_NOT_IMPERATIVE` reporting ordinary commands such as `CloseTicket` and `MakeDeposit`. (#1683)
- [Fields] Fixed building an element from only some of a value object's flattened arguments: Protean filled every missing argument with `None`, so `Customer(billing_address_street="1 Main St")` failed when `Address` had a field that does not accept it. (#1686)
  **Breaking.** A value object field that accepts `None` but defaults to something else, such as `city: str | None = "Unknown"`, now gets its default when you leave out its flattened argument. Pass `None` explicitly to keep the old value.
  **Migration:** [An omitted value object argument gets the value object's default](https://docs.proteanhq.com/reference/migration/v0-18/#an-omitted-value-object-argument-gets-the-value-objects-default)
- [Observability] Fixed the observatory failing a trace endpoint or stopping the live trace stream on a malformed trace entry; it now skips the entry and keeps reading, and a `duration_ms` that is infinite or NaN is left out of the latency figures instead of answering 500. (#1715)
- [Internals] Fixed some server, observatory, subscription and retry paths dropping errors without a trace; they now log them, at debug level for a skipped scrape and at warning for a failed cleanup, an invalid `server.version_retry` or an IR build that fails inside `Domain.check()`. (#1716)
- [DX] Fixed the persistence and handler rules telling agents to use `self.repository`, which handlers do not have; their examples now get a repository with `current_domain.repository_for(...)`. (#1736)
- [DX] Fixed the add-validation skill storing money as `Float`, so an order with subtotals of 0.1 and 0.2 and a total of 0.3 failed its own invariant; money fields are now `Decimal(precision=19, scale=4)`. (#1737)
- [Event store] **Breaking.** Saving the same aggregate instance again in a later transaction, without reloading it, now writes a new version. Before, the second save wrote the version the instance already had, so handlers that deduplicate by event id dropped the second event. (#1744)
  After a commit, `_version` and `_next_version` on each saved instance match what a reload returns; after a rollback, each instance gets back the version it had before the transaction.
  Inside a `UnitOfWork`, a `get()` or query of an aggregate the transaction has already loaded or saved returns that same instance with any changes made since, where each read used to build a new copy and lose events raised on an earlier one.
  Event-sourced aggregates track their versions from their events, so the version changes above do not apply to them.
  A fact event no longer moves the position of the aggregate's own event stream, so saving an instance of an aggregate with `fact_events=True` a second time no longer raises `ExpectedVersionError`.
  **Migration:** [Saving the same aggregate instance again writes a new version](https://docs.proteanhq.com/reference/migration/v0-18/#saving-the-same-aggregate-instance-again-writes-a-new-version)
- [Fields] Fixed a failed post-invariant leaving the change that broke it in place; the field keeps its previous value and the entity's changed flag goes back, across every field kind and `add_`/`remove_` call, and a failed check at the end of an `atomic_change` block undoes every change made in it. (#1746)
- [Docs] Fixed the FastAPI lifespan recipes not calling `domain.close()` in a `finally` block, so provider, broker, cache and event store connections leaked when the app exited through an exception. (#1777)
- [IR] Fixed `domain.to_ir()` failing with a `TypeError` when a field declares a `decimal.Decimal` `min_value` or `max_value`; a decimal bound on a `Decimal` field now goes into the IR as a decimal string. (#1780)
- [IR] Fixed the v0.3.0 schema leaving `sequential_by` undeclared, so a validator that refuses undeclared keys rejected any IR that set it. (#1787)
- [Event store] Fixed an event or command rebuilt from a stored message taking the handled message's `correlation_id` or `causation_id` when its own stored value was empty. (#1789)
- [Database] **Breaking.** A field declared with `choices` now gets the column type its choice values share, so an `Integer` with `choices` loads back as an `int` and a `String` with string choices keeps its `max_length` instead of becoming `TEXT` on MySQL. (#1791)
  **Migration:** [`choices` fields map to their declared column type](https://docs.proteanhq.com/reference/migration/v0-18/#choices-fields-map-to-their-declared-column-type)
- [Observability] Fixed each worker's queue handler under `--workers N` masking only the first redaction filter on the root logger, so keys from a second `configure_logging()` call left the worker unmasked. (#1803)
- [Internals] Fixed a possible segmentation fault at shutdown on Python 3.11 for a process that held stored messages until exit; datetimes Protean parses now carry a `datetime.timezone` instead of pydantic-core's own `TzInfo`. (#1806)
- [Event store] Fixed an event or command rebuilt from a stored message losing its stored `origin_stream` and taking the handled message's instead. (#1812)
- [Database] Fixed a QuerySet evaluated in one `UnitOfWork` handing out cached copies when read in a different transaction; it now runs its query again, so events raised on a copy are no longer lost. (#1842)
- [Cache] Fixed `RedisCache.flush_all()` sending `FLUSHALL`, which emptied every database on the server; it now sends `FLUSHDB`. (#1880)
  **Migration:** [`flush_all()` on a Redis cache clears only its database](https://docs.proteanhq.com/reference/migration/v0-18/#flush_all-on-a-redis-cache-clears-only-its-database)
- [Server] Fixed the multi-worker Supervisor killing a worker mid-drain; its shutdown budget is now the drain window plus 5 seconds, never less than 30. It also finds the project config for a dotted `--domain`. (#1896)
  **Migration:** [The multi-worker Supervisor waits for the drain window](https://docs.proteanhq.com/reference/migration/v0-18/#the-multi-worker-supervisor-waits-for-the-drain-window)
- [Fields] **Breaking.** A value object's string `part_of` now resolves to the aggregate class at `domain.init()`, so `IRBuilder(domain).build()` no longer raises `AttributeError` for one that no `ValueObject` field embeds, and a `part_of` naming no aggregate is rejected. (#1897)
  **Migration:** [A value object's string `part_of` must name an aggregate](https://docs.proteanhq.com/reference/migration/v0-18/#a-value-objects-string-part_of-must-name-an-aggregate)
- [Server] Fixed the engine running outbox processors for every managed provider, including `memory` and providers that hold only projections, whose outboxes nothing writes to. (#1923)

### Security

- [Scaffold] **Breaking, symlinked targets only.** `protean new` refuses a target directory that resolves outside the output directory. A symlinked `<output-dir>/<name>` used to be followed, so `--force` cleared files at the link target and the render wrote them there. (#1466)
  **Migration:** [`protean new` refuses a target symlinked out of the output directory](https://docs.proteanhq.com/reference/migration/v0-18/#protean-new-refuses-a-target-symlinked-out-of-the-output-directory)

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

Read the [0.17 migration guide](https://docs.proteanhq.com/reference/migration/v0-17/) before you upgrade. These changes can need action, in the order the guide covers them:

<details markdown="1">
<summary>14 breaking changes, in the order the guide covers them</summary>

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

- Add Redis broker DLQ management tests (`dlq_list`, `dlq_inspect`, `dlq_replay`, `dlq_replay_all`, `dlq_purge`, `dlq_trim`, `dlq_depth`) against real Redis, backfilling coverage for the `_client` accessor refactor in #1086. (#1090)

### Fixed

- Fix foreign-key violations when persisting an aggregate with `HasMany`/`HasOne` children in one `repository.add` inside a `UnitOfWork`. The parent row is now flushed into the transaction before its FK-referencing children are written, so databases that enforce foreign keys immediately (MSSQL, MySQL/InnoDB, SQLite with `PRAGMA foreign_keys=ON`) accept the child inserts. Child-bearing aggregate saves now emit their buffered SQL at flush time rather than only at commit, so any constraint violation on such a save may surface at `add()` time instead of `commit()` time. (#1043)
- The Redis Streams broker now transparently reconnects if its connection was closed (e.g. `redis_instance` set to `None` by engine shutdown) before a later operation runs, instead of raising `AttributeError: 'NoneType' object has no attribute ...` and killing a subscription's poll loop. This makes `Engine(test_mode=True).run()` against a Redis broker reliable in CI. (#1055)
- Fix re-running `domain.init()` in a live process closing the running brokers out from under the Engine, which permanently halted message consumption (with the Redis broker, an unrecoverable flood of `AttributeError: 'NoneType' object has no attribute 'xreadgroup'`). This surfaced in a process that both runs the Engine and re-initializes the domain — e.g. an APScheduler cron job calling `domain.init()` on every tick. `Brokers._initialize()` is now non-destructive: a broker whose configuration is unchanged is reused in place rather than closed and recreated, so the instance the Engine holds stays alive. Only brokers whose configuration changed, or that are no longer configured, are closed. Regression from #885 (0.16.0), whose broker cleanup turned a previously-silent connection leak on re-init into a hard, consumption-halting crash. (#1213)

## [0.16.2] - 2026-07-05

### Fixed

- Fix `datetime` values in serialized payloads being encoded with `str()` (a space-separated form) instead of ISO-8601. Datetime fields now serialize with `.isoformat()`, matching the message-metadata timestamp format. The naive/aware distinction and the UTC offset are preserved, so the instant round-trips unchanged (a named timezone is serialized as its fixed offset). This only affected real JSON-backed stores (event store, Elasticsearch, outbox); the in-memory adapter was unaffected. Records written before the fix remain readable (`datetime.fromisoformat()` and Pydantic parse both forms). (#1039)
- Fix a `Date` (`datetime.date`) field on a command or event raising `TypeError: Object of type date is not JSON serializable` when the message is processed. `ResolvedField.as_dict` now serializes plain `date` values to ISO-8601 strings; previously only `datetime` had a branch, so a raw `date` reached the checksum's `json.dumps` and failed. (#1046)
- Fix `repository.add()` leaving an `Auto(increment=True)` identity as `None` for stores that assign the value during create (e.g. the in-memory provider). The generated value is now reflected back onto the aggregate instance after `add()`, restoring parity with `dao.create()`. (#1056)
- Fix a DB-assigned `Auto(increment=True)` identifier not being reflected back onto the aggregate when persisting through a relational adapter (SQLAlchemy → Postgres/SQLite/MSSQL). After `repository.add()` (or `dao.create()`) the generated primary key now populates the original instance, including when the persist runs inside an outer `UnitOfWork`, instead of staying `None` until commit. Because reflecting the value forces the insert to flush early, a constraint violation on such an insert may now surface at `add()`/`create()` time rather than only at commit. (#1059)
- Fix an embedded `ValueObject` whose fields hold default/falsy values (e.g. all zeros) being reconstructed as `None` after persist + reload. Presence was gated on truthiness — and such a VO is falsy — so it was reset to `None` on assignment and dropped from serialization. Presence is now decided by identity (`is not None`), so an explicitly-assigned VO round-trips to an equal VO across the in-memory, relational, and Message-DB adapters (and on event-sourced aggregates); an unset VO still reads back as `None`. Note: `bool(vo)` still reports an all-default VO as falsy (check presence with `agg.vo_field is not None`), and a VO whose every field is `None` still reads back as `None` from flattened storage. (#1078)
- Enforce `Index(unique=True)` declarations in the in-memory repository. A save or update that violates a single-column or composite unique index now raises `ValidationError` (the same error already raised for field-level `unique=True`), so memory-mode tests catch duplicate-key regressions instead of silently accepting them. NULLs are treated as distinct, matching PostgreSQL/SQLite semantics. (#1071)
- Make `Outbox.target_broker` NOT NULL so a NULL row can no longer bypass the `(message_id, target_broker)` unique index — the dual-write idempotency guard (NULLs compare as distinct in a unique index, silently reopening the duplicate-publish window). It now defaults to the internal broker name; the framework always sets it on write, and legacy rows with a NULL `target_broker` are coerced to the default broker name on read. (#1041)
- `protean upgrade-check` now diffs a live outbox table for the intra-0.16 structural migrations it previously missed: a nullable `target_broker` (emitting the backfill + `SET NOT NULL`) and a legacy `message_id`-only unique index (emitting the composite-index swap), alongside the existing VARCHAR-bounds check. The [v0.16 migration guide](docs/reference/migration/v0-16.md) gains the matching `target_broker` NOT NULL recipes. (#1093)
- Fix projectors rejecting the `retries`, `backoff`, and `retry_exceptions` options with `Unknown option(s)`. Projectors now accept them for per-projector transient-failure retry, mirroring event and command handlers. (#1076)
- Fix `protean check` raising a `PROJECTION_WITHOUT_PROJECTOR` false positive for projections populated by a subscriber or event handler (the anti-corruption-layer / cross-domain pattern) rather than a co-located `@projector`. Declare such projections with `@domain.projection(externally_populated=True)` to record that they are populated externally and suppress the warning. (#1013)

### Upgrade Notes

- **Outbox `target_broker` NOT NULL (#1041).** New deployments get a `NOT NULL target_broker` column automatically. Existing deployments keep their current (nullable) column — Protean does not auto-alter tables — and continue to read any legacy NULL rows safely. To enforce the constraint on an existing database, backfill and add it manually, e.g. `UPDATE outbox SET target_broker = 'default' WHERE target_broker IS NULL;` followed by an `ALTER TABLE ... ALTER COLUMN target_broker SET NOT NULL`.

## [0.16.1] - 2026-06-30

### Added

- `OutboxRepository.find_all_by_message_id(message_id)` returns every outbox row sharing a `message_id`, and `OutboxRepository.find_by_message_id` gained an optional `target_broker` argument. A published event is dual-written once per target broker, so a single `message_id` can map to several rows; the new method returns them all, and the new argument selects a specific broker's row. (#1009)

### Deprecated

- Restored `assert_valid` and `assert_invalid` in `protean.testing` as deprecated shims. They were removed in 0.16.0 without a deprecation cycle, breaking downstream test suites at import time; they now emit a `DeprecationWarning` and will be removed in v0.18.0. Prefer `pytest.raises(ValidationError, match=...)` for invariant tests. (#1011)

### Fixed

- CLI commands no longer corrupt their machine-readable stdout output with log lines: the console log handler now writes to stderr, so the JSON from `protean ir show` and `protean schema show --raw` is clean and safe to pipe. (#1010)
- The recommended unique index on the `Outbox` table is now composite over (`message_id`, `target_broker`) instead of `message_id` alone, and the framework now always writes a non-NULL `target_broker` (the internal broker name) so the composite uniqueness is effective on every dialect. A single published event is dual-written to the outbox once per target broker (the internal broker plus every external broker), so a unique index on `message_id` alone rejected the framework's own multi-broker dual-write with a `UniqueViolation`; leaving `target_broker` NULL would have defeated `message_id` idempotency on PostgreSQL and SQLite, which treat NULLs as distinct in a UNIQUE index. (#1009)
- Fixed `protean ir check` falsely reporting a domain as stale after a framework upgrade that only changes the IR schema version. The staleness checksum now covers domain content only (excluding `$schema`, `ir_version`, `generated_at`, and `elements`), matching what `ir diff` compares, so the two commands agree. Baselines materialized before this fix report stale once; regenerate them with `protean ir show` to refresh. (#1012)
- Fixed `@handle("$any")` event handlers not firing under `event_processing="sync"`. Wildcard handlers now run during synchronous dispatch, matching their behaviour under the async engine. (#1023)
- Fixed per-field `validators=[...]` running against `None` on optional fields. An optional field with a format validator (e.g. `String(validators=[RegexValidator(...)])`) raised a spurious error when simply left unset, because the validator ran on `None`. Empty values now short-circuit per-field validators, matching the legacy field system and the documented execution order (empty → choices → cast → validators). (#1025)
- Fixed `domain.create_snapshots(Aggregate)` failing for event-sourced aggregates declared with `fact_events=True`. The bulk snapshot API mistook the aggregate's `{category}-fact-{id}` fact-event streams for real instances and raised `IncorrectUsageError` (fact events have no `@apply` handler). `create_snapshots` now skips those fact-event streams for fact-event-enabled aggregates. (#1028)
- Fixed database setup failing for domains that mix a SQLAlchemy provider with a cache-backed projection. `_create_database_artifacts` tried to build a SQL table for cache-backed projections (whose provider is `None`), raising `ConfigurationError: No provider configured with name 'None'` and aborting setup for the whole domain. Cache-backed projections are now skipped, since they persist to a cache rather than a database table. (#1034)

### Upgrade Notes

- **Outbox unique index (#1009).** If you run the outbox on a SQL store (PostgreSQL, SQLite, MySQL, or SQL Server), migrate the unique index from `message_id` to the composite `(message_id, target_broker)`: drop `uq_outbox_message_id`, backfill any rows where `target_broker IS NULL` to your internal broker name (default `"default"`), then create the composite unique index. Per-dialect SQL is in the [v0.16 migration guide](docs/reference/migration/v0-16.md). In-memory and Redis brokers are unaffected.

## [0.16.0] - 2026-06-29

### Added

- Observatory `/domain` page (the Domain Visualizer, #874): sidebar navigation and a `GET /api/domain/ir` endpoint that transforms the domain IR into a D3-ready graph structure (nodes, cross-aggregate links, clusters, flows, projections, stats).
- Observatory D3 force-directed aggregate topology graph on the `/domain` Topology tab. Interactive visualization with aggregate nodes showing name, stream category, ES/CQRS badge, and element counts; directed edges for cross-aggregate event handlers and process managers; zoom/pan, drag-to-reposition, hover highlighting of connected nodes, click-to-detail panel, mini-map overview, and legend.
- Observatory `/domain` aggregate detail panel — slide-in panel with collapsible sections for fields, entities, value objects, commands, events, handlers, invariants, and repository/models.
- Observatory `/domain` Event Flows tab — an interactive D3 directed graph showing command-to-event-to-handler chains with cluster grouping, path highlighting, and element type filters.
- Observatory `/domain` Process Managers tab — a process manager state machine view, plus an enhanced domain stats summary.
- Observatory D3-based interactive causation graph for visualizing complex correlation chains. Adds a "Graph View" toggle alongside the existing CSS tree in the correlation view, with horizontal tree layout, zoom/pan, collapse/expand subtrees (Shift+click), hover path highlighting, cross-aggregate dashed links with latency labels, and click-to-detail. Auto-selects graph view for chains with depth > 2 or event count > 5.
- Observatory causation graph swimlane layout and fan-out polish: swimlane backgrounds grouped by stream category with colored headers and node accent bars, fan-out indicators showing branching multiplicity, timeline axis with elapsed time from root, color-coded legend (commands vs events, same vs cross-aggregate links, duration badges), progressive disclosure auto-collapsing deep branches for 50+ node chains, and a mini-map overview for navigating large graphs.
- Observatory live causation graph updates via SSE: when viewing a correlation chain, new messages with matching `correlation_id` animate into the D3 graph in real time. New nodes fade in with a highlight pulse, links animate smoothly, and all overlays (swimlanes, timeline axis, mini-map) refresh automatically. A "Live" badge appears when the chain has recent activity (< 30s). SSE events are debounced to 300ms to coalesce bursts.
- Observatory correlation view enhanced with handler attribution badges, processing duration badges, inter-step latency labels, and cross-aggregate boundary markers in the causation tree. New "End-to-End Duration" and "Streams Touched" summary stat cards added to the correlation view. Reuses `Observatory.fmt.duration()` for consistent formatting.
- Observatory "Traces" tab on the Timeline page with search inputs (aggregate ID, event type, command type, stream category), a recent traces list table, and deep-link support (`?view=traces&aggregate_id=...`). Each trace row navigates to the correlation chain view.
- Observatory trace search and recent traces API endpoints: `GET /timeline/traces/recent` returns the most recent correlation chains with summary statistics (correlation_id, root_type, event_count, started_at, streams), and `GET /timeline/traces/search` allows querying chains by aggregate_id, event_type, command_type, or stream_category. Both return `{traces: [...], count: int}`.
- Enrich `CausationNode` with `handler`, `duration_ms`, and `delta_ms` fields for waterfall/swimlane rendering in the Observatory. The correlation chain response now includes `total_duration_ms`. Handler and timing data are populated from Redis trace stream entries when available; all new fields gracefully fall back to `None` when trace data is unavailable. The CLI `protean events trace` command now displays handler names, processing durations, and inter-message latencies.
- `value_object_from_entity()` utility function that auto-generates a `BaseValueObject` subclass mirroring an entity's fields, eliminating manual field duplication for command/event payloads. Supports custom naming, field exclusion, and recursive conversion of `HasOne`/`HasMany` associations. Exported from `protean` top-level package.
- `ValueObjectFromEntity` field descriptor in `protean.fields` for inline use in commands and events, e.g. `List(content_type=ValueObjectFromEntity(OrderItem))`.
- `BaseEntity.from_value_object()` classmethod for converting value object payloads back into entity instances, completing the round-trip.
- Generic `replace(**kwargs)` method on `BaseValueObject` for creating copies with selected fields changed, similar to `dataclasses.replace()`. Rejects unknown field names and re-validates invariants on the new instance.
- `domain.correlation_trace(correlation_id)` method that returns a flat, causally-ordered list of `CausationNode` objects for a correlation chain. Thin wrapper over `build_causation_tree()` surfaced at the domain level for downstream test assertions.
- `assert_chain()` test helper in `protean.testing` for validating message type sequences in correlation chains. Accepts both string type names and domain element classes.
- Structured error payload enrichment with `correlation_id` in JSON body for all Protean exception handlers (`ValidationError`, `InvalidDataError`, `ValueError`, `ObjectNotFoundError`, `InvalidStateError`, `InvalidOperationError`). When a domain context is active via `DomainContextMiddleware`, error responses automatically include `correlation_id` matching the `X-Correlation-ID` response header. Routes outside domain context are unaffected.
- Graceful resource cleanup on Engine shutdown: `Domain.close()` shuts down all infrastructure adapters (event store, brokers, caches, providers) in reverse initialization order. `Engine.shutdown()` now waits for in-flight message handlers to complete (10s bounded timeout) before closing infrastructure. New `close()` methods on `BaseBroker`, `BaseCache`, `EventStore`, and `Providers` port/registry classes with Redis adapter implementations. Shutdown sequence and invariants captured in [ADR-0011](docs/adr/0011-engine-shutdown-and-resource-lifecycle-contract.md).
- Kubernetes-compatible health check endpoints for Engine and FastAPI applications. The Engine embeds a lightweight HTTP server with `/healthz` (liveness), `/livez` (alias), and `/readyz` (readiness) endpoints. For FastAPI apps, `create_health_router(domain)` provides equivalent endpoints as a reusable router. Readiness checks cover database providers, brokers, event store, caches, and subscription count. Configure via `[server.health]` in `domain.toml` (enabled by default on port 8080). Design captured in [ADR-0012](docs/adr/0012-health-check-architecture.md). **Default behaviour change — Tier 2 (operational-defaults exception per [ADR-0004](docs/adr/0004-release-workflow-and-breaking-change-policy.md#exception-operational-defaults))**: `protean server` now binds port 8080 on startup. The engine logs a warning and continues without probes if the port is already in use, so the change is non-fatal. Disable with `[server.health] enabled = false` or move with `[server.health] port = ...`.
- Development hot-reload mode for `protean server`. Pass `--reload` to watch the working directory for Python source changes and automatically restart the inner Engine process on every edit. Built on `watchfiles` (installed via the new `protean[dev]` extra); `.pyc`, `__pycache__`, `.venv`, `.git`, `node_modules`, and `.protean/` caches are ignored. `--reload` cannot be combined with `--workers > 1`.
- Per-subscription OTEL metrics for message processing. New counters: `protean.subscription.messages_processed` (with `status` ok/error), `protean.subscription.retries`, and `protean.subscription.dlq_routed` — all with `{subscription, handler, stream}` attributes. New histogram: `protean.subscription.processing_duration` for per-message latency. New engine observable gauges: `protean.engine.up`, `protean.engine.uptime_seconds`, and `protean.engine.active_subscriptions`. All metrics are no-op when OpenTelemetry is not installed.
- Connection pool and backpressure OTEL metrics: `BaseProvider.pool_stats()` with SQLAlchemy implementation, DB pool gauges (`protean.db.pool_size`, `protean.db.pool_checked_out`, `protean.db.pool_overflow`, `protean.db.pool_checked_in`), Redis broker pool gauge (`protean.broker.pool_active_connections`), and renamed backpressure metrics (`protean.outbox.pending_count`, `protean.subscription.consumer_lag`, `protean.subscription.pending_messages`). Metric collection is now shared between Observatory and the OTEL gauges.
- DLQ retention and alerting policies with configurable trimming, depth thresholds, per-subscription overrides, and OTEL counters (`protean.dlq.trimmed`, `protean.dlq.alerts`). Global defaults in `[server.dlq]` (`retention_hours`, `alert_threshold`, `alert_callback`, `check_interval_seconds`); per-subscription overrides via `dlq_retention_hours` and `dlq_alert_threshold` on `SubscriptionConfig`.
- Consolidated server hardening documentation: new how-to guide at [docs/guides/server/hardening.md](docs/guides/server/hardening.md) covering connection pool tuning, Kubernetes health probes, DLQ maintenance, subscription profiles, OTEL metrics, and graceful shutdown, plus a new reference page at [docs/reference/server/hardening.md](docs/reference/server/hardening.md) cataloguing every option, default, metric, and profile shipped by epic 5.1.
- `[logging]` configuration section in `domain.toml` and auto-configure logging during `Domain.init()`. Escape hatch via `PROTEAN_NO_AUTO_LOGGING=1` for applications that manage their own logging stack.
- Global `--log-level`, `--log-format`, and `--log-config` CLI options that apply to every `protean` subcommand (`server`, `test`, `shell`, `projection`, `snapshot`, `observatory`, `check`, `dlq`, `events`). All CLI commands are wrapped in a structured exception handler that logs failures before exiting.
- Wide event access log (`protean.access`) that emits one structured log entry per handled message with full domain context (aggregate, events raised, repo operations, UoW outcome, correlation/causation IDs). Slow-handler detection via the `protean.perf` logger. New `bind_event_context()` / `unbind_event_context()` public API lets application code enrich wide events with business-specific fields (user tier, order total, feature flags).
- OpenTelemetry `trace_id`, `span_id`, and `trace_flags` are injected into every log record when `telemetry.enabled=True`, enabling log↔trace correlation in Grafana Tempo, Honeycomb, Datadog APM, and other APM tools. New `OTelTraceContextFilter` (stdlib) and `protean_otel_processor` (structlog) are wired automatically by `Domain.configure_logging()`. Correlation extraction falls back to `g.correlation_id` / `g.causation_id` when no `g.message_in_context` is in scope — closing the "HTTP route logging before `process()`" and "CLI logging with `add_context`" gaps.
- `protean.adapters.repository.sqlalchemy.slow_query` WARNING events when a SQLAlchemy query exceeds the configured threshold, and `protean.adapters.repository.sqlalchemy.query` DEBUG events for every query (opt-in via level configuration). Events carry `statement`, `parameters`, `duration_ms`, and `threshold_ms`, and are truncated via `[logging].slow_query_truncate_chars` (default 500). Threshold comes from `[logging].slow_query_threshold_ms` (default 100ms).
- Opt-in tail sampling for wide events via `[logging.sampling]` in `domain.toml`. New `TailSamplingProcessor` (structlog) and `TailSamplingFilter` (stdlib) make keep/drop decisions on `protean.access` events by outcome — errors (`status="failed"` or level ≥ ERROR), slow requests (`status="slow"`), and message types matching `critical_streams` glob patterns are always kept; everything else is sampled at `default_rate` (5% by default). Kept events carry `sampling_decision`, `sampling_rule`, and `sampling_rate` so log aggregators can compute accurate throughput from sampled data. Non-access loggers are never affected.
- `protean.access.http` wide event — one per HTTP request — emitted by `DomainContextMiddleware` for FastAPI apps. Carries the request envelope (method, path, status, duration), route name/pattern, commands dispatched during the request, client IP, user agent, and both `request_id` (from `X-Request-ID` or auto-generated) and `correlation_id`. Level ladder: INFO for 2xx/3xx, WARNING for 4xx, ERROR for 5xx. Responses always echo `X-Request-ID` so operators can paste it into log aggregators to find the matching event. New `[logging.http]` config section (`enabled`, `exclude_paths`, `log_request_headers`, `log_response_headers`) tunes HTTP wide events declaratively. `bind_event_context()` bindings flow through the async task boundary and land on both the HTTP and domain layers with the shared `correlation_id`.
- ADR-0010 (`docs/adr/0010-logging-overhaul-and-wide-event-architecture.md`) capturing the full architectural story of the Logging Overhaul — the structlog pipeline bridge, wide event access log, `bind_event_context()` API, two-layer HTTP + domain wide events, opt-in tail sampling, auto-configuration on `Domain.init()`, log↔trace correlation, pipeline-level redaction, multi-worker log queue, and the `protean.security` channel — alongside alternatives considered and explicitly rejected.
- Projection staleness detection: the new `protean projection status` command reports, per projection, how far behind it is in time (staleness) and in events (lag), when it last advanced, and its current row count. A `protean.projection.staleness_seconds` gauge (Prometheus `protean_projection_staleness_seconds`) is exposed for monitoring and Observatory dashboards.
- Handlers can now auto-retry on transient infrastructure failures: configure `@domain.command_handler(retries=3, backoff="exponential")` (also on `@domain.event_handler`) or enable it domain-wide via `server.transient_retry`. Transient exceptions (`ConnectionError`, `TimeoutError`, `SendError` by default; overridable via `retry_exceptions`) are retried with a configurable backoff strategy (`exponential` | `linear` | `fixed`) before the error reaches the subscription retry/DLQ pipeline. This is distinct from the existing version (OCC) retry, which is specific to `ExpectedVersionError`; the two compose with independent attempt budgets. Each attempt runs in a fresh `UnitOfWork`, so a failed attempt rolls back cleanly before the retry. Retries respect the command deadline: when a command carries a timeout/deadline, the loop stops instead of sleeping into an attempt that would start past it, so a retrying handler never executes after its deadline. Opt-in and disabled by default — existing behavior is unchanged. Retries increment the `protean.handler.retried` metric.
- Commands now support deadlines: pass `deadline=<datetime>` or `timeout=<timedelta>` to `domain.process()`. The deadline is stored in command metadata, propagated to downstream commands in the same causal chain, and checked before a handler runs — expired commands are rejected with `CommandExpiredError` (sync) or skipped without retry (async), preventing stale commands from executing after long queue delays. A default validity window can be configured per command handler (`@domain.command_handler(timeout=...)`) or domain-wide (`command_default_timeout` in config); both default to disabled. Expiries increment the `protean.command.expired` metric.
- `Q(field__isnull=True/False)` lookup for IS NULL / IS NOT NULL predicates, supported by SQLAlchemy, Memory, and Elasticsearch adapters. `isnull` is part of the required lookup set (`BaseProvider.REQUIRED_LOOKUPS`), so custom adapters must register it; a missing `isnull` lookup produces the standard missing-lookup warning at domain init.
- `QuerySet.count()` issues a flat `SELECT COUNT(*)` (or adapter equivalent) without projecting columns or materializing entities.
- `QuerySet.all(with_total=False)` skips the adapter's total-count round-trip (a separate wrapped `COUNT` query on SQLAlchemy) when only `ResultSet.items` is needed. The outbox finder/poll path uses it so each poll issues a single `SELECT`.
- `outbox.max_tick_interval` config option enables adaptive polling backoff in `OutboxProcessor`: empty polls double the wait up to the cap, non-empty batches reset to the base `tick_interval`. Defaults to `None` (constant-rate polling).
- `BaseDAO._claim()` — an atomic find-and-claim primitive for queue-style consumers (the outbox, and future high-throughput consumers). Adapters may override it with a faster dialect-specific path; the SQLAlchemy adapter does so for PostgreSQL (single `UPDATE … FOR UPDATE SKIP LOCKED … RETURNING`), and the in-memory adapter serializes claims under its provider lock. All other backends use a correct portable default.
- Portable `Index` declarations on aggregates and entities via the `indexes=` decorator option. Supports composite, descending, unique, partial (`where=Q(...)`), and covering (`include=`) indexes, with an `Index.from_sql(dialect, ddl)` escape hatch for dialect-specific DDL. SQLAlchemy providers emit the indexes at table build; unsupported opt-ins fall back to a full index with a warning. The `Outbox` aggregate now ships recommended indexes (active-set partial, unique `message_id`, `correlation_id`). New `protean schema render --indexes` command renders per-dialect `CREATE INDEX` DDL to `.protean/schemas/`. See ADR-0014.
- Added `F()` expressions for column-to-column comparisons inside `Q` lookups (e.g. `filter(retry_count__lt=F("max_retries"))`). Resolved natively by the in-memory and SQLAlchemy adapters; the Elasticsearch adapter raises `NotImplementedError` for `F()`-bearing predicates. The outbox poll and claim now push the `retry_count < max_retries` check into the database.
- `QuerySet.only(*fields)` projects a query to a subset of persisted columns (the identifier is always included), returning read-only `Record` objects instead of fully materialized entities. This avoids loading large columns — JSON blobs in particular — on read-optimized paths like counts, cleanups, and statistics. A `Record` is inert: it is not a domain entity, runs no invariants, and cannot be persisted, so projections never produce a partially-valid aggregate. Honored natively by every adapter (SQLAlchemy `load_only`, Elasticsearch `_source`, in-memory).
- `BaseDAO._delete_top(criteria, limit, order_by=None)` deletes up to `limit` matching rows and returns the count, so high-volume cleanups run in bounded batches instead of one unbounded `DELETE` that holds locks and bloats the transaction log. SQLAlchemy issues a single `DELETE … WHERE id IN (SELECT … LIMIT n)` on PostgreSQL/SQLite/MSSQL (portable select-then-delete-by-id elsewhere); Elasticsearch uses `delete_by_query` with `max_docs`; the in-memory store removes under its lock. `OutboxRepository.cleanup_old_published` / `cleanup_old_abandoned` now delete in batches sized by `[outbox.cleanup].batch_size` (default 5000, configurable), committing each batch before the next so a large backlog clears without one long-held lock.
- Brought the `any` and `overlap` array lookups to the Elasticsearch adapter (rendered as `terms` queries) and added `overlap` to the in-memory adapter, so array-membership filters behave consistently across backends. Documented the per-adapter lookup support matrix.
- Added query-shape test primitives `assert_query_count`, `assert_no_subquery_wrap`, and `assert_no_overfetch` to `protean.integrations.pytest`. These context managers observe the SQL a block issues and fail on query-cost regressions (extra round trips, subquery-wrapped counts, over-fetching). They are no-ops on the in-memory adapter and assert against a real SQLAlchemy backend.
- `protean upgrade-check` — a read-only CLI diagnostic that inspects a domain (and its live database schema) and reports the changes needing attention when upgrading to 0.16: raised SQLAlchemy pool defaults, the health-check port binding, the Elasticsearch v8-client/server requirement, and unbounded outbox columns. For the outbox it generates the exact backend `ALTER` SQL to review and run; nothing is applied automatically.

### Changed

- Surface connection pool configuration in `domain.toml` with production-sensible defaults. SQLAlchemy pool defaults raised to `pool_size=5` and `max_overflow=10` for PostgreSQL and MSSQL (previously `pool_size=2`, `max_overflow=5`). Redis broker, Redis cache, and MessageDB event store now forward pool parameters (`max_connections`, `socket_timeout`, etc.) from `conn_info`. A `LOW_POOL_SIZE` warning is emitted during domain validation when `pool_size` is set below 5. **Breaking change — Tier 2 (operational-defaults exception per [ADR-0004](docs/adr/0004-release-workflow-and-breaking-change-policy.md#exception-operational-defaults))**: a deployment that previously relied on the default SQLAlchemy pool settings will now open up to `workers × 15` connections per domain (was `workers × 7`). Before upgrading, verify that the database's `max_connections` setting has headroom; on PostgreSQL the default is 100. To retain the previous behaviour, set `pool_size = 2` and `max_overflow = 5` explicitly on each `[databases.<name>]` block. Silence the warning by setting `PROTEAN_ENV=development` or `testing`. See [Harden the Server → Size the pool against your database's ceiling](docs/guides/server/hardening.md#size-the-pool-against-your-databases-ceiling) for sizing guidance.
- Structured logging baseline: stdlib loggers now flow through the structlog pipeline via `ProcessorFormatter`, so framework internals and user code share one renderer and emit uniformly structured JSON in production. Stack-trace-lost sites (`logger.error(str(exc))`) converted to `logger.exception(...)`. Around fifty hot-path log calls converted to keyword-argument structured events. Operationally critical events (engine lifecycle, subscription start/stop, outbox batch completion) upgraded from DEBUG to INFO so operators running at the default level can see throughput without raising verbosity.
- Logging documentation split along Diataxis lines: `docs/guides/server/logging.md` is now a focused task-oriented guide (quick start, `[logging]` config, CLI overrides, `bind_event_context()`, tail sampling, security events, disable auto-configuration). New `docs/reference/logging.md` enumerates every `[logging]` key, CLI flag, environment variable, public API, and framework logger — including event names, levels, and field schemas for `protean.access`, `protean.access.http`, `protean.perf`, `protean.security`, `protean.server.*`, `protean.core.unit_of_work`, and the broker/repository adapters. New `docs/concepts/observability/logging.md` explains the wide event pattern, query-oriented field design, high-cardinality backend selection, the two-layer HTTP + domain split, tail sampling, and redaction as a pipeline stage. New `docs/guides/fastapi/http-wide-events.md` guide covers wiring, `[logging.http]` configuration, and enrichment.
- `OutboxRepository.find_unprocessed` now pushes status, lock-window, and retry-window predicates into the database query, removing the 3× over-fetch factor.
- `OutboxRepository.count_by_status` issues flat `SELECT COUNT(*)` queries instead of subquery-wrapped projections.
- `OutboxRepository.cleanup_old_published` and `cleanup_old_abandoned` issue a single `DELETE` and return rowcount instead of fetching rows before deletion.
- **Tier-3 (Structural)**: `Outbox` string fields now declare `max_length`, so SQL providers emit `VARCHAR(N)` instead of `TEXT` / `VARCHAR(MAX)`. This unblocks index creation on the outbox table. New deployments get the bounded columns automatically; existing deployments run a one-time `ALTER TABLE` per the [v0.16 migration guide](https://docs.proteanhq.com/reference/migration/v0-16/).
- Support the Elasticsearch 8.x client (`elasticsearch` / `elasticsearch-dsl` 8.x), which fresh installs now resolve to by default. The provider normalizes bare host entries to `scheme://host:port` URLs (using `USE_SSL` to choose the scheme) and no longer passes the v7-only `use_ssl` flag, so existing host configuration keeps working. This also allows `urllib3` 2.x, resolving the related security advisory. **The 8.x client requires an Elasticsearch 8.x server.** Deployments still running an Elasticsearch 7.x server should pin `elasticsearch<8` to keep the 7.17 client, which connects to both 7.x and 8.x servers. See the [v0.16 migration guide](https://docs.proteanhq.com/reference/migration/v0-16/) for details.
- **Behavioral change (secure by default):** `protean observatory` now binds to loopback (`127.0.0.1`) by default instead of `0.0.0.0`. The Observatory is unauthenticated and exposes domain internals and Dead Letter Queue management (retry/delete) endpoints, so it should not be reachable beyond the local machine without deliberate, restricted exposure. To reach it from another host, pass `--host 0.0.0.0` (or another address) explicitly; binding a non-loopback address now logs a warning. Expose it only on a trusted network behind an authenticating reverse proxy. **Upgrade impact:** if you relied on the default being reachable remotely (e.g. a Docker port mapping), add `--host 0.0.0.0` to your `protean observatory` invocation.

### Deprecated

- `--debug` flag on `protean server` and `protean observatory` is deprecated in favor of `--log-level DEBUG`. The flag still works but emits a `DeprecationWarning` and will be removed in v0.17.0.

### Removed

- `assert_valid` and `assert_invalid` were removed from `protean.testing`. They duplicated `pytest.raises(ValidationError)` behind lambda ceremony. **Migration:** replace `assert_invalid(lambda: op(), message="X")` with `with pytest.raises(ValidationError, match="X"): op()`; `assert_valid(lambda: op())` becomes a plain `op()` call.

### Fixed

- Fix Observatory graph rendering with black overlays caused by DaisyUI 4→5 CSS variable mismatch. Update all `oklch(var(--b1))` references to DaisyUI 5 equivalents (`var(--color-base-100)`, `color-mix()`).
- Fix causation graph swimlane grouping treating command and event streams for the same aggregate as separate categories. Strip `:command` suffix in stream category extraction so both share one swimlane.
- Fix subscriber `causation_id` set to Redis Stream delivery ID instead of source event's `message_id`. Commands dispatched from subscribers now carry the correct causation link for cross-domain causation trees in the Observatory.
- Fix Observatory assigning the first domain's name to all events when multiple domains share a single MessageDB. Domain attribution is now derived from the stream name prefix (`<domain>::<aggregate>-<id>`).
- Fix check-then-act race window in optimistic locking — version checks are now atomic with writes across all repository adapters (SQLAlchemy, Memory, Elasticsearch) and the memory event store. Previously, concurrent writers could both pass a pre-write version check and overwrite each other.
- Detect cross-handler command collisions at `Domain.init()` instead of at dispatch time — two command handler classes claiming the same command now raise `IncorrectUsageError` during validation, and are also reported by `protean check`.
- Fixed a race in the outbox where two workers could claim and publish the same message. Claiming is now atomic: the `OutboxProcessor` claims a batch of messages in a single round trip via `OutboxRepository.claim_batch()`, which uses one `UPDATE … WHERE id IN (SELECT … FOR UPDATE SKIP LOCKED) RETURNING *` statement on PostgreSQL and a correct portable fallback on every other backend. Closes the TOCTOU window between selecting a message and marking it `PROCESSING`. See ADR-0013.
- `command_handler`, `event_handler`, and `repository` now accept a string `part_of` reference (e.g. `part_of="Order"`) and resolve it like every other element, instead of raising at registration. This removes the import-ordering and circular-import friction that previously forced class references for exactly these three elements.

### Security

- Sensitive fields are masked in log output via a new `ProteanRedactionFilter` and `make_redaction_processor()` that wire into `Domain.configure_logging()`. Configurable via `[logging].redact` — defaults are unioned with operator-supplied keys so core protections cannot be disabled. Default mask list: `password`, `token`, `secret`, `api_key`, `authorization`, `cookie`, `session`, `csrf`. `log_method_call` automatically inherits redaction.
- `protean server --workers N` (N > 1) now installs a `QueueHandler` / `QueueListener` pattern so JSON log lines never interleave across worker processes.
- New dedicated `protean.security` logger for domain-boundary failures: `InvalidOperationError`, `InvalidStateError`, aggregate invariant violations, and boundary-crossing command validation errors emit WARNING events suitable for SIEM / alerting integration.

## [0.15.0] - 2026-04-10

### Fixed

- Fix persistence ordering in `BaseRepository`: aggregate root is now saved before child entities, and children before grandchildren (top-down). Previously the bottom-up ordering violated foreign-key constraints on databases that enforce them immediately (MSSQL, MySQL/InnoDB, SQLite with `PRAGMA foreign_keys`).
- Pre-commit hook documentation now recommends `repo: local` with `language: system` instead of `repo: https://github.com/proteanhq/protean`, since hooks call `derive_domain()` which imports user code that is unavailable in pre-commit's isolated virtualenv

### Added

- Auto-fix mode (`--fix`) for `protean-check-staleness` pre-commit hook: automatically regenerates stale IR and stages the updated file with `git add`, allowing the commit to proceed without manual intervention
- Multi-domain support for both pre-commit hooks (`protean-check-staleness`, `protean-check-compat`): new `[domains]` section in `.protean/config.toml` maps logical domain names to module paths, enabling a single hook entry to check all bounded contexts in a project. Each domain's IR is stored under `.protean/<name>/ir.json`. The `--domain` argument is now optional when `[domains]` is configured
- Structured logging integration for automatic correlation context injection: new `protean.integrations.logging` module with `ProteanCorrelationFilter` (stdlib `logging.Filter`) and `protean_correlation_processor` (structlog processor) that read `g.message_in_context` and inject `correlation_id` and `causation_id` into every log record. New `domain.configure_logging()` convenience method wires up both the filter and processor in one call. Safe no-op when no domain context is active.
- Add `correlation_id` and `causation_id` fields to `MessageTrace` dataclass and `TraceEmitter.emit()` in the Observatory tracing subsystem. All `handler.started`, `handler.completed`, `handler.failed`, `pm.transition`, `outbox.published`, `outbox.failed`, `message.acked`, `message.dlq` trace events now carry correlation and causation IDs from the processed message metadata. This enables the Observatory dashboard to group, filter, and link trace events by correlation chain. Backward compatible — callers that omit the new params get `None`.
- Add `protean.correlation_id` and `protean.causation_id` span attributes to `protean.handler.execute`, `protean.uow.commit`, `protean.outbox.process`, and `protean.outbox.publish` OTEL spans. Batch-level outbox spans only set these attributes when all messages in the batch share the same ID. This enables filtering all spans in a request chain by correlation ID in Jaeger, Datadog, or Tempo.
- X-Correlation-ID header support in `DomainContextMiddleware`: automatically extracts `X-Correlation-ID` (falling back to `X-Request-ID`) from incoming HTTP request headers and propagates the value as the default correlation ID during command processing. The response always includes an `X-Correlation-ID` header reflecting the ID that was used (from header, explicit `domain.process()` param, or auto-generated).
- End-to-end integration tests for correlation and causation ID propagation across command → event → handler → command → event → projection chains, external correlation ID flow, broker context propagation, event handler causation chain correctness, and OTEL span attribute verification (`tests/tracing/test_e2e_correlation_chain.py`).
- Deprecation support for domain elements and fields: new `deprecated` decorator option for all domain element types (`@domain.aggregate(deprecated={"since": "0.15", "removal": "0.18"})`) and `deprecated` parameter for fields (`String(deprecated="0.15")`), with normalized two-field metadata (`since` required, `removal` optional), sparse IR representation, `DEPRECATED_ELEMENT` and `DEPRECATED_FIELD` info-level diagnostics in `protean check`, and deprecation-aware contract diffing that classifies removals as "expected" (safe), "premature" (breaking), or "unexpected" (breaking) based on version comparison
- `.protean/config.toml` configuration support for IR compatibility checking: `CompatConfig` dataclass and `load_config()` loader in `protean.ir.config`. Supports `compatibility.strictness` (`strict`/`warn`/`off`), `compatibility.exclude` (FQN patterns), `compatibility.deprecation.min_versions_before_removal`, and `staleness.enabled`. Integrated with `protean ir diff`, `protean ir check`, and both pre-commit hooks (`protean-check-staleness`, `protean-check-compat`). `CompatConfig` and `load_config` are exported from `protean.ir`.
- Compatibility checking documentation guide covering `.protean/` directory structure, `config.toml` reference, breaking change rules, CLI commands, pre-commit hook setup, CI integration patterns, and deprecation lifecycle.
- Comprehensive documentation guide for correlation and causation IDs (`docs/guides/observability/correlation-and-causation.md`) covering the OOTB guarantee, external caller integration, full propagation flow with sequence diagram, causation chain semantics, cross-service boundary handling, OTEL relationship and span attribute reference, Observatory viewing, and structured logging setup. Cross-references added to FastAPI integration, subscribers, logging, OpenTelemetry, Observatory, message enrichment, and message tracing guides.

### Changed

- Documentation now positions `to_dict()` as the only recommended serialization method for domain elements and warns against using Pydantic's `model_dump()` directly, which does not handle Reference fields, shadow fields, or datetime conversion correctly. Pydantic methods are hidden from generated API docs.

- Status field self-transitions are now validated against the transition map instead of being silently allowed. Assigning a status to its current value is rejected unless the state lists itself as a target (e.g., `CANCELLED: [CANCELLED]`). This catches re-entry bugs at the framework level and makes idempotent operations explicit in the transition declaration. Terminal states also reject self-assignment.

### Fixed

- Fix unreadable handler wiring and event flow diagrams by splitting into per-concern diagrams in Markdown output (#821)
- Fix Mermaid parse errors in cluster diagrams when invariant names contain commas or are unquoted
- Fix `TypeError: can't compare offset-naive and offset-aware datetimes` in outbox retry logic. Database adapters may return timezone-naive datetimes for `next_retry_at` and `locked_until`, causing comparisons with `datetime.now(timezone.utc)` to crash and block all outbox processing. Added shared `ensure_utc_aware()` utility to normalize naive datetimes before comparison.
- Fix flaky `test_mixed_error_scenarios` in `test_server_robustness.py`: increase Engine test_mode processing cycles from 3 to 10 so all subscription types (events, commands, broker messages) have enough time to be scheduled and process their messages under CI load
- Bridge `correlation_id` from external broker messages to subscriber-triggered commands: `Engine.handle_broker_message()` now extracts `correlation_id` from the incoming message's `metadata.domain.correlation_id` (Protean external format) and sets it on the stub message context. When no correlation ID is present, a fresh UUID is auto-generated. This ensures the cross-service correlation chain is preserved through subscriber processing.
- Preserve outer message context across nested `domain.process()` calls: `CommandProcessor.process()` now saves and restores the previous `g.message_in_context` instead of unconditionally clearing it. This fixes correlation ID loss when a subscriber dispatches multiple commands within a single handler invocation.

### Added

- Pre-commit framework hooks: ship `.pre-commit-hooks.yaml` so downstream projects can add `protean-check-staleness` (blocks commit if `.protean/ir.json` is stale) and `protean-check-compat` (blocks commit if breaking IR changes detected against a git baseline) as pre-commit hooks. Console script entry points `protean-check-staleness` and `protean-check-compat` registered in `pyproject.toml`.
- Enhanced `protean ir diff` with auto-baseline and git support: when `--domain` is provided without `--left`/`--right`, automatically loads `.protean/ir.json` as the baseline and diffs against the live domain. New `--base <commit>` flag loads `.protean/ir.json` from any git commit via `git show`, enabling comparisons against `HEAD`, `main`, or any tag. CI-friendly exit codes: 0 (no changes), 1 (breaking changes), 2 (non-breaking changes only). New `load_ir_from_commit()` and `GitError` in `protean.ir.git` provide the git integration layer, exported from `protean.ir`.
- IR staleness detection: `check_staleness(domain_module, protean_dir) -> StalenessResult` in `protean.ir.staleness` compares the live domain's IR checksum against the materialized `.protean/ir.json`. Returns a `StalenessResult` with `status` (`fresh`, `stale`, or `no_ir`) and both checksums. The `protean ir check` CLI command exposes this with `--domain`, `--dir`, `--format json|text`, and exit codes 0 (fresh), 1 (stale), 2 (no IR found). `StalenessResult`, `StalenessStatus`, and `check_staleness` are exported from `protean.ir`.
- `classify_changes(diff_result, left_ir, right_ir) -> CompatibilityReport` in `protean.ir.diff` — walks all persisted/serialized IR sections (aggregates, entities, value objects, commands, events, database models, projections) and applies a comprehensive breaking-change ruleset: required field added without default → breaking, optional/defaulted field added → safe, field removed → breaking, field type changed → breaking, element removed → breaking, element added → safe, visibility public→internal → breaking, visibility internal→public → safe, `__type__` string changed → breaking. `CompatibilityChange` and `CompatibilityReport` dataclasses are exported from `protean.ir`.
- Real-time SSE updates for Observatory Timeline: live event prepending via `handler.completed`/`outbox.published` trace events with position-based deduplication, new-event row highlight animation, "N new events — click to scroll to top" toast notification when scrolled down, and immediate stat card refresh on each trace event
- Correlation chain and aggregate history sub-views for the Observatory Timeline page: vertical causation tree visualization for correlation chains, chronological aggregate event history with version labels, clickable correlation ID and stream name links in event detail panel, URL deep-linking (`/timeline?correlation={id}`, `/timeline?stream={category}&aggregate={id}`), and back-to-list navigation with browser history support
- Observatory Timeline page: chronological event browser with filter bar (stream category, event type, aggregate ID, kind), cursor-based pagination with infinite scroll, event detail panel with full payload/metadata and correlation chain links, summary stat cards, deep-linking support, and `g→t` keyboard shortcut
- OpenTelemetry integration documentation: comprehensive guide covering configuration, span catalog, metrics catalog, TraceParent propagation, FastAPI auto-instrumentation, APM setup guides (Jaeger, Grafana Tempo, Datadog), Observatory vs OTel positioning, and `/metrics` convergence
- End-to-end integration tests for unified OTel span hierarchy and Observatory trace emission: validates complete span tree from command → handler → UoW → repository → event store, verifies parent-child relationships across all layers, confirms complementary (non-redundant) attributes at each span level, and ensures Observatory traces fire correctly alongside OTel spans both with telemetry enabled and disabled
- OpenTelemetry SDK foundation with optional `telemetry` extra (`pip install protean[telemetry]`), `[telemetry]` configuration section, `telemetry.py` module for provider initialization, and `Domain.tracer`/`Domain.meter` lazy properties — graceful no-op when packages are not installed or telemetry is disabled
- OpenTelemetry spans for command processing and handler dispatch: `protean.command.process` (with command type, id, stream, correlation_id attributes), `protean.command.enrich` (child span), `protean.handler.execute` (with handler name and type, covers command handlers, event handlers, projectors, and process managers), and `protean.query.dispatch` — with exception recording and ERROR status on handler failures
- OpenTelemetry spans for infrastructure operations: `protean.uow.commit` (with event_count and session_count attributes), `protean.repository.add` and `protean.repository.get` (with aggregate type and provider attributes, covers both standard and event-sourced repositories), and `protean.event_store.append` (with stream, message_type, and position attributes) — all spans participate in the same trace as the originating command/query
- OpenTelemetry spans for server subscriptions and outbox processor: `protean.engine.handle_message` (with handler name, message type/id, stream category, worker_id, and subscription_type attributes), `protean.outbox.process` (per batch with batch_size, processor_id, is_external, successful_count), and `protean.outbox.publish` (per message with message_id, stream_category, message_type) — with exception recording and ERROR status on failures, and parent-child span relationships between process and publish spans
- Bridge W3C TraceParent headers with OpenTelemetry context propagation: `extract_context_from_traceparent()` and `inject_traceparent_from_context()` helpers in `telemetry.py`, context extraction in `Engine.handle_message()` and `CommandProcessor.process()` so processing spans parent under incoming traces, context injection in `CommandProcessor.enrich()` and `BaseAggregate.raise_()` so commands and events carry the active span's traceparent forward to downstream handlers
- Auto-instrument FastAPI endpoints with OpenTelemetry via `instrument_app(app, domain)` in `protean.integrations.fastapi` — wraps `opentelemetry-instrumentation-fastapi` with domain-scoped tracer/meter providers so HTTP request spans automatically parent command processing spans through OTEL context propagation, with graceful no-op when telemetry is disabled or packages are not installed
- OpenTelemetry metrics for domain operations: counters (`protean.command.processed`, `protean.handler.invocations`, `protean.uow.commits`, `protean.outbox.published`, `protean.outbox.failed`) and histograms (`protean.command.duration`, `protean.handler.duration`, `protean.uow.events_per_commit`, `protean.outbox.latency`) — instruments are cached per domain via `DomainMetrics` and use no-op fallbacks when OTel is not installed
- Hybrid `/metrics` endpoint convergence: when `opentelemetry-exporter-prometheus` is installed and telemetry is enabled, the Observatory `/metrics` endpoint serves OTel-generated Prometheus text (via `PrometheusMetricReader`) with infrastructure metrics exposed as `ObservableGauge` callbacks; falls back to the original hand-rolled implementation when OTel is not available
- Correlation chain and aggregate history API endpoints for the Observatory: `GET /api/timeline/correlation/{correlation_id}` (all events in a correlation chain with causation tree) and `GET /api/timeline/aggregate/{stream_category}/{aggregate_id}` (full event history for one aggregate instance with version info)
- Event store timeline query API endpoints for the Observatory: `GET /api/timeline/events` (paginated, filterable event list from `$all` stream), `GET /api/timeline/events/{message_id}` (single event detail with full payload and metadata), and `GET /api/timeline/stats` (summary statistics including total events, active streams, and throughput)
- JSON Schema generator (`protean.ir.generators.schema`) — pure functions that
  convert IR element dicts into standard JSON Schema (Draft 2020-12) with
  `x-protean-*` extension metadata for all data-carrying domain elements
- Schema file writer (`protean.ir.generators.schema_writer`) — materializes
  generated JSON Schemas to a `.protean/schemas/` directory tree with
  cluster-aware grouping by aggregate, versioned filenames, and deterministic
  output
- `protean schema generate` CLI command — generates JSON Schema files for all
  data-carrying elements from a live domain (`--domain`) or IR file (`--ir`),
  writing to `.protean/schemas/` by default with configurable `--output`
- `protean schema show` CLI command — displays the JSON Schema for a specific
  element by name or FQN, with syntax-highlighted output (default) or raw JSON
  (`--raw`) for piping
- Meta-schema validation tests — all generated schemas validated against JSON
  Schema Draft 2020-12 meta-schema
- End-to-end payload validation tests — sample payloads validated against
  generated schemas
- ADR-0005: IR-first schema generation rationale
- ADR-0006: Standard JSON Schema with `x-protean-*` extensions rationale
- Schema generation user guide (`docs/guides/compose-a-domain/schema-generation.md`)

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
