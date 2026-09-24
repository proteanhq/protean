"""Save and restore the process-wide logging state around a test.

``configure_logging`` and ``logging.config.dictConfig`` change process-wide
state: the root logger's level, handlers and filters, the level of named
loggers such as ``protean.server.engine``, the ``disabled`` flag that
``dictConfig`` sets on loggers it does not mention, ``logging.disable``, the
structlog configuration, and the structlog context variables that
``add_context`` binds. ``tests/conftest.py`` takes a snapshot before every test
and restores it afterwards, so one test's logging setup cannot change what a
later test's ``caplog`` sees.
"""

import logging
from dataclasses import dataclass
from typing import Any

import structlog

_LoggerState = tuple[int, list[logging.Handler], list[Any], bool, bool]


def _is_pytest_handler(handler: logging.Handler) -> bool:
    # pytest attaches its own capture handlers to the root logger around each
    # test phase and removes them itself, so they are never ours to restore.
    return type(handler).__module__ == "_pytest.logging"


def _logger_state(logger: logging.Logger) -> _LoggerState:
    return (
        logger.level,
        list(logger.handlers),
        list(logger.filters),
        logger.propagate,
        logger.disabled,
    )


def _new_logger_state(logger: logging.Logger) -> _LoggerState:
    """The state to give a logger that did not exist before the test.

    It gets the stdlib defaults, except that it keeps its ``NullHandler``. A
    library adds one to its logger when it is imported, and the first import
    can happen inside any test.
    """
    null_handlers = [h for h in logger.handlers if isinstance(h, logging.NullHandler)]
    return (logging.NOTSET, null_handlers, [], True, False)


def _restore_logger(logger: logging.Logger, state: _LoggerState) -> None:
    level, handlers, filters, propagate, disabled = state
    if logger.level != level:
        logger.setLevel(level)
    if logger.handlers != handlers:
        logger.handlers = handlers
    if logger.filters != filters:
        logger.filters = filters
    logger.propagate = propagate
    logger.disabled = disabled


def _structlog_config() -> dict[str, Any]:
    # ``get_config()`` hands back the live processor list, so an in-place
    # change to it would show up in the snapshot too. Copy the lists.
    return {
        key: list(value) if isinstance(value, list) else value
        for key, value in structlog.get_config().items()
    }


def _all_loggers() -> list[logging.Logger]:
    loggers = logging.Logger.manager.loggerDict.values()
    return [logging.getLogger(), *(x for x in loggers if isinstance(x, logging.Logger))]


def _attached_handlers() -> set[logging.Handler]:
    return {handler for logger in _all_loggers() for handler in logger.handlers}


@dataclass
class LoggingSnapshot:
    root: _LoggerState
    named: dict[str, _LoggerState]
    disable_level: int
    structlog_config: dict[str, Any]

    @classmethod
    def take(cls) -> "LoggingSnapshot":
        manager = logging.Logger.manager
        return cls(
            root=_logger_state(logging.getLogger()),
            named={
                name: _logger_state(logger)
                for name, logger in manager.loggerDict.items()
                if isinstance(logger, logging.Logger)
            },
            disable_level=manager.disable,
            structlog_config=_structlog_config(),
        )

    def restore(self) -> None:
        """Put the saved state back and close the handlers the test left behind.

        Loggers created since the snapshot get the stdlib defaults. The
        handlers pytest attaches for its own log capture are left alone.
        """
        manager = logging.Logger.manager
        if manager.disable != self.disable_level:
            logging.disable(self.disable_level)
        if _structlog_config() != self.structlog_config:
            structlog.configure(**self.structlog_config)
        structlog.contextvars.clear_contextvars()

        attached_before = _attached_handlers()

        root = logging.getLogger()
        level, handlers, filters, propagate, disabled = self.root
        pytest_handlers = [h for h in root.handlers if _is_pytest_handler(h)]
        own_handlers = [h for h in handlers if not _is_pytest_handler(h)]
        _restore_logger(
            root, (level, own_handlers + pytest_handlers, filters, propagate, disabled)
        )
        for name, logger in list(manager.loggerDict.items()):
            if isinstance(logger, logging.Logger):
                state = self.named.get(name) or _new_logger_state(logger)
                _restore_logger(logger, state)

        # A handler the test attached and nothing holds any more would stay
        # open until garbage collection, a log file included.
        for handler in attached_before - _attached_handlers():
            if not _is_pytest_handler(handler):
                handler.close()
