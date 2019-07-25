# Standard Library Imports
from functools import partial

# Protean
from werkzeug.local import LocalProxy, LocalStack

_domain_ctx_err_msg = """\
Working outside of domain context.
This typically means that you attempted to use functionality that needed
to interface with the current domain object in some way. To solve
this, set up an domain context with domain.domain_context().  See the
documentation for more information.\
"""


def _lookup_domain_object(name):
    top = _domain_context_stack.top
    if top is None:
        raise RuntimeError(_domain_ctx_err_msg)
    return getattr(top, name)


def _find_domain():
    top = _domain_context_stack.top
    if top is None:
        raise RuntimeError(_domain_ctx_err_msg)
    return top.domain


# context locals
_domain_context_stack = LocalStack()
current_domain = LocalProxy(_find_domain)
g = LocalProxy(partial(_lookup_domain_object, "g"))
