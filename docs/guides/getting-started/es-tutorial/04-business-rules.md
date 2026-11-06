# Chapter 4: Business Rules That Never Break

A tester discovers a problem: a withdrawal of $200 from an account with $100
succeeds. The validation in `withdraw()` checks the balance *before* the
`@apply` handler runs. What if the validation and the state mutation disagree?

You fix this problem with **invariants**. An invariant is a rule that Protean
checks *after* every state mutation. Invariants keep the aggregate **always
valid**, whichever path changed its state.

## The Problem with Method-Level Validation

In Chapter 2, our `withdraw()` method checked `if amount > self.balance`. This
works for the simple case. The check has a subtle issue, though: it runs before
`raise_()` calls the `@apply` handler. If any future code path changes the
balance between the check and the event, the validation could be bypassed.

Invariants solve this by validating the aggregate's state **after**
the `@apply` handler has already mutated it.

## Post-Invariants

Add two invariants to the `Account` aggregate:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch04.py:invariants"
```

Here is how they work:

1. When `raise_()` is called on an event-sourced aggregate, Protean:
    - Records the event
    - Calls the matching `@apply` handler (state is mutated)
    - Runs all `@invariant.post` methods
    - If any invariant raises `ValidationError`, Protean rejects the event.
      Protean then skips recording the event, leaves the version unchanged, and
      undoes the handler's field changes

2. **`balance_must_not_be_negative`** ensures no operation can leave
   the account with a negative balance. You no longer need the manual check in
   `withdraw()`, because the invariant rejects any withdrawal that leaves the
   balance negative.

3. **`closed_account_must_have_zero_balance`** ensures an account
   cannot be closed while funds remain. This rule would be difficult to
   enforce with method-level checks alone because it spans two fields
   (`status` and `balance`).

## Closing an Account

We also add an `AccountClosed` event and a `close()` method:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch04.py:account_closed_event"
```

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch04.py:close_method"
```

And the corresponding `@apply` handler:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch04.py:apply_account_closed"
```

## Invariants in Action

Let's exercise both invariants:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch04.py:usage"
```

Run it:

```shell
$ python fidelis.py
Account opened: acc-001-uuid...
Overdraft rejected: {'balance': ['Insufficient funds: balance cannot be negative']}
Close rejected: {'status': ['Cannot close account with non-zero balance']}

Account status: CLOSED
Balance: $0.00

All checks passed!
```

`balance_must_not_be_negative` caught the overdraft attempt. The `@apply`
handler reduced the balance to -$100, the invariant detected the violation, and
Protean rejected the event.

`closed_account_must_have_zero_balance` caught the close attempt. The `@apply`
handler set `status = "CLOSED"`, but the invariant saw the balance was still
$100 and rejected the transition.

## Why Invariants Are Better

Invariants have important advantages over method-level checks:

| Method-Level Checks | Invariants |
|---------------------|-----------|
| Run before the event | Run after the `@apply` handler |
| Check preconditions | Validate postconditions |
| Can be bypassed by new code paths | Always enforced, every time |
| Do not run during replay | Also enforced during replay |
| Must be duplicated across methods | Defined once, applied everywhere |

!!! tip "Always Valid"
    Post-invariants guarantee that the aggregate is in a valid state after
    every single event. This is the "always valid" principle. The aggregate is
    never in an invalid state, at any point.

## What We Built

- **Post-invariants** with `@invariant.post` that validate state after
  every `@apply` handler.
- **`balance_must_not_be_negative`**: Prevents overdrafts at the
  aggregate level.
- **`closed_account_must_have_zero_balance`**: Enforces a
  multi-field business rule.
- An **AccountClosed** event and `close()` method.
- Business rules **always enforced**, whichever code path modifies the
  aggregate.

Chapter 5 adds automated tests written with Protean's fluent testing DSL.

## Full Source

??? example "ch04.py, 246 lines"

    ```python
    --8<-- "guides/getting-started/es-tutorial/ch04.py:full"
    ```

## Next

[Chapter 5: Testing the Ledger →](05-testing-the-ledger.md)
