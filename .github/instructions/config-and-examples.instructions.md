---
applyTo: "docs/**,src/protean/cli/**,src/protean/scaffold/**,src/protean/template/**,**/*.toml"
---

# Config, scaffold, and example review rules

- Flag a config snippet, `domain.toml`, or generated scaffold that no test
  executes. A config example is correct only if it runs. A key spelled right that
  nothing reads survives releases. Verify by loading it, not by matching its text.
- Flag a new `domain.toml` key wired into only one bootstrap path. It must work
  through programmatic init, the server worker, the shell, and middleware.
- Flag a change that edits a failing example to match broken behavior instead of
  fixing the code. The tell is an orphan: an env var nothing reads, a config key
  nothing consumes, a flag nothing checks.
