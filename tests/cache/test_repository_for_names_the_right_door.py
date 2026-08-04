"""`repository_for()` on a cache-backed projection should say what to use instead.

It used to fail with `No provider configured with name 'None'`, which names the
wrong problem: the projection is not misconfigured, the caller is at the wrong
door. Reported from the ShopStream reference app as a first-user friction point,
where the working API had to be found by reading source (#1286).
"""

from __future__ import annotations

import pytest

from protean import Domain
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def domain():
    domain = Domain(name="CacheDoor")
    domain.config["caches"] = {"default": {"provider": "memory"}}

    @domain.projection(cache="default")
    class Token:
        key = Identifier(identifier=True)
        email = String()

    @domain.projection
    class Plain:
        key = Identifier(identifier=True)

    domain.init(traverse=False)
    domain.Token, domain.Plain = Token, Plain
    return domain


class TestTheErrorNamesTheWorkingApi:
    def test_it_says_the_projection_is_cache_backed(self, domain):
        with pytest.raises(IncorrectUsageError) as exc:
            with domain.domain_context():
                domain.repository_for(domain.Token)

        assert "cache-backed" in str(exc.value)

    @pytest.mark.parametrize("api", ["cache_for", "view_for"])
    def test_it_names_both_doors(self, domain, api):
        """Writing goes through `cache_for`, reading through `view_for`."""
        with pytest.raises(IncorrectUsageError) as exc:
            with domain.domain_context():
                domain.repository_for(domain.Token)

        assert f"domain.{api}(Token)" in str(exc.value)

    def test_it_no_longer_talks_about_providers(self, domain):
        """The old message sent readers hunting through provider config."""
        with pytest.raises(IncorrectUsageError) as exc:
            with domain.domain_context():
                domain.repository_for(domain.Token)

        assert "No provider configured" not in str(exc.value)

    def test_the_api_it_recommends_actually_works(self, domain):
        """An error naming an API that does not work would be worse than none."""
        with domain.domain_context():
            assert domain.cache_for(domain.Token) is not None
            assert domain.view_for(domain.Token) is not None


class TestProviderBackedProjectionsAreUnaffected:
    def test_a_plain_projection_still_gets_a_repository(self, domain):
        with domain.domain_context():
            assert domain.repository_for(domain.Plain) is not None
