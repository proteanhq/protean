import contextvars
import logging
import sys
import traceback
import types
import warnings
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

if TYPE_CHECKING:
    from protean import Domain, UnitOfWork
    from protean.domain.context import DomainContext

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

_domain_ctx_err_msg = """\
Working outside of domain context.
This typically means that you attempted to use functionality that needed
to interface with the current domain object in some way. To solve
this, set up an domain context with domain.domain_context().  See the
documentation for more information.\
"""


class _ContextStack(Generic[_T]):
    """A contextvars-backed stack preserving ``push``/``pop`` nesting.

    Replaces Werkzeug's ``LocalStack`` for the domain and Unit-of-Work context
    stacks. Each execution context (OS thread or asyncio task) gets its own
    list via ``contextvars.ContextVar``. The list is replaced on every mutation,
    which keeps the stack correct across ``await`` boundaries without
    thread-local machinery.
    """

    def __init__(self, name: str) -> None:
        self._var: contextvars.ContextVar[list[_T]] = contextvars.ContextVar(name)

    @property
    def top(self) -> _T | None:
        stack = self._var.get([])
        return stack[-1] if stack else None

    def push(self, obj: _T) -> None:
        stack = self._var.get([])
        self._var.set([*stack, obj])

    def pop(self) -> _T | None:
        stack = self._var.get([])
        if not stack:
            return None
        self._var.set(stack[:-1])
        return stack[-1]


class _ContextLocalProxy(Generic[_T]):
    """A proxy that resolves the wrapped object on every access.

    Replaces Werkzeug's ``LocalProxy`` for ``current_domain``,
    ``current_uow``, and ``g``. When a lookup returns an object, attribute
    get/set/delete, containment, iteration, representation, truthiness, and
    comparison delegate to that object. When no object is active, the proxy
    behaves like ``None``: it is falsy, its representation and string form are
    ``"None"``, it compares equal to ``None``, and containment/iteration raise
    the same ``TypeError`` that ``None`` would.
    """

    _lookup: Callable[[], _T | None]

    def __init__(self, lookup: Callable[[], _T | None]) -> None:
        object.__setattr__(self, "_lookup", lookup)

    def _get_current_object(self) -> _T | None:
        return self._lookup()

    def _get_object_or_raise(self, name: str) -> _T:
        obj = self._get_current_object()
        if obj is None:
            raise AttributeError(name)
        return obj

    @property  # type: ignore[misc]
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        # ``object.__class__`` is a read/write property; overriding it read-only
        # is deliberate (the proxy reports the wrapped type for ``isinstance``),
        # so silence the incompatible-override report.
        obj = self._get_current_object()
        if obj is None:
            return type(self)
        return type(obj)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_object_or_raise(name), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._get_object_or_raise(name), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(self._get_object_or_raise(name), name)

    def __bool__(self) -> bool:
        obj = self._get_current_object()
        return bool(obj) if obj is not None else False

    def __repr__(self) -> str:
        obj = self._get_current_object()
        if obj is None:
            return repr(None)
        return repr(obj)

    def __str__(self) -> str:
        obj = self._get_current_object()
        if obj is None:
            return "None"
        return str(obj)

    def __eq__(self, other: object) -> bool:
        obj = self._get_current_object()
        if obj is None:
            return other is None
        return bool(obj == other)

    def __hash__(self) -> int:
        obj = self._get_current_object()
        if obj is None:
            return hash(None)
        return hash(obj)

    def __dir__(self) -> list[str]:
        obj = self._get_current_object()
        return list(dir(obj))

    def __contains__(self, item: object) -> bool:
        obj = self._get_current_object()
        return item in obj  # type: ignore[operator]

    def __iter__(self) -> Iterator[Any]:
        obj = self._get_current_object()
        return iter(obj)  # type: ignore[no-any-return, call-overload]


def _warning_stacklevel() -> int:
    """Return a stacklevel that points at the first frame outside this module.

    The warning must appear to come from user code, not from the proxy or stack
    helpers inside this module. Walk up from the caller of
    ``_active_domain_context`` until we leave ``protean.utils.globals``.
    """
    frame: types.FrameType | None = sys._getframe(2)  # caller of _active_domain_context
    stacklevel = 2
    while frame is not None and frame.f_globals.get("__name__") == __name__:
        frame = frame.f_back
        stacklevel += 1
    return stacklevel


def _active_domain_context(log_traceback: bool = False) -> "DomainContext | None":
    top = _domain_context_stack.top
    if top is None:
        if log_traceback:
            logger.debug("=======NO ACTIVE DOMAIN - STACK TRACE - START=======")
            logger.debug("".join(traceback.format_stack()))
            logger.debug("=======NO ACTIVE DOMAIN - STACK TRACE - END=======")
        warnings.warn(
            _domain_ctx_err_msg,
            stacklevel=_warning_stacklevel(),
        )
    return top


def _lookup_domain_object(name: str) -> Any | None:
    top = _active_domain_context()
    return getattr(top, name) if top is not None else None


def _find_domain() -> "Domain | None":
    top = _active_domain_context(log_traceback=True)
    return top.domain if top is not None else None


def _find_uow() -> "UnitOfWork | None":
    return _uow_context_stack.top


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
_domain_context_stack: _ContextStack[Any] = _ContextStack("protean.domain_context")
_uow_context_stack: _ContextStack[Any] = _ContextStack("protean.uow_context")
current_domain: "Domain" = _ContextLocalProxy(_find_domain)  # type: ignore[assignment]
current_uow: "UnitOfWork" = _ContextLocalProxy(_find_uow)  # type: ignore[assignment]
# ``g`` is a request-scoped scratch namespace that intentionally holds arbitrary
# attributes; typing it ``Any`` reflects that dynamic contract.
g: Any = _ContextLocalProxy(partial(_lookup_domain_object, "g"))

# Only the three request-scoped proxies are public; the lookup helpers and the
# context stacks above stay internal and are excluded from ``import *``.
__all__ = ["current_domain", "current_uow", "g"]
