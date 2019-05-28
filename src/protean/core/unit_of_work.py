class UnitOfWork:
    def __init__(self, domain):
        # Initializae session factories from all providers
        #   Connections will be retrieved at this stage

        # Also initialize Identity Map?
        #   Repository will first check here before retrieving from Database
        self.domain = domain
        self._in_progress = False

        self.sessions = {}
        for provider in self.domain.providers.providers_list():
            self.sessions[provider.name] = provider.get_session()

        self.objects_to_be_added = {}
        self.objects_to_be_updated = {}
        self.objects_to_be_removed = {}

    @property
    def in_progress(self):
        return self._in_progress

    def __enter__(self):
        # Initiate a new session as part of self
        self.start()
        return self

    def __exit__(self, *args):
        # Commit and destroy session
        pass

    def start(self):
        # Stand in method for `__enter__`
        #   To explicitly begin and end transactions
        self._in_progress = True

    def commit(self):
        # Commit and destroy session
        pass

    def rollback(self):
        # Destroy session and self without Committing
        pass

    def register_new(self, element):
        identity = getattr(element, element.meta_.id_field.field_name, None)
        assert identity is not None

        self.objects_to_be_added[identity] = element

    def register_update(self, element):
        identity = getattr(element, element.meta_.id_field.field_name, None)
        assert identity is not None

        self.objects_to_be_updated[identity] = element

    def register_delete(self, element):
        identity = getattr(element, element.meta_.id_field.field_name, None)
        assert identity is not None

        self.objects_to_be_removed[identity] = element
