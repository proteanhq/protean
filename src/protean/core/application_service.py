class BaseApplicationService:
    """Base ApplicationService class that all other Application services should inherit from.
    This is a placeholder class for now. Methods that are implemented
    in concreate Application Service classes are inspired from Application concepts,
    and typically use more than one aggregate to accomplish a task"""

    def __new__(cls, *args, **kwargs):
        if cls is BaseApplicationService:
            raise TypeError("BaseApplicationService cannot be instantiated")
        return object.__new__(cls, *args, **kwargs)
