# Documentation Guide for Claude

Instructions for working with the Protean documentation.

## Adding a New Documentation Page

When you add a new `.md` file to the docs, update **all** of the following:

1. **`mkdocs.yml`** -- Add the file to the `nav:` section in the correct
   location. This controls the sidebar navigation.

2. **`docs/contents.md`** -- Add a one-line entry with a link and short
   description (`--` separated). This is the flat, searchable listing of
   every page.

3. **`docs/how-do-i.md`** -- If the new page answers a "How do I...?"
   question, add a row to the appropriate table.

4. **Section index page** -- Most sections have an `index.md` that lists
   pages in that section. Update it. Examples:
   - `docs/patterns/index.md` for patterns
   - `docs/guides/index.md` for guides
   - `docs/reference/index.md` for reference
   - `docs/concepts/index.md` for explanation
   - `docs/concepts/building-blocks/index.md` for building blocks

## Documentation Structure

```
docs/
├── index.md                    # Home page (hero, code sample, grid cards)
├── start-here.md               # Onboarding guide for new users
├── contents.md                 # Flat listing of every page with descriptions
├── how-do-i.md                 # Task-oriented lookup table
├── glossary.md                 # Term definitions
│
├── guides/                     # How-to guides (goal-oriented, action-focused)
│   ├── getting-started/        # Installation, quickstart, 10-part tutorial
│   ├── pathways/               # DDD, CQRS, Event Sourcing pathways
│   ├── compose-a-domain/       # Domain object, registration, initialization
│   ├── domain-definition/      # Aggregates, entities, VOs, events
│   ├── domain-behavior/        # Validations, invariants, mutation, events
│   ├── change-state/           # App services, commands, handlers, persistence
│   ├── consume-state/          # Event handlers, projections, subscribers
│   ├── fastapi/                # FastAPI integration
│   ├── server/                 # Running the server (running.md only)
│   └── testing/                # Domain, application, integration tests
│
├── reference/                  # Factual lookup documentation
│   ├── domain-elements/        # Decorators, object model, identity config
│   ├── fields/                 # All field types, arguments, definition styles
│   ├── configuration.md        # domain.toml parameters and options
│   ├── cli/                    # CLI commands
│   ├── server/                 # Subscription types, config, observability
│   ├── adapters/               # Database, broker, cache, event store config
│   ├── tooling/                # Mypy plugin
│   └── migration/              # Version migration guides
│
├── concepts/                # Understanding-oriented content
│   ├── philosophy.md           # Design principles
│   ├── foundations/            # Ubiquitous language, bounded contexts, etc.
│   ├── architecture/           # DDD, CQRS, Event Sourcing patterns
│   ├── building-blocks/        # One page per domain element concept
│   ├── async-processing/       # Engine, subscriptions, outbox, streams
│   ├── ports-and-adapters.md   # Adapter architecture explanation
│   └── internals/              # Field system, query system, ES internals
│
├── patterns/                   # Cross-cutting DDD patterns and recipes
│   ├── index.md                # Pattern listing organized by category
│   └── *.md                    # Individual pattern pages
│
└── community/                  # Contributing guides
```

## Three Content Types (Diataxis-inspired)

The same concept often appears in multiple places. Each content type has a
different purpose:

| Type | Location | Purpose | Depth |
|------|----------|---------|-------|
| **Guides** | `guides/` | How to accomplish a task in Protean | Practical, action-focused |
| **Reference** | `reference/` | Factual lookup of options, config, APIs | Austere, consistent |
| **Explanation** | `concepts/` | Why things work the way they do | Conceptual, connective |
| **Patterns** | `patterns/` | Cross-cutting architectural wisdom | In-depth, trade-off analysis |

For example, "Aggregates" appears in:
- `concepts/building-blocks/aggregates.md` -- What an aggregate is
- `guides/domain-definition/aggregates.md` -- How to define one in Protean
- `patterns/design-small-aggregates.md` -- Design wisdom about sizing

## Writing Conventions

### General
- Use `---` (horizontal rules) to separate major sections within a page.
- Use em dashes (`--`) in the contents page for descriptions.
- Use sentence case for headings ("Design small aggregates", not "Design
  Small Aggregates"). Exception: proper nouns and acronyms.
- Keep code examples valid Protean syntax. Use decorators (`@domain.aggregate`,
  `@domain.event`, etc.) and field types from `protean.fields`.
- Cross-reference related pages with relative markdown links.

### Guides
- Start with a brief intro explaining what the page covers.
- Guides for domain elements that apply to specific pathways use an
  admonition at the top: `!!! abstract "Applies to: DDD · CQRS · Event Sourcing"`
- Use concrete code examples throughout.
- Guides should be action-focused: "How to X". No teaching, no reference
  tables. Link to Reference for config options, link to Explanation for
  conceptual background.

### Reference
- Factual, austere, consistent formatting.
- Mirror the structure of the machinery (fields, CLI, config, adapters).
- Include examples that illustrate, but don't teach.
- Link to Guides for practical workflows, Explanation for context.

### Explanation
- Understanding-oriented. Answer "why" questions.
- Building block pages use a "Facts" section for key characteristics.
- Can include opinion, perspective, and design rationale.
- Link to Guides for practical details.

### Patterns
- Follow this structure consistently:
  1. **The Problem** -- Why this pattern matters, what goes wrong without it.
  2. **The Pattern** -- Core principle and mental model.
  3. **How Protean Supports It** -- Framework features that help.
  4. **Applying the Pattern** -- Concrete code examples.
  5. **Anti-Patterns** -- What to avoid, with code examples.
  6. **When Not to Use / Trade-offs** -- Exceptions and nuance.
  7. **Summary** -- Quick-reference table.
- Pattern file names use kebab-case: `design-small-aggregates.md`.
- `patterns/index.md` organizes patterns into five categories:
  Aggregate Design, Event-Driven Patterns, Architecture & Quality,
  Identity & Communication, Testing & Infrastructure.

## MkDocs Features Used

- **Material for MkDocs** theme with `material` extensions.
- **Admonitions**: `!!! note`, `!!! warning`, `!!! abstract`, `!!! example`.
- **Grid cards**: `<div class="grid cards" markdown>` for card layouts.
- **Mermaid diagrams**: Fenced code blocks with `mermaid` language.
- **Code annotations**: Enabled via `content.code.annotate`.
- **Copy button**: On code blocks via `content.code.copy`.
- **Tabs**: `=== "Tab Name"` for tabbed content.

## Top-Level Navigation

The `nav:` in `mkdocs.yml` has these top-level sections:

1. **Protean** -- Home, Start Here, Philosophy, Contents, How Do I...?
2. **Getting Started** -- Installation, Quickstart, Tutorial
3. **Guides** -- Goal-oriented how-to guides organized as a learning journey
4. **Reference** -- Factual lookup: fields, CLI, config, adapters, server
5. **Explanation** -- Philosophy, foundations, architecture, building blocks, internals
6. **Patterns & Recipes** -- Cross-cutting patterns organized by category
7. **Glossary**
8. **Community** -- Contributing guides
