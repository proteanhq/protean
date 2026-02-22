# Organize by Domain Concept

## The Problem

A flat folder of fourteen files communicates nothing about the domain:

```
src/identity/customer/
├── __init__.py
├── account.py
├── addresses.py
├── api.py
├── commands.py
├── customer_address_book_projector.py
├── customer_lookup_projector.py
├── customer_profile_projector.py
├── customer.py
├── customers_by_tier_projector.py
├── events.py
├── profile.py
├── registration.py
└── tier.py
```

This structure has three problems:

1. **No narrative.** An alphabetically sorted list of files communicates
   nothing about the domain. The aggregate root (`customer.py`) has the
   same visual weight as a projector file. There is no hierarchy of
   importance.

2. **Write and read sides entangled.** Projector files (read-side concerns)
   sit alongside the aggregate and its capabilities (write-side concerns).
   Query-side plumbing pollutes the domain story.

3. **Scattered workflows.** To work on address management, a developer
   touches five files: `addresses.py` for the handler, `commands.py` to
   find the relevant commands among many others, `events.py` to find the
   relevant events, `customer.py` for aggregate methods, and
   `customer_address_book_projector.py` for the read model. One capability,
   five locations.

The classic layered alternative — splitting code into `domain/`,
`application/`, `infrastructure/` — is even worse. To understand a single
feature, you fish through three separate subtrees. The folder tree reads
like a framework manual instead of a business story.

## The Pattern

**The folder tree owns the "what" (domain concepts). The framework owns
the "which kind" (layer, side, boundary).**

Organize your codebase so that the directory tree reads like the table of
contents of a book about your business. When a newcomer opens a domain
folder, they should immediately understand what the system *does* — not
what technologies it uses. Every folder and top-level file should be
something you'd explain to a product manager.

This means resolving three cross-cutting tensions:

### Domain Model vs. Application vs. Infrastructure

The framework carries layer metadata. The folder structure doesn't need to.

When Protean sees `@CommandHandler`, it knows that's application layer.
When it sees `@Aggregate`, it knows that's domain model. Protean's
decorators carry this information so the folder structure doesn't have to
repeat it.

Infrastructure concerns that are truly external (API endpoints,
configuration) live as top-level files within the bounded context, visible
as scaffolding rather than buried in a junk drawer.

### Write vs. Read (CQRS)

Projections live in their own top-level folder within the bounded context,
not nested inside aggregates.

Projections serve business questions. They *happen* to source data from
aggregates, but they're organized by the question they answer, not by
where their data comes from. An address book exists because the support
team needs to look up where customers live — not because the Customer
aggregate decided to project itself.

Placing projections at the domain level also scales naturally: when a
projection eventually draws from multiple aggregates, it already has a
home that doesn't belong to any single aggregate.

### External vs. Internal (Hexagonal)

External adapters live at the domain boundary level, not inside aggregates.

A single API endpoint often orchestrates across multiple aggregates.
Placing `api.py` at the domain level keeps aggregate folders purely about
domain behavior and allows APIs to naturally span multiple aggregates as
the domain grows.

## How Protean Supports It

Protean's decorator system is the enabler. Because every element declares
its architectural role through its decorator (`@domain.aggregate`,
`@domain.command_handler`, `@domain.projection`, `@domain.repository`),
the framework carries architectural metadata that traditional codebases
encode through folder structure. This frees you to organize by domain
concept instead.

Protean's auto-discovery scans all Python files in the domain's
`root_path` recursively. It doesn't care *where* you place files — it
discovers elements by their decorators. This means structural decisions
are purely for developer ergonomics, not framework requirements.

The `protean new` command scaffolds projects that follow these principles
from day one: aggregates as top-level folders, projections at the domain
level, and shared vocabulary in its own folder.

## Applying the Pattern

### Aggregates Are Top-Level Folders

Each aggregate within a bounded context is a folder at the top level.
These are chapter headings — names a business stakeholder would recognize:

```
src/identity/
├── customer/          # First aggregate
├── organization/      # Second aggregate
└── ...
```

### Capability Files Colocate Commands with Their Handlers

Each capability file contains both the command definitions and the handler
for that capability. One concept, one file:

```python
# customer/addresses.py

@domain.command(part_of="Customer")
class AddAddress:
    customer_id = Identifier(required=True)
    street = String(required=True)
    city = String(required=True)
    ...

@domain.command(part_of="Customer")
class RemoveAddress:
    customer_id = Identifier(required=True)
    address_id = Identifier(required=True)

@domain.command(part_of="Customer")
class SetDefaultAddress:
    customer_id = Identifier(required=True)
    address_id = Identifier(required=True)


@domain.command_handler(part_of="Customer")
class ManageAddressesHandler:
    @handle(AddAddress)
    def add_address(self, command):
        ...

    @handle(RemoveAddress)
    def remove_address(self, command):
        ...

    @handle(SetDefaultAddress)
    def set_default_address(self, command):
        ...
```

This optimizes for the most common developer workflow: understanding or
modifying a single capability. No hunting through shared grab-bag files.

### Events Stay Separate

Commands and events are treated asymmetrically, reflecting a real
architectural truth:

- **Commands flow inward** toward a specific capability. `AddAddress`
  only makes sense in the context of address management. It colocates
  with its handler.
- **Events radiate outward** to many consumers. `AddressAdded` originates
  from the Customer aggregate but is consumed by projectors, notification
  services, analytics pipelines, and potentially other domains entirely.

`events.py` serves as the aggregate's **output contract** — a complete
catalog of everything the aggregate announces. When building a new
projector or integration, a developer scans `events.py` to discover what
they can react to. This is a different workflow from "build the address
feature."

Events must also remain separate for a mechanical reason: they're imported
by the aggregate (which raises them), so placing them inside capability
files would create circular imports (the capability handler imports the
aggregate, and the aggregate would import events from the capability file).

### Projections Get Their Own Folder

Projections live in a `projections/` folder at the bounded context level.
Each file contains both the projection (read model definition) and the
projector (event handler that builds it). One business question, one file:

```
├── projections/
│   ├── customer_card.py        # Snapshot of a customer
│   ├── customer_lookup.py      # Find a customer by email
│   ├── address_book.py         # Where do they live?
│   └── customer_segments.py    # Distribution by tier
```

Projection files are named for the **business question they answer**
rather than mirroring write-side structure. `customer_lookup.py`, not
`customer_lookup_projector.py`.

### Shared Domain Vocabulary Gets Its Own Folder

Value objects that don't belong to any single aggregate — Email, Phone,
and similar cross-cutting domain vocabulary — live in a `shared/` folder
at the bounded context level:

```
└── shared/
    ├── email.py
    └── phone.py
```

### The Complete Structure

```
src/identity/                              # Bounded context
│
├── domain.py                              # What is this bounded context
├── api.py                                 # How the outside world talks to it
│
├── customer/                              # The central concept
│   ├── customer.py                        #   Model + entities + VOs
│   ├── events.py                          #   What Customer announces
│   ├── registration.py                    #   How customers join
│   ├── profile.py                         #   Managing who they are
│   ├── addresses.py                       #   Where they live/ship to
│   ├── account.py                         #   Account lifecycle
│   └── tier.py                            #   Loyalty program
│
├── projections/                           # How we query customers
│   ├── customer_card.py                   #   Snapshot of a customer
│   ├── customer_lookup.py                 #   Find a customer by email
│   ├── address_book.py                    #   Where do they live?
│   └── customer_segments.py              #   Distribution by tier
│
└── shared/                                # Domain vocabulary
    ├── email.py
    └── phone.py
```

A newcomer opens `src/identity/` and understands:

> "The Identity domain is defined in `domain.py` and exposes an `api`.
> It centers on the **Customer** aggregate — customers register, manage
> their profiles, have addresses, go through account lifecycle, and
> participate in a loyalty program. The domain answers queries through
> **projections**: customer snapshots, lookups, address books, and segment
> distributions. It has **shared** vocabulary for email and phone."

### How It Scales

When a second aggregate arrives (e.g., Organization), the structure
absorbs it without reorganization:

```
src/identity/
├── domain.py
├── api.py
│
├── customer/                              # First aggregate
│   └── ...
│
├── organization/                          # Second aggregate — same pattern
│   ├── organization.py
│   ├── events.py
│   ├── enrollment.py
│   └── membership.py
│
├── projections/                           # Can now span both aggregates
│   ├── customer_card.py
│   ├── customer_lookup.py
│   ├── address_book.py
│   ├── customer_segments.py
│   ├── org_directory.py
│   └── member_roster.py                   # Draws from Customer + Organization
│
└── shared/
    ├── email.py
    └── phone.py
```

The new aggregate is a new chapter. Projections that span both aggregates
already have a natural home.

## Anti-Patterns

### Layered folders that hide the domain

```
# Anti-pattern: organizing by technical layer
src/identity/
├── domain/
│   ├── customer.py
│   └── organization.py
├── application/
│   ├── customer_commands.py
│   └── organization_commands.py
└── infrastructure/
    ├── customer_repository.py
    └── api.py
```

To understand customer address management, you open three folders. The
folder tree reads like a framework manual. Protean's decorators already
carry this layer information — the structure doesn't need to repeat it.

### Grab-bag files

```
# Anti-pattern: all commands in one file
customer/
├── commands.py        # 15 commands for 5 different capabilities
├── handlers.py        # 15 handlers, one per command
└── events.py
```

`commands.py` becomes a grab bag that grows unbounded. Splitting by
capability (`addresses.py`, `profile.py`, `tier.py`) keeps each file
focused and navigable.

### Projections nested inside aggregates

```
# Anti-pattern: projections as aggregate internals
customer/
├── customer.py
├── events.py
├── customer_lookup_projector.py
├── customer_card_projector.py
└── address_book_projector.py
```

This entangles read and write concerns. Projections serve business
questions — they belong at the domain level where they can naturally span
multiple aggregates.

## When Not to Use

**Very small domains.** If your bounded context has a single aggregate
with two or three capabilities, a flat file structure is fine. Don't
create folders for organizational purity when the total file count is
under six.

**Prototyping.** During the earliest exploration, a single file with
everything is acceptable. Structure emerges as the domain solidifies.
Don't let premature organization slow down domain discovery.

## Litmus Tests

Use these to validate structure decisions as the domain grows:

| Test | Question |
|------|----------|
| **Table of contents** | Every folder and top-level file should be nameable as something you'd explain to a product manager. If a name requires a parenthetical technical explanation, it fails. |
| **Possessive** | If a concept naturally belongs to something else ("a customer's profile"), it's a file inside that folder. If it has its own lifecycle or serves its own audience, it's its own folder or top-level file. |
| **One concept, one place** | To understand address management, you open one file. To understand the aggregate's event contract, you open one file. To understand a read model, you open one file. |
| **Framework carries it** | If a structural decision exists only to communicate technical layer information, ask whether Protean's type system already carries that information. If it does, the structure doesn't need to repeat it. |

## Summary

| Aspect | Guidance |
|--------|----------|
| **Governing principle** | Folder tree owns the "what" (domain concepts); framework owns the "which kind" (layer, side, boundary) |
| **Aggregates** | Top-level folders within the bounded context |
| **Capabilities** | One file per capability, colocating commands and their handler |
| **Events** | Separate `events.py` per aggregate — the output contract |
| **Projections** | Own folder at domain level, named by business question |
| **Shared vocabulary** | Own folder for cross-aggregate value objects |
| **API / external** | Top-level file at domain level, not inside aggregates |
| **Infrastructure** | Emerges as a folder only when needed, not created preemptively |

---

!!! tip "Related reading"
    **Concepts:**

    - [Aggregates](../concepts/building-blocks/aggregates.md) — Aggregates as conceptual wholes.

    **Guides:**

    - [Compose a Domain](../guides/compose-a-domain/index.md) — Registering and organizing domain elements.
    - [CLI: new](../reference/cli/project/new.md) — Scaffolding a new project with domain-oriented structure.
