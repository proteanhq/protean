"""Test domain module whose own top-level import fails.

Raising ``ImportError`` at module scope (via an ``import`` of a module that
does not exist) reaches ``__import__`` as an ``ImportError`` triggered
*inside* the domain module — not "module not found". ``locate_domain`` wraps
this case in ``NoDomainException`` with a "While importing ..." message, the
same exception class it uses for "module not found". Used to exercise the
``verify`` branch that tells the two apart: this one is a load failure (exit
2), not the domain-not-found usage error (exit 1).
"""

import this_module_does_not_exist_anywhere  # noqa: F401
