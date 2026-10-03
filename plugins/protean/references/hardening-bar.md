# The skill-hardening bar

Every teaching skill in the pack is held to this bar. A skill passes when all of
the following hold.

- **Correct against the current API.** The prose and the code match the
  framework version the pack ships inside. No renamed decorator, no removed
  argument, no behavior the current code no longer has.
  `tests/dx/test_skill_snippets.py` runs the fenced `python` blocks in
  `SKILL.md` and `references/*.md`. The blocks of one file run in order in one
  namespace, and the file's domain must initialize after the last block. A block
  that is not meant to run (a signature, a partial method, a wrong example shown
  on purpose) starts with a `# fragment` line, and the test skips it. Do not mark
  a block as a fragment to hide an error: a file that fails goes on the test's
  allowlist until it is fixed. The prose is still a read against the code.
- **Runnable examples.** Every `assets/*.py` builds a real domain and
  initializes against the installed framework. `tests/dx/test_examples.py` runs
  all of them, so a broken example fails the test run.
  `tests/dx/test_asset_diagnostics.py` runs `check` on every asset and fails on
  any warning or error outside the four completeness codes, unless the asset and
  code are on its allowlist. Assets that show a problem on purpose (`*_before.py`,
  `saga_before_unclosed.py`, `audit_sample_codebase.py`) are exempt.
- **Valid frontmatter.** The frontmatter parses as YAML, `name` equals the
  skill's folder name, and the description is at most 1,024 characters. Quote a
  description that contains `: `. `tests/dx/test_skill_frontmatter.py` checks
  this.
- **Resolving references.** Every internal reference a skill makes resolves: each
  `../<name>/SKILL.md` cross-link points at a bundled skill, each `references/*.md`
  and `assets/*.py` the skill names exists, and no example asset or reference page
  is left unlinked. `tests/dx/test_pack_integrity.py` checks this.
- **A verify step.** The recipe links `references/verify-with-check.md`, the one
  shared instruction to run `check` and resolve what it reports.
  `tests/dx/test_pack_integrity.py` checks the link.
- **Declared diagnostic codes.** A skill that teaches a coded convention declares
  the codes under `metadata.diagnostic_codes` in its frontmatter, in the
  block-list form. The seed skill `protean-overview` is the shape to match.
  `tests/dx/test_diagnostic_codes.py` checks that every declared code is a real
  diagnostic code and that every skill the reverse index names exists.
