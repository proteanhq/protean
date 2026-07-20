# ADR-0019: Check-engine determinism boundary and a behavioral analysis substrate

**Status:** Accepted

**Date:** July 2026

## Context

`protean check` is Protean's architecture fitness-function engine. Its value rests on
a single promise: a diagnostic is a *fact*. When the engine flags a violation, the
verdict must be objective, reproducible, and the same on every run and every machine —
otherwise it is noise a team learns to ignore, and a fitness function that cries wolf
is worse than no fitness function at all.

Today every rule honours that promise structurally. Each `_diagnose_*` rule walks the
Intermediate Representation (the structural model of a bounded context — its aggregates,
entities, fields, indexes, events, handlers, and their declared metadata; see
[ADR-0003](0003-one-ir-document-per-bounded-context.md) and
[ADR-0005](0005-ir-first-schema-generation.md)). The IR describes *what the domain
declares*. It says nothing about *what the domain's code does* inside a method body.
The one rule that reads source — `INFRA_IMPORT_IN_DOMAIN` — deliberately inspects only
a module's top-level import statements and never descends into function bodies.

A class of valuable checks lives below that line. "This query filters on an unindexed
field", "this collection is loaded in full and filtered in Python", "this read-modify-save
sequence is not wrapped in a Unit of Work" — none of these are visible in the structural
IR. They are properties of the statements a developer wrote, and detecting them requires
parsing and analysing method bodies (their Abstract Syntax Trees).

Three such rules were planned as ordinary fitness functions. Auditing them against the
codebase surfaced two distinct problems that this ADR separates and settles:

1. **There is no substrate.** The rules were specified against body-level analysis
   machinery that does not exist. The engine can parse a module's imports; it cannot
   enumerate the query call-sites in a repository method, resolve what a receiver refers
   to, or track a value across statements.

2. **Not every such rule can keep the promise.** Some body-level checks yield a
   definite verdict from unambiguous facts. Others depend on resolving what an
   arbitrary receiver refers to, or on tracing a value through reassignments across
   statements — analysis that, in a dynamic language, is inherently approximate and
   carries false positives that the rule authors themselves acknowledged.

Related: [#773](https://github.com/proteanhq/protean/issues/773).

## Decision

**We draw a determinism boundary for the check engine, and we build a behavioral
analysis substrate beneath it.**

**The boundary.** `protean check` ships only rules that produce a deterministic,
reproducible verdict. A rule qualifies when its answer is computed from the structural
IR, or from *unambiguous* facts in a source AST — facts that do not require guessing
what a name refers to or reconstructing a value's provenance through approximate
dataflow. A check whose correctness depends on ambiguous receiver resolution or on
probabilistic intra-procedural dataflow — and which therefore emits false positives —
does not belong in the engine. This is not a comment on such a check's usefulness; it
is a statement about what the engine is allowed to assert as fact. The determinism
boundary is what makes a green `protean check` run trustworthy.

**The substrate.** We add a *behavioral analysis layer* that sits alongside the
structural IR. Where the IR answers "what does the domain declare?", the behavioral
layer answers "what does the domain's code do?" by parsing the method bodies of
registered domain elements and exposing the results to rules as plain queryable data —
the same ergonomics a rule enjoys against the IR today. Its capabilities are, in
foundation order:

1. a source-and-AST provider that resolves each element to its module, parses it once,
   and caches the tree (generalising the parse step currently local to the import rule);
2. an element/method index mapping each element to its class and method nodes, tagged by
   role (command-handler method, repository method, aggregate behavior, event `apply`,
   projector on-event);
3. a call-site catalog with receiver-role resolution, recognising Protean idioms
   (`repository.add`/`get`/`find_by`/`filter`/`find`, `raise_`, `with UnitOfWork()`);
4. intra-procedural dataflow — definition/use chains, statement ordering, and lexical
   block coverage; and
5. a queryable behavioral view exposed to rules as data.

The substrate is a general framework capability, not scaffolding for one rule. Its first
consumer is the deterministic `UNINDEXED_FILTER_PATH` rule, whose verdict is objective:
a filtered field either has a declared index in the IR or it does not.

## Consequences

- The engine gains the ability to reason about code, not just declarations, opening a
  broad family of deterministic rules that were previously impossible — lost-write
  detection, event-store aggregates that mutate without raising an event, repository
  calls inside loops, runtime adapter calls from the domain layer, and more — plus
  non-lint uses of the same layer such as interaction graphs and change-impact analysis.
- The `protean check` promise is now written down: a green run means every shipped rule
  reached a reproducible verdict. Contributors have a citable answer to "why doesn't the
  engine catch X?" — because a trustworthy *maybe* is a contradiction, and the boundary
  keeps the engine free of them.
- Body-level analysis is more expensive than an IR walk: files must be located, read, and
  parsed. The provider parses each module once and caches, and source-reading rules remain
  opt-in where cost warrants, as `INFRA_IMPORT_IN_DOMAIN` already is.
- Some genuinely useful checks are deliberately kept out of the engine because they cannot
  meet the boundary. That is an accepted cost: the engine's authority is worth more than
  its coverage. Such checks may be served by other tools built on the same substrate; the
  substrate itself is open and unconstrained.
- The substrate is new surface area — an AST provider, a call-site model, a dataflow pass —
  that must be built and maintained before the rules that depend on it. It is sequenced as
  foundation-first work so each layer lands and is tested independently.

## Alternatives Considered

**Ship the body-level rules as best-effort heuristics inside the engine.** Rejected: it
inverts the engine's core value. One rule that flags correct code teaches teams to distrust
every rule, and the distrust is not rule-scoped. The boundary exists precisely to prevent
this.

**Keep `protean check` structural-only and never read method bodies.** Rejected: it
permanently forecloses a large class of objectively-decidable checks (an unindexed filter
is a fact, not a guess) and leaves real architectural drift undetectable. The problem was
never that body-level analysis is unsound — it is that *some* of it is. The boundary lets
the sound part through.

**Build only the narrow analysis the first rules need.** Rejected: the same substrate —
source provider, call-site catalog, dataflow — underlies a whole family of future rules
and framework features. Building it as a general behavioral layer, rather than as one-off
helpers, is the higher-leverage investment and avoids re-deriving the same machinery per rule.
