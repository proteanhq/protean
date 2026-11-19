import pytest

from protean.domain import Domain
from protean.exceptions import ConfigurationError
from protean.testing import _event_store_of


def test_before_init_it_raises():
    domain = Domain(name="Uninit")

    with pytest.raises(ConfigurationError) as exc:
        _event_store_of(domain)

    assert exc.value.code == "CONFIG_EVENT_STORE_NOT_INITIALIZED"


def test_after_init_it_returns_the_service(test_domain):
    test_domain.init(traverse=False)

    assert _event_store_of(test_domain) is test_domain.event_store
