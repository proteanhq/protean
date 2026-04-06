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
