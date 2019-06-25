class BaseApplicationService:
    """Base ApplicationService class that all other Application services should inherit from.

    This class is a placeholder class for now. Application concepts directly influence the
    method names in concrete Application Service classes, so no abstract methods are necessary.
    Each Application Service class is usually associated one-to-one with API calls.

    Application services are responsible for fetching the linked domain, initializing repositories,
    caches, and message brokers, and injecting dependencies into the domain layer. These are automatable
    aspects that can be part of the base class in the future.
    """

    def __new__(cls, *args, **kwargs):
        if cls is BaseApplicationService:
            raise TypeError("BaseApplicationService cannot be instantiated")
        return object.__new__(cls, *args, **kwargs)
