---
applyTo: "tests/**"
---

# Test review rules

- Flag a new log or metric emission (security, access, perf) without both a
  positive test (it fires when expected) and a negative test (it does not fire
  outside its stated scope).
- Flag a timing test that sleeps just under a deadline and asserts the outcome. It
  flakes under load. Assert the schedule the code recorded instead.
- On a shared `MagicMock` helper, flag overriding a method with `return_value`
  when the helper set `side_effect`. The override does nothing. Set
  `side_effect = None` first.
- A test that handles "unset" values should test the empty shapes (`None`, `""`,
  missing key) against a non-default configured value. With the default
  configured, a wrong fallback is invisible.
- A test that builds its own `Domain(name=...)` must carry
  `@pytest.mark.no_test_domain`.
- A test that needs an external service (PostgreSQL, Redis, Elasticsearch,
  MessageDB) must carry the matching pytest marker. Selection is by marker, not by
  path.
