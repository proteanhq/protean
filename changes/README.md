# Changelog Fragments

Each PR drops a fragment file here. At epic completion, `/changelog` assembles
them into `CHANGELOG.md` and deletes the fragments.

## Naming

```
<issue-number>.<category>.md
```

- **issue-number**: GitHub issue number (e.g., `752`)
- **category**: One of `added`, `changed`, `deprecated`, `removed`, `fixed`, `security`

A single issue may have multiple fragments if it spans categories (e.g., `752.added.md` and `752.deprecated.md`).

## Content

One or two lines, written from the user's perspective:

```markdown
Add deprecation lifecycle (`deprecated={"since": "0.15", "removal": "0.18"}`) for domain elements and fields
```

See `CHANGELOG.md` for style examples.

## Breaking changes

A fragment that announces a break must say so and point at the migration
section that tells a user what to do:

```markdown
**Breaking.** `checks.subscriptions` in the `/readyz` response is now an object
instead of an integer. Anything parsing it as a number needs updating.

**Migration:** [/readyz reports an object](https://docs.proteanhq.com/reference/migration/v0-17/#readyz-reports-an-object-where-it-reported-a-number)
```

`tests/test_changelog_fragments.py` enforces both halves: a declared break needs
the `**Migration:**` line, and the anchor it names has to exist in that guide.

**Keep the category honest.** A behaviour change that is genuinely a bug fix
stays under `fixed`; the `**Breaking.**` marker is what stops an upgrader
skimming past it. Do not move a fix to `changed` just to signal risk.

This matters because it has already gone wrong: in the 0.17.0 audit the
`/readyz` change was correctly identified as breaking and correctly written up
here, and still never reached the migration guide, because the handoff was
manual.

## Changes with no issue number

Most fragments are named for their issue. A change that landed without one (the
Apache-2.0 relicense, for example) may use a lowercase slug instead:
`license.changed.md`.
