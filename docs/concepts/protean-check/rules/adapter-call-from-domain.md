# ADAPTER_CALL_IN_DOMAIN

| | |
|---|---|
| **Code** | `ADAPTER_CALL_IN_DOMAIN` |
| **Category** | `bounded_context` |
| **Level** | `warning` |
| **Opt-in** | `[lint].check_adapter_calls = true` |

## What it flags

A domain element whose **method body calls a concrete adapter** under
`protean.adapters`. `protean check` reports one finding per call-site, naming the
element, the method, the adapter symbol, and the source line.

This catches runtime coupling one level deeper than `INFRA_IMPORT_IN_DOMAIN`,
which reads only module-level imports. It reads method bodies through the
[behavioral analysis substrate](../behavioral-analysis.md). An adapter reached
through `import protean` attribute
access — `protean.adapters.broker.inline.InlineBroker(...)` — is a real call-site
coupling that the module-level import rule's name-prefix check does not see,
because the module imports only `protean`.

## Opt-in

The rule is **off by default**. Turn it on in `domain.toml`:

```toml
[lint]
check_adapter_calls = true
```

It parses method bodies, which is heavier than the module-import scan
`INFRA_IMPORT_IN_DOMAIN` does, so it stays opt-in per
[ADR-0019](../../../adr/0019-check-engine-determinism-boundary-and-behavioral-substrate.md).
It uses a dedicated
flag rather than reusing `check_infra_imports`, so each rule is switchable on its
own — turning on the call-site rule never changes what the import rule does.

## Scope and limits

The rule walks **every non-internal registered domain element** — aggregates,
entities, value objects, repositories, handlers, domain services, process
managers, subscribers — in fqn order, and reads the methods **defined in each
element's own class body**. It is deliberately **conservative**: it flags a call
only when the callee **statically resolves** under `protean.adapters`. A call
whose callee cannot be resolved is **skipped, never guessed at**, keeping the
rule on the deterministic side of ADR-0019.

Because it reads only an element's own top-level methods, it does **not** see an
adapter call that sits in a method inherited from a non-registered base or mixin,
in a class-attribute default, at module level, or nested inside another `def`,
`lambda`, or class within a method — those are conservative, by-design misses,
not violations the rule certifies absent. In particular, it does not flag:

- **A class that is not a registered domain element.** Only registered elements
  are visited, so a plain helper class calling an adapter is out of scope.
- **A function-local import.** `from protean.adapters... import X` inside a
  method binds a name the module symbol table does not carry, so the call does
  not resolve.
- **A fetched or injected receiver.** An adapter held in a local variable
  (`broker = self.brokers["default"]; broker.publish(...)`) or reached through
  `current_domain.providers[...]` has an unresolvable receiver root.
- **A self-rooted call.** `self._dao.filter(...)` resolves to no FQN, so
  legitimate repository/DAO use is never flagged.

## Why it matters

Calling into `protean.adapters` from a domain method couples the domain layer to
a specific adapter at runtime and breaks the ports-and-adapters boundary. The
domain should depend on abstractions and let the concrete adapter be wired
through the domain's provider configuration, so infrastructure can be swapped
(memory for tests, Postgres for production) without editing domain code.

## Example

Flagged — a domain method constructs a concrete broker adapter:

```python
import protean
from protean import Domain
from protean.fields import String

domain = Domain(name="app")

@domain.aggregate
class Order:
    name = String(max_length=50)

    def provision(self):
        # calls protean.adapters.* -> ADAPTER_CALL_IN_DOMAIN
        return protean.adapters.broker.inline.InlineBroker("default", None, {})
```

Compliant — the domain names no adapter; a self-rooted repository call resolves
to no FQN and is not flagged:

```python
@domain.aggregate
class Order:
    name = String(max_length=50)

    def total(self):
        return self._dao.filter(name="x")   # self-rooted -> no finding
```

## How to fix

- Remove the `protean.adapters` call from the domain method.
- Depend on a domain-layer abstraction and let the adapter be wired through the
  domain's provider configuration instead.

## Suppressing

Suppress the rule for a single element with `suppress_checks`:

```python
@domain.aggregate(suppress_checks=["ADAPTER_CALL_IN_DOMAIN"])
class Order:
    name = String(max_length=50)

    def provision(self):
        return protean.adapters.broker.inline.InlineBroker("default", None, {})
```

To adopt the rule on a codebase with pre-existing violations, grandfather the
first *N* findings with the `[lint].suppressions` allow-list:

```toml
[lint]
check_adapter_calls = true
suppressions = { ADAPTER_CALL_IN_DOMAIN = 3 }
```
