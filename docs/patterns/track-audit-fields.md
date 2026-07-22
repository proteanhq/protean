# Track Audit and Lifecycle Fields

<span class="pathway-tag pathway-tag-cqrs">CQRS</span>

## The Problem

Almost every persisted aggregate wants four cross-cutting fields:

- `created_at` / `updated_at` — when the row was first written and last changed.
- `created_by` / `updated_by` — which user made those changes.

These have nothing to do with the aggregate's business rules, but if you leave
them to each aggregate you end up re-implementing the same thing everywhere:
setting `updated_at = now()` at the top of every mutating method, and threading
the current user down into the domain by hand. Miss one method and the audit
trail is quietly wrong.

The two halves of the problem are different in nature. Timestamps are a pure
function of *when* the save happens. Audit users are a function of *who* is
acting — context the aggregate should not have to know about. Protean solves
each with the mechanism that fits it.

## The Pattern

Put the cross-cutting fields on an **abstract base aggregate** and inherit it.
Let the framework fill them in on save:

- Timestamps are **declarative** — `auto_now_add` / `auto_now` flags on the
  `DateTime` fields.
- Audit users come from a **pre-persist enricher** that reads the acting user
  from the domain context and stamps them just before the save.

The aggregate stays focused on its business behavior; the base and the enricher
carry the bookkeeping.

## How Protean Supports This

### An abstract audit base

```python
from protean import Domain
from protean.fields import DateTime, String

domain = Domain()


@domain.aggregate(abstract=True, auto_add_id_field=False)
class Audited:
    created_at: DateTime(auto_now_add=True)   # stamped once, on create
    updated_at: DateTime(auto_now=True)       # stamped on every save
    created_by: String(max_length=50)
    updated_by: String(max_length=50)


@domain.aggregate
class Article(Audited):
    title: String(max_length=200)
    body: String(max_length=5000)
```

`auto_now_add` and `auto_now` are Django-parity flags on `DateTime` (and
`Date`). They are stamped in the persistence path, so an `auto_now*` field is
`None` until the first save. The two are mutually exclusive.

### A pre-persist enricher for the acting user

Register a callback that stamps the audit users just before an aggregate is
saved. It **mutates the aggregate in place** (unlike event/command enrichers,
which return metadata), and it runs on both create and update:

```python
from protean.utils.globals import g


@domain.aggregate_enricher
def stamp_audit_user(aggregate):
    user = g.get("current_user")
    aggregate.updated_by = user
    if aggregate.created_by is None:   # set once, on create; preserved after
        aggregate.created_by = user
```

Setting `created_by` only when it is unset is what keeps it stable across later
updates while `updated_by` refreshes every time.

### Supplying the acting user

The enricher reads `current_user` off the domain context, so put it there at the
edge of your application (an HTTP middleware, a CLI entry point, a worker):

```python
with domain.domain_context(current_user="alice"):
    repo = domain.repository_for(Article)
    repo.add(Article(title="Hello", body="..."))
```

## Applying the Pattern

Create and update, end to end:

```python
# Create — as "alice"
with domain.domain_context(current_user="alice"):
    repo = domain.repository_for(Article)
    article = Article(title="Draft", body="...")
    repo.add(article)
    article_id = article.id

stored = domain.repository_for(Article).get(article_id)
# stored.created_at and stored.updated_at are set
# stored.created_by == stored.updated_by == "alice"

# Update — as "bob"
with domain.domain_context(current_user="bob"):
    repo = domain.repository_for(Article)
    article = repo.get(article_id)
    article.title = "Published"
    repo.add(article)

final = domain.repository_for(Article).get(article_id)
# final.created_at unchanged; final.updated_at advanced
# final.created_by == "alice"; final.updated_by == "bob"
```

## Where it applies

The stamping and the enricher run on the `repository.add()` → save path -- the
same place Protean manages aggregate versions. They deliberately do **not** run
on two escape hatches:

- **Bulk updates.** A set-based `repository.query.filter(...).update(...)` issues
  one store-level `UPDATE` and runs no per-row Python, so it does not stamp. This
  matches Django, where `auto_now` fires on `Model.save()` but not
  `QuerySet.update()`. Load and save when you need the stamps.
- **Event-sourced aggregates.** These persist as a stream of events, not rows in
  a table, so there are no columns to stamp. Record who and when *in the events*
  themselves (see [Message Enrichment](../guides/domain-behavior/message-enrichment.md)
  for event-level metadata). This recipe is for state-based (DDD/CQRS) aggregates.

## Anti-Patterns

### Stamping in every mutator

Setting `updated_at = utc_now()` at the top of each business method works but
drifts: the one method that forgets it leaves a stale timestamp, and there is no
single place to audit. `auto_now` removes the need entirely.

### Overloading the enricher with business logic

The pre-persist enricher is powerful — it *can* mutate any field or raise an
exception. Keep it to cross-cutting lifecycle/audit metadata. Business state
changes belong in the aggregate's own named methods, where they can raise events
and be tested in isolation. The enricher is a bookkeeping hook, not an escape
hatch.

### Modeling the acting user inside the domain

The framework supplies the *hook* and the *stamping mechanism*, not a user
model. `created_by`/`updated_by` are whatever your application puts on the
context — a user id, a username, a service name. Keep the identity concern in
your application layer.

---

!!! tip "See also"
    - [Simple Fields — Auto-populated timestamps](../reference/fields/simple-fields.md#auto-populated-timestamps) — the `auto_now`/`auto_now_add` reference
    - [Message Enrichment](../guides/domain-behavior/message-enrichment.md#aggregate-pre-persist-enrichers) — the aggregate enricher alongside event/command enrichers
    - [Multi-Tenancy](multi-tenancy.md) — the same context-propagation approach applied to tenant isolation
