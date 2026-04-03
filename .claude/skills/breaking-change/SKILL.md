---
name: breaking-change
description: Analyze the current branch for breaking changes to Protean's public API and generate the required mitigations. Use when the user says "check for breaking changes", "is this a breaking change", "deprecation", "API compatibility", or before any PR that touches public-facing code in protean.*. Also trigger when renaming, moving, or removing any class, function, or method that user code could depend on.
argument-hint: "[--generate-shims]"
---

# Breaking Change Analyzer

Diff the public API surface against main, classify each break by tier, and generate the required mitigations. The project's policy (see CLAUDE.md and ADR-0004) requires every break to be mitigated in the same PR — not deferred to a follow-up.

## Determine the current version

Read the version from `pyproject.toml` — you'll need this for computing removal versions:

```bash
grep '^version' pyproject.toml
```

Parse the minor version number `N` from the `0.N.x` pattern. Strip any `rc` suffix — deprecation math uses the release version, not the RC.

## Identify API surface changes

```bash
git diff main...HEAD -- 'src/protean/'
```

Focus on `protean.*` — anything a downstream user could import or call. Scan for:

- **Renames or removals**: classes, functions, methods, constants, or module-level names that disappeared or changed names
- **Signature changes**: added required parameters, removed parameters, changed types, changed return types
- **Default value changes**: a parameter that used to default to X now defaults to Y
- **Behavioral changes**: same function signature but different observable behavior (return value, side effects, exceptions raised)
- **Persistence changes**: event `__type__` strings, database model schemas, serialization formats

Ignore names prefixed with `_` unless they appear in `__all__` or are used in documentation/examples. When in doubt about whether something is public API, treat it as public — false positives are safer than missed breaks.

## Classify each break

### Tier 1: Surface-Level (renamed class, moved import, changed signature)

Introduce the new API alongside the old. The old API emits `DeprecationWarning` with a specific removal version and delegates to the new implementation.

**Survival rule**: minimum 2 minor versions. If deprecated in 0.N, earliest removal is 0.(N+2).

**Example** — if current version is 0.15.x and you're renaming `old_method` to `new_method`:

```python
import warnings

def old_method(self):
    warnings.warn(
        "old_method() is deprecated. Use new_method() instead. "
        "Will be removed in v0.17.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    return self.new_method()
```

Key details:
- `stacklevel=2` so the warning points to the caller's code, not the wrapper
- The message names both the old and new API
- The message includes a specific version number, not "a future version"
- The wrapper delegates to the new implementation — it does not duplicate logic

For moved imports, create the old import path as a re-export with a deprecation warning in the old module's `__init__.py`.

### Tier 2: Behavioral (same signature, different behavior)

New behavior goes behind a configuration flag, defaulting to old behavior. This is a 3-version rollout:

| Version | State |
|---------|-------|
| v0.N | New behavior available via config flag, off by default |
| v0.N+1 | Warning emitted if flag is unset ("will change in v0.{N+2}") |
| v0.N+2 | Default flips to new behavior |

The config flag lives in `domain.toml` under the appropriate section. Name it descriptively — `aggregate.use_new_identity_strategy`, not `compat_flag_123`.

### Tier 3: Structural (persistence format, event schema, serialization)

These affect data at rest — the most dangerous category:

- Version the schema or format explicitly (add a version field if one doesn't exist)
- Document exact migration steps in the release's Upgrade Notes
- Provide a migration script or `protean` CLI command where feasible
- If the change affects event `__type__` strings, it's almost certainly Tier 3

## Generate mitigations

If `$ARGUMENTS` includes `--generate-shims`:
- For each Tier 1 break, create the deprecation wrapper and insert it into the source file
- For each Tier 2 break, scaffold the config flag and guard the behavior
- For each Tier 3 break, outline the migration script structure

Without `--generate-shims`, produce a report only — don't modify source files.

## Output the checklist

For each breaking change found, produce the 5-point checklist:

```
### Breaking Change: [concise description]

| Step | Status | Detail |
|------|--------|--------|
| 1. Identify | Done | [what changed in protean.* that user code depends on] |
| 2. Classify | Done | Tier [1/2/3] — [surface/behavioral/structural] |
| 3. Mitigate | [Done/TODO] | [deprecation wrapper / config flag / migration script] |
| 4. Document | TODO | CHANGELOG entry under [Deprecated/Changed] |
| 5. Test | TODO | `protean check` detects deprecated usage |
```

## Compose with changelog

If breaking changes are found, add CHANGELOG entries — Tier 1 and 2 breaks go under **Deprecated**, Tier 3 under **Changed**. You can invoke the `/changelog` skill or insert directly.

## When nothing is found

Report cleanly: "No breaking changes detected in the public API surface." This is the expected outcome for most PRs — don't manufacture findings.
