# `protean eventstore`

The `protean eventstore` command group inspects and maintains the event store.
Its first command, `verify`, runs a read-only integrity check.

All commands accept a `--domain` option to specify the domain module path
(defaults to the current directory).

## Commands

| Command | Description |
|---------|-------------|
| `protean eventstore verify` | Check the event store's internal consistency |

## `protean eventstore verify`

Reads the whole store once and reports any violation of its internal
invariants. It mutates nothing and works against any adapter (memory,
MessageDB).

```bash
protean eventstore verify --domain=my_domain
```

It checks these invariants:

- **Rows are well-formed.** Every message carries its `id`, `stream_name`,
  `position`, and `global_position`.
- **Position is gapless.** Each stream's `position` runs from 0 without gaps.
- **Global position is strictly increasing.** `global_position` increases
  store-wide across every message.
- **Message ids are unique.** No message id appears twice.
- **Snapshots are well-formed and do not run ahead.** Each `:snapshot-` stream
  carries an integer `_version` that stays at or below the head position of its
  aggregate stream.

A corrupt row is reported, not skipped: a missing field or a malformed snapshot
becomes a violation rather than a silent pass.

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--json` | Emit the result as the shared CLI envelope | Off |

## Output

A clean store prints a one-line summary and exits 0:

```
Event store is consistent: 42 message(s) across 7 stream(s), 0 violations.
```

When a violation is found, it prints a table naming each one and exits 1:

```
       Event store integrity violations
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Kind          ┃ Stream          ┃ Position ┃ Detail                      ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ position_gap  │ test::user-abc  │        2 │ Stream 'test::user-abc'     │
│               │                 │          │ jumps to position 2;        │
│               │                 │          │ expected 1.                 │
└───────────────┴─────────────────┴──────────┴─────────────────────────────┘

1 violation(s) across 2 message(s) and 1 stream(s).
```

## JSON output

With `--json`, the command emits the shared CLI result envelope. The report is
under `data`, with the violation list under `data.violations`:

The command serializes with sorted keys, so real output is alphabetized:

```json
{
  "data": {
    "message_count": 42,
    "ok": true,
    "stream_count": 7,
    "violations": []
  },
  "diagnostics": [],
  "status": "pass",
  "version": "0.1.0"
}
```

Each violation carries a stable `kind` (`malformed_message`,
`duplicate_message_id`, `position_gap`, `non_monotonic_global_position`,
`malformed_snapshot`, or `snapshot_ahead_of_stream`), the `stream` and
`position` it was found at (either may be `null`), and a human-readable
`detail`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | The store is consistent. |
| 1 | At least one violation was found. |
| 2 | Usage or environment error (no or unloadable domain), under `--json`. |

Without `--json`, a load error aborts with exit 1, the same as every other
`protean` command, so exit 1 in human mode covers both a real violation and a
domain that failed to load. Use `--json` when a script needs to tell the two
apart.

## Backup and restore

`verify` checks the store's *internal* consistency. Physical backup and restore
stay with the database and its own tooling. For MessageDB, that means the
PostgreSQL tooling (`pg_dump`, `pg_restore`, and point-in-time recovery). Run
`protean eventstore verify` after a restore to confirm the recovered store is
internally consistent.

## Domain discovery

The `protean eventstore` commands use the same domain discovery mechanism as
`protean server`. See [Domain Discovery](../project/discovery.md) for the full
resolution logic.
