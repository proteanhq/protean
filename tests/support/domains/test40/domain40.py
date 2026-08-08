"""Test domain module that raises on import.

Raising a plain ``RuntimeError`` at module scope reaches ``__import__`` as
that ``RuntimeError``, not the ``ImportError`` that ``locate_domain`` wraps in
``NoDomainException``. Used to exercise the fallback path in ``verify`` that
catches any other exception from domain discovery and maps it to the
init-failure exit code (2) instead of letting it crash out as an unhandled
traceback.
"""

raise RuntimeError("domain40 intentionally fails to import")
