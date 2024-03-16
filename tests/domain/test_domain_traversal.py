import pytest


class TestDomainTraversal:
    @pytest.mark.no_test_domain
    def test_loading_domain_without_init(self):
        from tests.support.test_domains.test6 import publishing

        assert publishing.domain is not None
        assert len(publishing.domain.registry.aggregates) == 0

    @pytest.mark.no_test_domain
    def test_loading_domain_with_init(self):
        from tests.support.test_domains.test7 import publishing

        assert publishing.domain is not None
        publishing.domain.init()
        assert len(publishing.domain.registry.aggregates) == 1
