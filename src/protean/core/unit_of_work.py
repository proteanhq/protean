# Standard Library Imports
import logging

# Protean
from protean.core.exceptions import InvalidOperationError
from protean.globals import _uow_context_stack, current_domain

logger = logging.getLogger('protean.core.unit_of_work')


class UnitOfWork:
    def __init__(self):
        # Initialize session factories from all providers
        #   Connections will be retrieved at this stage

        # Also initialize Identity Map?
        #   Repository will first check here before retrieving from Database
        self.domain = current_domain
        self._in_progress = False

        self._sessions = {}
        self._events = []

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

    def start(self):
        # Stand in method for `__enter__`
        #   To explicitly begin and end transactions
        self._in_progress = True
        _uow_context_stack.push(self)

    def commit(self):
        # Raise error if there the Unit Of Work is not active
        logger.debug(f'Committing {self}...')
        if not self._in_progress:
            raise InvalidOperationError("UnitOfWork is not in progress")

        # Exit from Unit of Work
        _uow_context_stack.pop()

        # Commit and destroy session
        try:
            for _, session in self._sessions.items():
                session.commit()

            for event in self._events:
                for broker in self.domain.brokers_list:
                    broker.send_message(event)

            logger.debug('Commit Successful')
        except Exception as exc:
            logger.error(f'Error during Commit: {str(exc)}. Rolling back Transaction...')
            self.rollback()

        self._reset()

    def _reset(self):
        for _, session in self._sessions.items():
            session.close()

        self._sessions = {}
        self._events = []
        self._in_progress = False

    def rollback(self):
        # Raise error if there the Unit Of Work is not active
        if not self._in_progress:
            raise InvalidOperationError("UnitOfWork is not in progress")

        # Exit from Unit of Work
        _uow_context_stack.pop()

        try:
            for _, session in self._sessions.items():
                session.rollback()

            logger.debug('Transaction rolled back')
        except Exception as exc:
            logger.error(f'Error during Transaction rollback: {str(exc)}')

        self._reset()

    def _get_session(self, provider_name):
        provider = self.domain.get_provider(provider_name)
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

    def register_event(self, event):
        self._events.append(event)
