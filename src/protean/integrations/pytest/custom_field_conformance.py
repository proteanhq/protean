"""Custom-field conformance harness.

A reusable check a ``Custom``-built field runs against itself. Import
``run_custom_field_conformance``, hand it a ``Custom(...)`` field plus a raw
value that should parse, the value it should parse to, and a raw value that
should be rejected. The harness declares a throwaway aggregate carrying the
field, then asserts the whole custom-field contract holds:

- the outcome of each validation stage (a missing value resolves to the
  default, or to ``None``; the cast parses a raw value into the type and
  rejects one it cannot parse),
- the ``ResolvedField`` reflection an adapter reads (``required`` and a
  JSON-serializable ``as_dict``),
- a serialize, persist, reload, and event-replay round-trip.

It builds its own in-memory domain, so a third party needs nothing from
Protean's own test tree to run it. This mirrors the adapter conformance harness
in ``protean.integrations.pytest.adapter_conformance``.
"""

from __future__ import annotations

import json
from typing import Any

from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.exceptions import ValidationError
from protean.fields.resolved import ResolvedField
from protean.fields.spec import _UNSET, FieldSpec
from protean.utils.reflection import fields


def run_custom_field_conformance(
    field: FieldSpec,
    *,
    valid_input: Any,
    expected: Any,
    invalid_input: Any,
) -> None:
    """Assert a ``Custom`` field honours the custom-field contract.

    ``field`` is the ``Custom(...)`` spec under test. ``valid_input`` is a raw
    value the field should parse; ``expected`` is what it should parse to
    (compared with ``==``, so the custom type needs a meaningful ``__eq__``).
    ``invalid_input`` is a raw value the field should reject.

    Raises ``AssertionError`` on any contract violation.
    """
    if not isinstance(field, FieldSpec):
        raise TypeError(
            "run_custom_field_conformance expects a FieldSpec built by Custom(); "
            f"got {type(field).__name__}"
        )
    # Every built-in factory returns a FieldSpec too, so the isinstance check
    # alone would let a String() through and report it as custom-field
    # conformance. Only Custom() stamps field_kind="custom".
    if field.field_kind != "custom":
        raise TypeError(
            "run_custom_field_conformance expects a field built by Custom(); "
            f"got a field of kind {field.field_kind!r}"
        )

    domain = Domain(name="CustomFieldConformance")
    domain.config["event_processing"] = "sync"

    # A throwaway aggregate carrying only the field under test (plus the
    # auto-generated id). Assignment style so ``resolve_fieldspecs`` collects it.
    subject = type(
        "CustomFieldConformanceSubject",
        (BaseAggregate,),
        {"sample": field},
    )
    domain.register(subject, fact_events=True)
    domain.init(traverse=False)

    with domain.domain_context():
        _assert_cast(subject, valid_input, expected)
        _assert_rejects_invalid(subject, invalid_input)
        _assert_empty_handling(subject, field)
        resolved = _assert_reflection(subject, field, expected)
        _assert_round_trip(domain, subject, valid_input, expected, resolved)


def _assert_cast(subject: Any, valid_input: Any, expected: Any) -> None:
    """The cast parses a raw value into the field's type."""
    instance = subject(sample=valid_input)
    assert instance.sample == expected, (
        f"casting {valid_input!r} produced {instance.sample!r}, expected {expected!r}"
    )


def _assert_rejects_invalid(subject: Any, invalid_input: Any) -> None:
    """A raw value the cast cannot parse is rejected as a ValidationError."""
    try:
        subject(sample=invalid_input)
    except ValidationError:
        return
    raise AssertionError(
        f"{invalid_input!r} was accepted; the cast did not reject an invalid value"
    )


def _assert_empty_handling(subject: Any, field: FieldSpec) -> None:
    """Empty short-circuits before the cast.

    A required field rejects a missing value. An optional field left unset falls
    back to its declared default, or to ``None`` when it has none; either way the
    parser is not asked to make an instance out of nothing.
    """
    if field.required:
        try:
            subject()
        except ValidationError:
            return
        raise AssertionError(
            "a required Custom field accepted a missing value; it must reject it"
        )

    instance = subject()

    if field.default is not _UNSET:
        # A declared default is what a missing value resolves to. It may be an
        # instance of the custom type, a raw value, or a callable producing
        # either; Pydantic does not run the parser over it.
        expected_default = field.default() if callable(field.default) else field.default
        assert instance.sample == expected_default, (
            f"an optional Custom field left unset should fall back to its "
            f"default {expected_default!r}, got {instance.sample!r}"
        )
        return

    assert instance.sample is None, (
        f"an optional Custom field left unset should be None, got {instance.sample!r}"
    )


def _assert_reflection(subject: Any, field: FieldSpec, expected: Any) -> ResolvedField:
    """The field surfaces as a ResolvedField with a JSON-serializable as_dict."""
    resolved = fields(subject)["sample"]
    assert isinstance(resolved, ResolvedField), (
        f"expected a ResolvedField for the custom field, got {type(resolved).__name__}"
    )
    assert resolved.required == field.required, (
        f"ResolvedField.required is {resolved.required}, "
        f"but the field was declared required={field.required}"
    )
    serialized = resolved.as_dict(expected)
    # Must not raise: the persistence and event payloads are JSON-encoded, so a
    # custom value that as_dict leaves unserialized would break the round-trip.
    json.dumps(serialized)
    return resolved


def _assert_round_trip(
    domain: Domain,
    subject: Any,
    valid_input: Any,
    expected: Any,
    resolved: ResolvedField,
) -> None:
    """Serialize, persist, reload, and replay from the fact event."""
    instance = subject(sample=valid_input)
    repository = domain.repository_for(subject)
    repository.add(instance)

    reloaded = repository.get(instance.id)
    assert reloaded.sample == expected, (
        f"reloaded value {reloaded.sample!r} does not equal the original {expected!r}"
    )
    # The reloaded value serializes the same way, so a second save would match.
    json.dumps(resolved.as_dict(reloaded.sample))

    store = domain.event_store.store
    assert store is not None, "the domain has no configured event store"
    fact_stream = f"{subject.meta_.stream_category}-fact-{instance.id}"
    messages = store.read(fact_stream)
    assert len(messages) > 0, (
        "expected a fact event on persistence but the stream was empty"
    )
    replayed: Any = messages[-1].to_domain_object()
    assert replayed.sample == expected, (
        f"value replayed from the fact event {replayed.sample!r} does not equal "
        f"the original {expected!r}"
    )
