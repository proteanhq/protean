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
from typing import ParamSpec, TypeVar

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
            per-version warning class; ``None`` (or an unrecognized version)
            uses the base :class:`ProteanDeprecationWarning` and omits the
            "Will be removed" clause.
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
