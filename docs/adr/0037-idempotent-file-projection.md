# ADR-0037: Idempotent File Projection and the `dx` Lockfile

**Status:** Accepted

**Date:** August 2026

## Context

`protean dx install` writes agent-facing files into a user's project: an `AGENTS.md`
block, an `.mcp.json` server entry, and more later. Those files are co-owned. The
framework writes part of each one, the user owns the rest, and both sides keep
editing after the first write. Running `install` again must refresh the framework's
part and leave the user's part exactly as it was.

Nothing in the codebase does this. `docs.py:_write_output` and
`scaffold/manifest.py:write_manifest` are plain overwrites. `scaffold/apply.py:apply_plan`
is create-only: it refuses to touch a file that already exists, and it rejects edit
and config operations. So the create case is solved and the re-write case is not.

Re-writing safely needs one thing the create case never needs: a way to tell a
version change apart from a user edit. If the file on disk differs from what the
framework would write, that could mean the framework's own content moved on, or it
could mean the user edited the framework's block by hand. Those need opposite
answers. The first is a routine update. The second must stop and say so, because
overwriting it destroys work the user did.

The file's own bytes cannot answer that question. The engine has to remember what it
last wrote.

## Decision

We add `protean.dx.projection`, a file-projection engine that takes a rendered
artifact, a target path, and a merge mode, and applies it idempotently. It is the
update-and-merge path `apply_plan` defers, and it calls `apply_plan` for the create
case so pre-flight and rollback are not re-derived.

**Two merge modes, matching the two file shapes `dx` ships.**

- *Managed region*, for co-owned text. The framework's block sits between two
  sentinel comment lines, `PROTEAN:BEGIN <region-id>` and `PROTEAN:END <region-id>`.
  Re-projecting replaces only the body between them. Every byte outside, the marker
  lines included, is preserved. The caller supplies the comment syntax (`<!-- -->`
  for Markdown, `#` for a config), so the engine stays format-agnostic.
- *Structured JSON*, for `.mcp.json`. The rendered dict's top-level keys are the
  managed keys. Re-projecting sets those keys and preserves every other key on disk.
  The merge is shallow: a managed key's value is replaced whole. `.mcp.json` names
  its servers at the top level, so that is enough.

**A lockfile at `.protean/dx.lock` remembers what was written.** It sits beside
`project.json` (ADR-0034) and `ir.json`. Per target path it records the pack version
stamp and two hashes: the hash of the whole file the engine last wrote, and the hash
of the managed slice it last wrote.

**The slice hash alone decides what happens.** Comparing three values, the slice on
disk, the slice the lock last recorded, and the slice just rendered, gives four
outcomes:

- **create**: the target is absent.
- **no change**: the on-disk slice equals the new slice and the version stamp
  matches. Nothing is written and the lockfile is left alone.
- **update**: a safe write. Either the user left the region alone (the on-disk slice
  equals what the lock recorded), or the on-disk slice already equals the new content
  while the version advanced.
- **conflict**: the on-disk slice matches neither the lock nor the render, so the user
  edited inside the framework's block. The engine writes nothing and raises.

The whole-file hash does not feed that decision. It feeds one informational flag,
`outside_modified`, which says the file drifted while the managed slice stayed
identical. A `check` or `diff` verb can report that the user edited around the block.
It never blocks a write, because editing outside the block is the whole point of a
co-owned file.

**The diff path mutates nothing.** `diff_projection` recomputes from disk, compares,
and returns the status plus the content it would write. `apply_projection` runs it
first and then acts. This is the derive-and-compare shape of
`scaffold/manifest.py:check_manifest_drift`.

**Hashes are taken over LF-normalized utf-8 text.** A target is read in text mode,
so a CRLF file and an LF file with the same content hash the same and a platform
newline difference never reads as a phantom conflict. A write goes back out in
whatever line ending the file already uses, so an update never rewrites them.

**A symlink target is refused.** `diff_projection` raises before it reads. An update
writes through `os.replace`, which would swap the link for a regular file and leave
the link's target holding the old content. `apply_plan` already refuses to create
over a symlink, dangling ones included, so both paths say the same thing.

**One pair per region id, in v1.** A file carries exactly one
`PROTEAN:BEGIN/END` pair for the requested region id; other tools' regions, with
different ids, may coexist in the same file and are left untouched. A missing,
duplicated, or reversed marker for the requested id raises instead of falling
back to overwriting the file. Marker matching is line-anchored, so a region id
that is a prefix of another id does not false-match.
A projection whose body contains a line identical to a marker is rejected at
construction, because writing it would frame a phantom region and poison every later
re-projection.

**Serialization follows the house style** of ADR-0033: a frozen dataclass, an explicit
`to_dict`/`from_dict` JSON dump with sorted keys and a trailing newline, and a
`lock_version` marker that `from_dict` rejects loudly when it does not recognize it.

Writes are atomic, through a sibling temp file and an `os.replace`. The target file is
written before the lockfile, so a failed write leaves the lock on the prior stamp and
the next run re-derives rather than trusting a stamp for content that never landed.

## Consequences

- Re-running `dx install` is safe by default. The common cases, nothing changed and
  the user edited around the block, both do the right thing with no prompt.
- A user edit inside the framework's block is never silently destroyed. The cost is
  that resolving it is manual: the engine reports the conflict and stops, and there is
  no merge-conflict-marker mode or `--force` in v1.
- The lockfile is a new file in the user's repo. It has to be committed for the
  conflict check to work across machines. Delete it and the engine loses the record
  of what it last wrote: a file whose block still matches the new render is still a
  safe update, but a block the user edited now reads as a conflict, since an
  unrecorded slice matches no lock.
- Managed-region files carry visible marker comments. That is a small cost in the
  file's readability, and it buys a boundary the user can see and work around.
- The shallow JSON merge cannot manage a nested key on its own. Managing
  `servers.protean` means managing all of `servers`. `.mcp.json` does not need more
  than that today; a deeper merge would need a key-path notion and is deferred until
  a file actually asks for it.
- `lock_version` means an old build meeting a newer lockfile fails loudly instead of
  misreading it. The cost is one more version marker to bump when the shape changes.

## Alternatives Considered

- **Compare the whole file instead of the managed slice.** Rejected: any user edit
  anywhere in a co-owned file would then read as a conflict, which is exactly the
  case the engine exists to allow. The whole-file hash is kept, but only as the
  informational `outside_modified` signal.
- **A three-way merge with conflict markers in the file.** Rejected for v1: it writes
  a broken file into the user's project and leaves them to repair it. Refusing to
  write and naming the conflict is a smaller promise the engine can keep.
- **No lockfile, deciding from markers and content alone.** Rejected: without a record
  of what was last written, a version change and a user edit look identical, and the
  engine has to guess. Guessing wrong in one direction destroys user work.
- **Store the framework's last-written content, not a hash.** Rejected: it bloats a
  committed file with a second copy of every managed block, and the decision only ever
  needs equality, which a hash answers.
