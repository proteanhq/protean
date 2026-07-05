"""Coverage for the Providers/Caches container ``__getitem__`` contract.

Both containers must raise ``KeyError`` (not return ``None``) for a missing or
uninitialised key, per the ``MutableMapping`` contract — the typing pass fixed
these to raise, so callers relying on ``.get()`` semantics stay correct.
"""

import pytest

from protean.adapters.cache import Caches
from protean.adapters.repository import Providers


def test_caches_getitem_raises_keyerror_when_uninitialized(test_domain):
    caches = Caches(test_domain)
    with pytest.raises(KeyError):
        caches["default"]


def test_providers_getitem_raises_keyerror_when_uninitialized(test_domain):
    providers = Providers(test_domain)
    with pytest.raises(KeyError):
        providers["default"]
