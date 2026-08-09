"""Reusable deprecation machinery for Protean.

Every deprecation in ``protean.*`` must, per ADR-0004 (Tier 1), emit a
``DeprecationWarning`` that names a specific removal version. This module is the
single place that machinery lives, so the policy cannot drift site by site:

- A base :class:`ProteanDeprecationWarning` plus one subclass per removal
  version (mirroring Django's ``RemovedInDjangoXXWarning`` classes). The
  per-version class makes filtering trivial — a downstream project can promote a
  specific window to an error with
  ``-W error::protean._deprecation.RemovedInProtean018Warning``.
- :func:`warn_deprecated` — emit a consistently formatted warning from inside a
  deprecated code path (e.g. a conditional branch).
- :func:`deprecated` — a decorator for a whole function/method that is going
  away; it warns on every call and otherwise delegates unchanged.

This module is internal (underscore-prefixed): the warning *classes* are a
stable reference point for ``-W`` filters, but the helpers are for framework
code, not application code.
"""

import functools
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import ParamSpec, TypeVar

from protean.ir.diagnostics import DiagnosticCode

_P = ParamSpec("_P")
_R = TypeVar("_R")


class ProteanDeprecationWarning(DeprecationWarning):
    """Base class for every deprecation warning emitted by Protean."""


class RemovedInProtean017Warning(ProteanDeprecationWarning):
    """Marks API scheduled for removal in v0.17.0."""


class RemovedInProtean018Warning(ProteanDeprecationWarning):
    """Marks API scheduled for removal in v0.18.0."""


class RemovedInProtean10Warning(ProteanDeprecationWarning):
    """Marks API deprecated during the 0.x series and removed at v1.0.0."""


# Canonical ``X.Y.Z`` removal version → its warning class. A deprecation must
# cite a version that has a dedicated class; adding a new removal window means
# adding a subclass here so ``-W`` filtering keeps working per-window.
_REMOVAL_WARNINGS: dict[str, type[ProteanDeprecationWarning]] = {
    "0.17.0": RemovedInProtean017Warning,
    "0.18.0": RemovedInProtean018Warning,
    "1.0.0": RemovedInProtean10Warning,
}


def _warning_for_removal(removal: str) -> type[ProteanDeprecationWarning]:
    """Resolve a canonical removal version to its warning class.

    Raises ``ValueError`` for an unknown version so a typo or a missing subclass
    fails loudly at authoring time rather than silently degrading to the base
    class (which would break per-version ``-W`` filtering).
    """
    try:
        return _REMOVAL_WARNINGS[removal]
    except KeyError:
        known = ", ".join(sorted(_REMOVAL_WARNINGS))
        raise ValueError(
            f"No Protean deprecation warning class for removal version "
            f"{removal!r}. Use a canonical X.Y.Z version (known: {known}) or add "
            f"a RemovedInProteanXXWarning subclass in protean/_deprecation.py."
        ) from None


def warn_deprecated(
    subject: str,
    *,
    removal: str | None = None,
    alternative: str | None = None,
    stacklevel: int = 2,
) -> None:
    """Emit a consistently formatted Protean deprecation warning.

    Args:
        subject: What is deprecated, phrased as it should read at the start of
            the sentence (e.g. ``"--debug"`` or ``"assert_valid()"``).
        removal: Canonical ``X.Y.Z`` version the API is removed in, or ``None``
            when no removal is scheduled yet. A recognized version selects its
            per-version warning class; ``None`` or an unrecognized version
            falls back to the base :class:`ProteanDeprecationWarning`. The
            "Will be removed in v<removal>." clause is included whenever
            ``removal`` is given (recognized or not); it is omitted only when
            ``removal`` is ``None``.
        alternative: An optional complete sentence telling the caller what to do
            instead (e.g. ``"Use --log-level DEBUG instead."``).
        stacklevel: Which frame the warning is attributed to, counted from the
            caller of ``warn_deprecated`` (same convention as ``warnings.warn``
            seen from the caller's seat). Default ``2`` points at the caller of
            the *deprecated function* — correct when ``warn_deprecated`` is
            reached one frame down, e.g. from a decorator ``wrapper`` or a shared
            helper. Pass ``1`` when ``warn_deprecated`` is called directly in the
            body of the deprecated code, so the warning lands on that call site.

    An unregistered ``removal`` version degrades to the base
    :class:`ProteanDeprecationWarning` rather than raising: emitting a
    deprecation must never crash the live deprecated code path (the caller's
    program keeps running and is still nudged). Use ``@deprecated`` instead when
    the version can be validated eagerly — it fails fast at import.
    """
    parts = [f"{subject} is deprecated."]
    if alternative:
        parts.append(alternative)
    if removal:
        parts.append(f"Will be removed in v{removal}.")

    category: type[ProteanDeprecationWarning] = (
        _REMOVAL_WARNINGS.get(removal, ProteanDeprecationWarning)
        if removal
        else ProteanDeprecationWarning
    )
    warnings.warn(
        " ".join(parts),
        category,
        # +1 accounts for this helper's own frame so the caller's ``stacklevel``
        # has the same meaning it would when calling ``warnings.warn`` directly.
        stacklevel=stacklevel + 1,
    )


def deprecated(
    *,
    removal: str,
    alternative: str | None = None,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Decorate a deprecated function/method: warn on every call, then delegate.

    The removal version is validated at decoration time, so an unknown version
    fails at import rather than on first call.

    Args:
        removal: Canonical ``X.Y.Z`` version the callable is removed in.
        alternative: An optional complete sentence telling the caller what to do
            instead.

    Example::

        @deprecated(removal="0.18.0", alternative="Call the operation directly.")
        def assert_valid(operation): ...
    """
    _warning_for_removal(removal)  # fail fast on an unknown version

    def decorator(func: Callable[_P, _R]) -> Callable[_P, _R]:
        @functools.wraps(func)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            warn_deprecated(
                f"{func.__name__}()",
                removal=removal,
                alternative=alternative,
            )
            return func(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Deprecation registry
# ---------------------------------------------------------------------------
# The single source of truth for every active framework-API deprecation. Each
# framework-API warn site routes through :func:`warn_from_registry` /
# :func:`deprecated_from_registry`, which read the removal version and "what to
# do instead" clause from the entry here, so a framework deprecation cannot start
# warning without first being registered. (A source-scan test in
# ``tests/ir/test_deprecation_coverage_audit.py`` enforces that no module calls
# the low-level ``warn_deprecated`` / ``@deprecated`` primitives directly; the
# one allowlisted exception is a user-*declared* deprecated event, whose removal
# comes from the user's event meta rather than this registry.) ``protean check``
# reads the same table to audit that every ``detection="check"`` deprecation has
# a rule that can see it statically, and every ``detection="runtime"`` one
# records why it cannot.

# Shared "what to do instead" clause for the email subsystem, deprecated across
# four surfaces (element registration, ``send_email``, ``get_email_provider``,
# and a non-default ``email_providers`` config block). Kept here so the runtime
# warning text and the registry entries never drift apart.
_EMAIL_ALTERNATIVE = (
    "Notify from an event handler or subscriber that calls an "
    "application-level notification service instead."
)


@dataclass(frozen=True)
class Deprecation:
    """One active deprecation and how ``protean check`` can (or cannot) see it.

    ``detection`` splits the two arms:

    - ``"check"`` — a static ``protean check`` rule detects the usage on a
      built domain. ``check_code`` is the diagnostic code that rule emits (e.g.
      ``"DEPRECATED_OPTION"``, ``"DEPRECATED_IMPORT"``), and ``detection_hint``
      is a token guaranteed to appear in *that* diagnostic's message (e.g.
      ``"Method"``, ``"pickled"``, ``"email_providers"``). The coverage audit
      confirms the rule fires by finding a diagnostic whose code is
      ``check_code`` and whose message carries the hint and the removal version,
      so two entries that share a code (``is_event_sourced``/``published`` under
      ``DEPRECATED_OPTION``) are told apart by their hint, and two entries that
      share a hint substring (the email element and the ``email_providers``
      config both say "email subsystem") are told apart by their code.
    - ``"runtime"`` — the usage is an imperative call with no static site, so
      only the per-version ``DeprecationWarning`` can catch it. ``reason``
      records why ``check`` structurally cannot.
    """

    slug: str
    name: str
    since: str
    removal: str
    detection: str
    alternative: str | None = None
    detection_hint: str | None = None
    check_code: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        # A registered removal version must resolve to a warning class, the same
        # eager check ``@deprecated`` makes, so a typo fails at import.
        _warning_for_removal(self.removal)
        if self.detection not in ("check", "runtime"):
            raise ValueError(
                f"Deprecation {self.slug!r} has detection={self.detection!r}; "
                f"expected 'check' or 'runtime'."
            )
        if self.detection == "check":
            # A check entry is proven by a specific rule: it must name both the
            # diagnostic code that rule emits and a token in that message, and it
            # must not carry a runtime ``reason`` (a mixed entry is a mistake, not
            # a valid either/or — reject it here rather than trusting the audit).
            if not self.detection_hint:
                raise ValueError(
                    f"Deprecation {self.slug!r} is detection='check' but has no "
                    f"detection_hint (the token that proves its rule fired)."
                )
            if not self.check_code:
                raise ValueError(
                    f"Deprecation {self.slug!r} is detection='check' but has no "
                    f"check_code (the diagnostic code its rule emits)."
                )
            if self.reason:
                raise ValueError(
                    f"Deprecation {self.slug!r} is detection='check' but also "
                    f"carries a runtime `reason`; a check entry is proven by its "
                    f"rule, not a reason."
                )
        else:  # runtime
            if not self.reason:
                raise ValueError(
                    f"Deprecation {self.slug!r} is detection='runtime' but records "
                    f"no reason for why `protean check` cannot see it statically."
                )
            if self.detection_hint or self.check_code:
                raise ValueError(
                    f"Deprecation {self.slug!r} is detection='runtime' but carries "
                    f"a static detection_hint/check_code; a runtime entry has no "
                    f"firing check rule."
                )


DEPRECATIONS: dict[str, Deprecation] = {
    entry.slug: entry
    for entry in (
        Deprecation(
            slug="is_event_sourced_alias",
            name="`is_event_sourced=` option alias",
            since="0.13.0",
            removal="1.0.0",
            detection="check",
            alternative="Use `event_sourced` instead.",
            detection_hint="is_event_sourced",
            check_code=DiagnosticCode.DEPRECATED_OPTION.value,
        ),
        Deprecation(
            slug="command_published_option",
            name="`published` option on a command",
            since="0.13.0",
            removal="1.0.0",
            detection="check",
            alternative=(
                "Commands are internal to the bounded context; only events "
                "are published. It has no effect."
            ),
            detection_hint="published",
            check_code=DiagnosticCode.DEPRECATED_OPTION.value,
        ),
        Deprecation(
            slug="email_element",
            name="`@domain.email` element",
            since="0.12.0",
            removal="1.0.0",
            detection="check",
            alternative=_EMAIL_ALTERNATIVE,
            detection_hint="email subsystem",
            check_code=DiagnosticCode.DEPRECATED_EMAIL.value,
        ),
        Deprecation(
            slug="method_field",
            name="`Method` field type",
            since="0.12.0",
            removal="1.0.0",
            detection="check",
            alternative="Serializer fields are no longer supported.",
            detection_hint="Method",
            check_code=DiagnosticCode.DEPRECATED_IMPORT.value,
        ),
        Deprecation(
            slug="nested_field",
            name="`Nested` field type",
            since="0.12.0",
            removal="1.0.0",
            detection="check",
            alternative="Serializer fields are no longer supported.",
            detection_hint="Nested",
            check_code=DiagnosticCode.DEPRECATED_IMPORT.value,
        ),
        Deprecation(
            slug="list_pickled",
            name="`pickled=` argument on `List`",
            since="0.12.0",
            removal="1.0.0",
            detection="check",
            alternative="It has no effect.",
            detection_hint="pickled",
            check_code=DiagnosticCode.DEPRECATED_FIELD.value,
        ),
        Deprecation(
            slug="email_providers_config",
            name="`email_providers` config block",
            since="0.12.0",
            removal="1.0.0",
            detection="check",
            alternative=_EMAIL_ALTERNATIVE,
            detection_hint="email_providers",
            check_code=DiagnosticCode.DEPRECATED_CONFIG.value,
        ),
        Deprecation(
            slug="utils_plumbing",
            name="`protean.utils.*` import shims",
            since="0.12.0",
            removal="1.0.0",
            detection="check",
            alternative="It is internal plumbing with no public replacement.",
            detection_hint="protean.utils",
            check_code=DiagnosticCode.DEPRECATED_IMPORT.value,
        ),
        Deprecation(
            slug="get_email_provider",
            name="`Domain.get_email_provider()`",
            since="0.12.0",
            removal="1.0.0",
            detection="runtime",
            alternative=_EMAIL_ALTERNATIVE,
            reason=(
                "An imperative method call has no static declaration site for a "
                "rule to read off a built domain; the per-call "
                "RemovedInProtean10Warning is the only detector."
            ),
        ),
        Deprecation(
            slug="send_email",
            name="`Domain.send_email()`",
            since="0.12.0",
            removal="1.0.0",
            detection="runtime",
            alternative=_EMAIL_ALTERNATIVE,
            reason=(
                "An imperative method call has no static declaration site for a "
                "rule to read off a built domain; the per-call "
                "RemovedInProtean10Warning is the only detector."
            ),
        ),
        Deprecation(
            slug="assert_valid",
            name="`assert_valid()`",
            since="0.16.1",
            removal="0.18.0",
            detection="runtime",
            alternative="Call the operation directly instead.",
            reason=(
                "A test-only helper; `protean check` scans domain source, not "
                "test suites (ADR-0019), so it never sees the call site."
            ),
        ),
        Deprecation(
            slug="assert_invalid",
            name="`assert_invalid()`",
            since="0.16.1",
            removal="0.18.0",
            detection="runtime",
            alternative="Use pytest.raises(ValidationError, match=...) instead.",
            reason=(
                "A test-only helper; `protean check` scans domain source, not "
                "test suites (ADR-0019), so it never sees the call site."
            ),
        ),
    )
}


def warn_from_registry(slug: str, subject: str, *, stacklevel: int = 2) -> None:
    """Emit a deprecation warning for a registered deprecation.

    The removal version and "what to do instead" clause come from
    ``DEPRECATIONS[slug]``, so a warning cannot exist without a registry entry
    (a missing slug raises ``KeyError`` at the call site). ``subject`` stays at
    the call site because several sites build it dynamically (e.g. the
    per-name ``protean.utils.<name>`` subject).

    ``stacklevel`` has the same meaning as in :func:`warn_deprecated` — it is
    counted from the caller of *this* function, and the extra frame this wrapper
    adds is accounted for internally, so attribution is unchanged from calling
    :func:`warn_deprecated` directly.
    """
    entry = DEPRECATIONS[slug]
    warn_deprecated(
        subject,
        removal=entry.removal,
        alternative=entry.alternative,
        stacklevel=stacklevel + 1,
    )


def deprecated_from_registry(
    slug: str,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """``@deprecated`` for a registered deprecation, sourcing its removal version
    and alternative from ``DEPRECATIONS[slug]`` (a missing slug raises
    ``KeyError`` at import, so a decorated deprecation cannot skip the registry).
    """
    entry = DEPRECATIONS[slug]
    return deprecated(removal=entry.removal, alternative=entry.alternative)
