import logging
import traceback
import warnings
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from werkzeug.local import LocalProxy, LocalStack

if TYPE_CHECKING:
    from protean import Domain, UnitOfWork

logger = logging.getLogger(__name__)

_domain_ctx_err_msg = """\
Working outside of domain context.
This typically means that you attempted to use functionality that needed
to interface with the current domain object in some way. To solve
this, set up an domain context with domain.domain_context().  See the
documentation for more information.\
"""


def _lookup_domain_object(name: str) -> Any | None:
    top = _domain_context_stack.top
    if top is None:
        warnings.warn(
            _domain_ctx_err_msg,
            stacklevel=3,
        )
        return None
    return getattr(top, name)


def _find_domain() -> "Domain | None":
    top = _domain_context_stack.top
    if top is None:
        logger.debug("=======NO ACTIVE DOMAIN - STACK TRACE - START=======")
        logger.debug("".join(traceback.format_stack()))
        logger.debug("=======NO ACTIVE DOMAIN - STACK TRACE - END=======")
        warnings.warn(
            _domain_ctx_err_msg,
            stacklevel=3,
        )
        return None
    return cast("Domain", top.domain)


def _find_uow() -> "UnitOfWork":
    return cast("UnitOfWork", _uow_context_stack.top)


def _domain_now(now: datetime | None = None) -> datetime:
    """Return the current UTC time from the active domain's injectable clock.

    Reads ``current_domain.clock`` when a domain context is active, so tests can
    freeze time by assigning ``domain.clock`` a stub clock and have deadline,
    lock, and retry boundaries move deterministically. Falls back to real UTC
    time when no domain context is active (a plain script, or a worker before
    bootstrap), keeping the timestamp helpers usable outside a domain. An
    explicit ``now`` short-circuits both — the caller has already read a clock.

    Unlike accessing ``current_domain`` directly, this reads the context stack
    without emitting the "working outside of domain context" warning, so the
    no-context fallback stays silent on every timestamp.

    Both an explicit ``now`` and a value read from an injected clock are
    normalized to timezone-aware UTC (naive datetimes are assumed UTC), so a
    stub clock that returns a naive datetime fails no more loudly than the
    ``datetime.now(UTC)`` it replaces and callers that pass ``now=`` never leak
    a naive value into deadline/lock comparisons or serialization.
    """
    from protean.utils import ensure_utc_aware  # noqa: PLC0415

    if now is not None:
        return ensure_utc_aware(now)
    top = _domain_context_stack.top
    if top is not None:
        clock = getattr(top.domain, "clock", None)
        if clock is not None:
            return ensure_utc_aware(cast(datetime, clock.now()))
    return datetime.now(UTC)


# context locals
# ``mypy`` resolves the obsolete ``types-Werkzeug`` stub package (obsolete since
# werkzeug 2.0, which ships inline ``py.typed``), whose ``LocalStack.__init__`` is
# untyped and non-generic. That produces a spurious ``no-untyped-call`` for a
# source that is genuinely typed upstream, so we cast the class to ``Any`` at the
# construction site. The explicit ``LocalStack`` annotations preserve the type for
# downstream ``.top``/``.push`` access; pyright (which reads the inline types) is
# unaffected.
_domain_context_stack: LocalStack = cast("Any", LocalStack)()
_uow_context_stack: LocalStack = cast("Any", LocalStack)()
current_domain: "Domain" = LocalProxy(_find_domain)  # type: ignore
current_uow: "UnitOfWork" = LocalProxy(_find_uow)  # type: ignore
# ``g`` is a request-scoped scratch namespace (Werkzeug-style) that intentionally
# holds arbitrary attributes; typing it ``Any`` reflects that dynamic contract.
g: Any = LocalProxy(partial(_lookup_domain_object, "g"))

# Only the three request-scoped proxies are public; the lookup helpers and the
# context stacks above stay internal and are excluded from ``import *``.
__all__ = ["current_domain", "current_uow", "g"]
