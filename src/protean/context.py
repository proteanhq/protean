"""Context Management Framework"""
from .utils import local


class Context:
    """Class to create and manage context for UseCase"""

    def __init__(self, **kwargs):
        """Initialize Context"""
        self.kwargs = kwargs

        self.local_context = local.Local()
        self.local_context_manager = local.LocalManager([self.local_context])

    def __getattr__(self, attr):
        """Retrieve attribute from one of the context managers"""
        return getattr(self.local_context, attr)

    def __enter__(self):
        """Initialize Local Objects"""
        self.set_context(self.kwargs)

    def __exit__(self, exception_type, exception_value, traceback):
        """Cleanup Local Objects"""
        self.cleanup()

    def set_context(self, data):
        """Load Context with data"""
        for key in data:
            setattr(self.local_context, key, data[key])

    def cleanup(self):
        """Load Context with data"""
        self.local_context_manager.cleanup()


context = Context()
