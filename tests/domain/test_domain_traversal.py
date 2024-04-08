import pytest


class TestDomainTraversal:
    @pytest.mark.no_test_domain
    def test_loading_domain_without_init(self):
        from tests.support.test_domains.test6 import publishing6

        assert publishing6.domain is not None
        assert len(publishing6.domain.registry.aggregates) == 0

    @pytest.mark.no_test_domain
    def test_loading_domain_with_init(self):
        from tests.support.test_domains.test7 import publishing7

        assert publishing7.domain is not None
        publishing7.domain.init()
        assert len(publishing7.domain.registry.aggregates) == 1
