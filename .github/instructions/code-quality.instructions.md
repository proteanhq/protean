---
applyTo: "**"
---

# Code Quality Review Guidelines

## Python conventions

- **Python 3.11+** required. Use modern syntax: `X | Y` unions, `match` statements where appropriate.
- **Type hints** on all new code and any existing code touched by the PR.
- Follow ruff formatting and linting rules configured in `pyproject.toml`.
- Prefer simple, minimal changes. Don't refactor surrounding code unless it's part of the PR's purpose.

## Dependency management

- This project uses **uv** (not Poetry) for dependency management.
- Lock file is `uv.lock`. Build backend is `hatchling`.
- `pyproject.toml` uses PEP 621 `[project]` metadata format.
- Development dependencies use `[dependency-groups]`, not `[project.optional-dependencies]`.
- Flag any PR that adds `poetry` commands or references.

## Security

- No hardcoded secrets, connection strings, or credentials.
- Configuration values should use environment variable substitution (`${VAR_NAME}`).
- Review for OWASP top 10 in any user-facing code (CLI, API endpoints, template rendering).

## Template files

Files under `src/protean/template/domain_template/` are Copier/Jinja2 templates that generate new Protean projects. When reviewing these:
- Verify Jinja2 variables render correctly for all conditional branches (e.g., empty lists, missing optional values).
- Ensure generated `pyproject.toml` produces valid PEP 508 dependency specifiers.
- Check that Dockerfiles, CI workflows, and scripts use `uv` (not `poetry`).

## Documentation

- Docs live in `docs/` and use MkDocs with Material theme.
- ADRs (Architecture Decision Records) go in `docs/adr/`.
- Any architectural change should include or reference an ADR.
