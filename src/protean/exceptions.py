"""
Custom Protean exception classes
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

# Re-exported here as the public, stable category users filter on to promote
# Protean deprecations to errors in CI (see ADR-0004). The emission machinery
# and per-version subclasses live in ``protean._deprecation``.
from protean._deprecation import ProteanDeprecationWarning

if TYPE_CHECKING:
    from protean.ir.diagnostics import CodeMeta, DiagnosticCode

__all__ = [
    "CommandExpiredError",
    "ConfigurationError",
    "DatabaseError",
    "DeserializationError",
    "DuplicateCommandError",
    "ExpectedVersionError",
    "IncorrectUsageError",
    "InsufficientDataError",
    "InvalidDataError",
    "InvalidOperationError",
    "InvalidStateError",
    "NoDomainException",
    "NotSupportedError",
    "ObjectNotFoundError",
    # Re-exported deprecation category (see the import above); the public,
    # stable filter target users promote to errors in CI.
    "ProteanDeprecationWarning",
    "ProteanException",
    "ProteanExceptionWithMessage",
    "SendError",
    "TooManyObjectsError",
    "TransactionError",
    "ValidationError",
]

logger = logging.getLogger(__name__)


_SECURITY_DETAIL_MAX_LEN = 256


def _emit_security_event(event_type: str, args: tuple[Any, ...]) -> None:
    """Route boundary-level exceptions to the ``protean.security`` logger.

    Only emits when a domain handler is on the stack (``g.message_in_context``
    is set). Exceptions constructed in tests, fixtures, REPL sessions, or
    framework internals that catch and recover (e.g. ``UnitOfWork`` state
    checks) therefore stay off the channel — matching the gating applied to
    ``invariant_failed``.

    Imports are lazy because ``protean.domain.context`` transitively pulls
    in ``protean.adapters``, which imports back from ``protean.exceptions``.
    Lifting these to module level would break package initialization.
    """
    from protean.domain.context import has_domain_context  # noqa: PLC0415
    from protean.integrations.logging import log_security_event  # noqa: PLC0415
    from protean.utils.globals import g  # noqa: PLC0415

    if not has_domain_context() or g.get("message_in_context") is None:
        return

    detail = str(args[0])[:_SECURITY_DETAIL_MAX_LEN] if args else ""
    log_security_event(event_type, detail=detail)


class ProteanException(Exception):
    """Base class for all Exceptions raised within Protean.

    A raise site may pass ``code`` (a :class:`~protean.ir.diagnostics.DiagnosticCode`)
    and ``location`` to carry a stable, machine-readable diagnostic alongside the
    prose message. ``rationale`` and ``fix`` then resolve from the registry, so an
    agent or operator catching the exception gets the same coded rationale/fix an
    IR-build diagnostic carries. Both default to ``None`` when no code is given,
    so every existing raise keeps working unchanged.
    """

    def __init__(
        self,
        *args: Any,
        code: DiagnosticCode | None = None,
        location: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args)

        self.extra_info = kwargs.get("extra_info")
        # Stored as the plain string value so it pickles without dragging the
        # enum (and the ``protean.ir`` import) across the wire.
        self.code: str | None = code.value if code is not None else None
        self.location: str | None = location

    @property
    def rationale(self) -> str | None:
        """The registry rationale for this exception's ``code``, or ``None``."""
        meta = self._resolved()
        return meta.rationale if meta is not None else None

    @property
    def fix(self) -> str | None:
        """The registry fix for this exception's ``code``, or ``None``."""
        meta = self._resolved()
        return meta.fix if meta is not None else None

    def _resolved(self) -> CodeMeta | None:
        # ``None`` when there is no code, or when the code does not resolve in
        # this Protean version — a code renamed or removed since the exception
        # was pickled still deserializes and keeps its ``code`` string; only
        # ``rationale``/``fix`` read as ``None``, so reading a coded exception
        # never raises. Imported lazily because ``protean.ir`` imports back from
        # this module, and only on read, never on the raise path.
        if self.code is None:
            return None
        from protean.ir.diagnostics import (  # noqa: PLC0415
            DiagnosticCode,
            resolve,
        )

        try:
            return resolve(DiagnosticCode(self.code))
        except (ValueError, KeyError):
            return None

    def __reduce__(self) -> tuple[Any, tuple[Any, ...], dict[str, Any]]:
        # Carry ONLY the diagnostic attributes as state. Serializing the whole
        # ``__dict__`` would drag subclass payloads across the wire — e.g.
        # ``DatabaseError.original_exception``, often a live, unpicklable driver
        # error — and break pickling on the very outbox/broker boundary the code
        # is meant to survive. The positional arg reconstructs the message as
        # before; other subclass attributes stay dropped, exactly as they were.
        return (self.__class__, self.args[:1], self._diagnostic_state())

    def _diagnostic_state(self) -> dict[str, Any]:
        return {"code": self.code, "location": self.location}


class ProteanExceptionWithMessage(ProteanException):
    def __init__(
        self,
        messages: dict[str, list[str]] | list[str] | str,
        traceback: str | None = None,
        **kwargs: Any,
    ) -> None:
        logger.debug(f"Exception:: {messages}")

        self.messages = messages
        self.traceback = traceback

        super().__init__(**kwargs)

    def __str__(self) -> str:
        if isinstance(self.messages, dict):
            return f"{dict(self.messages)}"
        return f"{self.messages}"

    def __reduce__(self) -> tuple[Any, tuple[Any, ...], dict[str, Any]]:
        # ``messages`` reconstructs the payload; state restores the diagnostic
        # attributes. Reconstruct as ``self.__class__`` so a coded
        # ``ValidationError`` round-trips as a ``ValidationError`` (an
        # ``except ValidationError`` past the broker still catches it), not as a
        # bare ``ProteanExceptionWithMessage``.
        return (self.__class__, (self.messages,), self._diagnostic_state())


class NoDomainException(ProteanException):
    """Raised if a domain cannot be found or loaded in a module"""


class ConfigurationError(ProteanException):
    """Improper Configuration encountered like:
    * An important configuration variable is missing
    * Re-registration of Database Models
    * Incorrect associations
    """


class ObjectNotFoundError(ProteanException):
    """Object was not found, can raise 404"""


class TooManyObjectsError(ProteanException):
    """Expected one object, but found many"""


class InsufficientDataError(ProteanException):
    """Object was not supplied with sufficient data"""


class InvalidDataError(ProteanExceptionWithMessage):
    """Data (type, value) is invalid"""


class InvalidStateError(ProteanException):
    """Object is in invalid state for the given operation

    Equivalent to 409 (Conflict)"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _emit_security_event("invalid_state", args)


class InvalidOperationError(ProteanException):
    """Operation being performed is not permitted"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _emit_security_event("invalid_operation", args)


class NotSupportedError(ProteanException):
    """Object does not support the operation being performed"""


class IncorrectUsageError(ProteanException):
    """Usage of a Domain Element violates principles"""


class ValidationError(ProteanExceptionWithMessage):
    """Raised when validation fails on a field. Validators and custom fields should
    raise this exception.

    :param errors: An error message or a list of error messages or a
        dictionary of error message where key is field name and value is error

    """


class DatabaseError(ProteanException):
    """Raised when database operations fail."""

    def __init__(
        self,
        message: str,
        original_exception: BaseException | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.original_exception = original_exception


class SendError(ProteanException):
    """Raised on email dispatch failure."""


class ExpectedVersionError(ProteanException):
    """Raised on expected version conflicts in EventSourcing"""


class TransactionError(ProteanException):
    """Raised when a transaction fails to commit or encounters an error during processing"""


class DuplicateCommandError(ProteanException):
    """Raised when a command with a duplicate idempotency key is submitted
    and raise_on_duplicate=True is specified.

    Carries the original result from the first successful processing.
    """

    def __init__(
        self, message: str, original_result: Any = None, **kwargs: Any
    ) -> None:
        super().__init__(message, **kwargs)
        self.original_result = original_result


class CommandExpiredError(ProteanException):
    """Raised when a command is processed after its deadline has passed.

    Prevents stale commands from executing after long queue delays. Carries
    the command type and the deadline that was exceeded for diagnostics.
    """

    def __init__(
        self,
        message: str,
        command_type: str | None = None,
        deadline: datetime | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.command_type = command_type
        self.deadline = deadline


class DeserializationError(ProteanException):
    """Exception raised when message deserialization fails.

    Provides enhanced error context including message details and the original error
    to help with debugging and troubleshooting message processing issues.
    """

    def __init__(
        self,
        message_id: str,
        error: str,
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize DeserializationError.

        Args:
            message_id: Unique identifier of the message that failed to deserialize
            error: Description of the error that occurred
            context: Additional context information about the message and error
        """
        self.message_id = message_id
        self.error = error
        self.context = context or {}
        super().__init__(
            f"Failed to deserialize message {message_id}: {error}", **kwargs
        )

    def __repr__(self) -> str:
        return f"DeserializationError(message_id='{self.message_id}', error='{self.error}', context={self.context})"
