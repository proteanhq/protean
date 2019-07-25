# Standard Library Imports
import logging

# Protean
from protean.core.exceptions import InvalidOperationError

logger = logging.getLogger('protean.core.unit_of_work')


class UnitOfWork:
    def __init__(self, domain):
        # Initializae session factories from all providers
        #   Connections will be retrieved at this stage

        # Also initialize Identity Map?
        #   Repository will first check here before retrieving from Database
        self.domain = domain
        self._in_progress = False

        self._sessions = {}
        self._changes = {}
        for provider in self.domain.providers_list():
            self._sessions[provider.name] = provider.get_session()

            self._changes[provider.name] = {
                'ADDED': {},
                'UPDATED': {},
                'REMOVED': {}
            }

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

    def commit(self):
        # Raise error if there the Unit Of Work is not active
        if not self._sessions or not self._in_progress:
            raise InvalidOperationError("UnitOfWork is not in progress")

        # Commit and destroy session
        try:
            for provider_name in self._sessions:
                provider = self.domain.get_provider(provider_name)
                provider.commit(self._changes[provider_name])

            self._sessions = {}
            self._in_progress = False
        except Exception as exc:
            logger.error(f'Error during Commit: {str(exc)}. Rolling back Transaction...')
            self.rollback()

    def rollback(self):
        # Raise error if there the Unit Of Work is not active
        if not self._sessions or not self._in_progress:
            raise InvalidOperationError("UnitOfWork is not in progress")

        # Destroy session and self without Committing
        logger.error('Transaction Rolled Back.')
        self._sessions = {}
        self._in_progress = False

    def register_new(self, element):
        identity = getattr(element, element.meta_.id_field.field_name, None)
        assert identity is not None

        self._changes[element.meta_.provider]['ADDED'][identity] = element

    def register_update(self, element):
        identity = getattr(element, element.meta_.id_field.field_name, None)
        assert identity is not None

        self._changes[element.meta_.provider]['UPDATED'][identity] = element

    def register_delete(self, element):
        identity = getattr(element, element.meta_.id_field.field_name, None)
        assert identity is not None

        self._changes[element.meta_.provider]['REMOVED'][identity] = element

    @property
    def changes_to_be_committed(self):
        return self._changes
