import logging
from typing import Any

from protean.exceptions import (
    ConfigurationError,
    ExpectedVersionError,
    InvalidOperationError,
    ValidationError,
)
from protean.utils import Processing
from protean.utils.globals import _uow_context_stack, current_domain
from protean.utils.reflection import id_field

logger = logging.getLogger(__name__)


class UnitOfWork:
    def __init__(self):
        """Initialize session factories from all providers

        Connections will be retrieved at this stage

        Also initialize Identity Map?
        Repository will first check here before retrieving from Database
        """
        # FIXME Should UnitOfWork keep an Identity map, of all `seen` objects?
        self.domain = current_domain
        self._in_progress = False

        self._sessions = {}
        self._messages_to_dispatch = []
        self._identity_map = {}

    @property
    def in_progress(self):
        return self._in_progress

    def __enter__(self):
        # Initiate a new session as part of self
        self.start()
        return self

    def __exit__(self, *args):
        # Commit and destroy session
        self.commit()

    def _add_to_identity_map(self, aggregate) -> None:
        identifier = getattr(aggregate, id_field(aggregate).field_name)
        self._identity_map[identifier] = aggregate

    def start(self):
        # Stand in method for `__enter__`
        #   To explicitly begin and end transactions
        self._in_progress = True
        _uow_context_stack.push(self)

    def commit(self):  # noqa: C901
        # Raise error if there the Unit Of Work is not active
        logger.debug(f"Committing {self}...")
        if not self._in_progress:
            raise InvalidOperationError("UnitOfWork is not in progress")

        # Exit from Unit of Work
        _uow_context_stack.pop()

        # Commit and destroy session
        try:
            for _, session in self._sessions.items():
                session.commit()

            # Push messages to all brokers
            # FIXME Send message to its designated broker?
            # FIXME Send messages through domain.brokers.publish?
            for channel, message in self._messages_to_dispatch:
                for _, broker in self.domain.brokers.items():
                    broker.publish(channel, message)
            self._messages_to_dispatch = []  # Empty after dispatch

            events = []
            for _, item in self._identity_map.items():
                if item._events:
                    for event in item._events:
                        current_domain.event_store.store.append(event)
                        events.append((item, event))
                item._events = []

            # Iteratively consume all events produced in this session
            if current_domain.config["event_processing"] == Processing.SYNC.value:
                # Handover events to process instantly
                for _, event in events:
                    handler_classes = current_domain.handlers_for(event)
                    for handler_cls in handler_classes:
                        handler_cls._handle(event)

            logger.debug("Commit Successful")
        except ValueError as exc:
            logger.error(str(exc))
            self.rollback()

            # Extact message based on message store platform in use
            if str(exc).startswith("P0001-ERROR"):
                msg = str(exc).split("P0001-ERROR:  ")[1]
            else:
                msg = str(exc)
            raise ExpectedVersionError(msg) from None
        except ConfigurationError as exc:
            # Configuration errors can be raised if events are misconfigured
            #   We just re-raise it for the client to handle.
            raise exc
        except Exception as exc:
            logger.error(
                f"Error during Commit: {str(exc)}. Rolling back Transaction..."
            )
            self.rollback()
            raise ValidationError(
                {"_entity": [f"Error during Data Commit: - {repr(exc)}"]}
            )

        self._reset()

    def _reset(self):
        for _, session in self._sessions.items():
            session.close()

        self._sessions = {}
        self._messages_to_dispatch = []
        self._identity_map = set()
        self._in_progress = False

    def rollback(self):
        # Raise error if the Unit Of Work is not active
        if not self._in_progress:
            raise InvalidOperationError("UnitOfWork is not in progress")

        # Exit from Unit of Work
        _uow_context_stack.pop()

        try:
            for _, session in self._sessions.items():
                session.rollback()

            logger.debug("Transaction rolled back")
        except Exception as exc:
            logger.error(f"Error during Transaction rollback: {str(exc)}")

        self._reset()

    def _get_session(self, provider_name):
        provider = self.domain.providers[provider_name]
        return provider.get_session()

    def _initialize_session(self, provider_name):
        new_session = self._get_session(provider_name)
        self._sessions[provider_name] = new_session
        if not new_session.is_active:
            new_session.begin()
        return new_session

    def get_session(self, provider_name):
        if provider_name in self._sessions:
            return self._sessions[provider_name]
        else:
            return self._initialize_session(provider_name)

    def register_message(self, channel: str, message: dict[str, Any]):
        self._messages_to_dispatch.append((channel, message))
