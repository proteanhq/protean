# ADR-0037: Idempotent Managed Files and the `dx` State File

**Status:** Accepted

**Date:** August 2026

## Context

`protean dx install` writes agent-facing files into a user's project: an
`AGENTS.md` block, an `.mcp.json` server entry, and more later. Those files are
co-owned. The framework writes part of each file and the user owns the rest.
Both sides keep editing after the first write. Running `install` again must
refresh the framework's part and leave the user's part exactly as it was.

Nothing in the codebase does this. `docs.py:_write_output` and
`scaffold/manifest.py:write_manifest` are plain overwrites.
`scaffold/apply.py:apply_plan` is create-only: it refuses to touch a file that
already exists. It also rejects edit and config operations. So the create case
is solved and the re-write case is not.

Re-writing safely needs one thing the create case never needs: a way to tell a
version change apart from a user edit. Suppose the file on disk differs from
the framework's new render. Either the framework's own content changed in a new
version, or the user edited the framework's block by hand. Those need opposite
answers. The first is a routine update. The second must stop and say so,
because overwriting it destroys work the user did.

The writer cannot tell a version change from a user edit by reading the file's
own bytes. The writer has to remember what it last wrote.

## Decision

We add `protean.dx.managed_files`, a managed-file writer that takes a rendered
artifact, a target path, and a merge mode, and applies it idempotently. The
writer is the update-and-merge path that `apply_plan` defers. For the create
case it calls `apply_plan`, so it does not re-derive pre-flight and rollback.

**`dx` ships three file shapes, so the writer has three merge modes.** The
first two modes shipped with this ADR. The whole-file mode was added for the
per-editor renderers (#1474).

- *Managed block*, for co-owned text. The framework's block sits between two
  sentinel comment lines, `PROTEAN:BEGIN <block-id>` and `PROTEAN:END <block-id>`.
  A second apply replaces only the body between them. Every byte outside, the marker
  lines included, is preserved. The caller supplies the comment syntax (`<!-- -->`
  for Markdown, `#` for a config), so the writer stays format-agnostic.
- *Managed JSON keys*, for `.mcp.json`. The rendered dict's keys are the managed
  keys. A second apply sets those keys and preserves every other key on disk. A
  managed key's value is replaced whole. An optional key-path scopes the merge to a
  nested object: `.mcp.json` manages only the `mcpServers.protean` key-path, so an
  existing file keeps the user's other servers (the key-path merge landed in #1475).
- *Whole file*, for a dx-owned text file with no user-owned region. The framework
  owns the entire file, so the render is the whole content and the managed
  slice is the whole file. A hand edit anywhere in it reads as a conflict. The
  whole-file mode is for a file format that cannot take a marker line before
  its first byte. Cursor's `.mdc` rule file is one example, because its YAML
  frontmatter must start at line 1 (#1474).

**A state file at `.protean/dx-state.json` records what the writer last
wrote.** The state file is in the same folder as `project.json` (ADR-0034) and
`ir.json`. Per target path it records the pack version stamp and two hashes:
the hash of the whole file the writer last wrote, and the hash of the managed
slice it last wrote.

**The writer picks the outcome from the slice hash and the version stamp.** The
writer compares three values (the slice on disk, the slice the state file last
recorded, and the slice just rendered) and gets one of four outcomes:

- **create**: the target is absent.
- **no change**: the on-disk slice equals the new slice and the version stamp
  matches. Nothing is written and the state file is left alone.
- **update**: a safe write. In one case the user left the block alone, so the
  on-disk slice equals what the state file recorded. In the other, the version
  advanced and the on-disk slice already equals the new content.
- **conflict**: the on-disk slice matches neither the state file nor the render, so
  the user edited inside the framework's block. The writer writes nothing and raises.

The writer does not use the whole-file hash to pick among the four outcomes.
The whole-file hash sets one informational flag, `outside_modified`. The flag
says the file changed outside the managed slice and the slice stayed identical.
A `check` or `diff` verb can report that the user edited around the block. The
`outside_modified` flag never blocks a write, because the user is meant to edit
a co-owned file outside the block.

**The diff path mutates nothing.** `diff_managed_file` recomputes from disk, compares,
and returns the status plus the content it would write. `apply_managed_file` runs it
first and then acts. This is the derive-and-compare shape of
`scaffold/manifest.py:check_manifest_drift`.

**Hashes are taken over LF-normalized utf-8 text.** The writer reads a target
in text mode, so a CRLF file and an LF file with the same content get the same
hash. A platform newline difference therefore never shows up as a false
conflict. The writer keeps the file's existing line endings when it writes, so
an update never changes those line endings.

**A symlink target is refused.** `diff_managed_file` raises before it reads. An update
writes through `os.replace`, which would swap the link for a regular file and leave
the link's target holding the old content. `apply_plan` already refuses to create
over a symlink, dangling ones included, so both paths say the same thing.

**In v1, a file holds one marker pair per block id.** A file carries exactly
one `PROTEAN:BEGIN/END` pair for the requested block id. Other tools' blocks,
with different ids, may share the same file, and the writer leaves them
untouched. When a marker for the requested id is missing, duplicated, or
reversed, the writer raises an error and does not overwrite the file. Marker
matching is line-anchored, so a block id that is a prefix of another id does
not false-match. The writer rejects a block at construction when the block's
body contains a line identical to a marker. Writing that block would add a
stray marker line to the file and break every later apply.

**Serialization follows the house style of the versioned ChangePlan contract
(ADR-0033)**: a frozen dataclass, an explicit `to_dict`/`from_dict` JSON dump
with sorted keys and a trailing newline, and a `state_version` marker.
`from_dict` rejects an unrecognized `state_version` loudly.

Writes are atomic, through a sibling temp file and an `os.replace`. The writer
writes the target file before the state file, so a failed write leaves the
prior stamp in the state file. The next run then re-derives the outcome and
does not trust a stamp for content that was never written.

## Consequences

- Re-running `dx install` is safe by default. In the two common cases, the
  writer does the right thing with no prompt: nothing changed, or the user
  edited around the block.
- A user edit inside the framework's block is never silently destroyed. The
  cost is manual resolution: the writer reports the conflict and stops. In v1
  there is no merge-conflict-marker mode and no `--force`.
- The state file is a new file in the user's repo. It has to be committed for the
  conflict check to work across machines. If you delete the state file, the
  writer loses its record of past writes and can compare each block only with
  the new render. A block that matches the new render is still a safe update,
  and a block the user edited becomes a conflict.
- Managed-block files carry visible marker comments. The marker comments make
  the file a little harder to read. In return, the user can see the boundary of
  the framework's block and edit around it.
- The JSON merge takes an optional key-path so it can manage a nested key on its
  own: managing `mcpServers.protean` sets only that entry and keeps every
  sibling server. With no key-path it stays the shallow top-level merge. The
  writer has the nested form because `.mcp.json` needs it (#1475). Other
  targets still use the shallow merge.
- `state_version` means an old build meeting a newer state file fails loudly instead of
  misreading it. The cost is one more version marker to bump when the shape changes.

## Alternatives Considered

- **Compare the whole file instead of the managed slice, for co-owned files.**
  Rejected: the writer would then treat any user edit anywhere in a co-owned
  file as a conflict. The writer exists to allow exactly those edits. The
  whole-file hash is kept, but only as the informational `outside_modified`
  signal. (The whole-file mode added in #1474 covers the opposite case: dx owns
  the file outright and the file has no user region. For that file, a
  whole-file conflict is the intended behavior.)
- **A three-way merge with conflict markers in the file.** Rejected for v1: it writes
  a broken file into the user's project and leaves them to repair it. The
  writer can guarantee a smaller behavior: it refuses to write and names the
  conflict.
- **No state file, deciding from markers and content alone.** Rejected: without a record
  of what was last written, a version change and a user edit look identical,
  and the writer has to guess. If the writer guesses wrong in one direction, it
  destroys user work.
- **Store the framework's last-written content in place of a hash.** Rejected:
  the state file is committed, and storing content would add a second copy of
  every managed block to it. The writer only needs to test equality, and a hash
  can do that.
