import sys

from pathlib import Path

import pytest


class TestDomainTraversal:
    @pytest.fixture(autouse=True)
    def reset_path(self, request):
        original_path = sys.path[:]

        yield

        sys.path[:] = original_path

    def test_loading_domain_without_init(self):
        test_path = (
            Path(__file__) / ".." / ".." / "support" / "test_domains" / "test6"
        ).resolve()

        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "publishing", str(test_path) + "/publishing.py"
        )
        publishing = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publishing)

        assert publishing.domain is not None
        assert len(publishing.domain.registry.aggregates) == 0

    @pytest.mark.no_test_domain
    def test_loading_domain_with_init(self):
        from tests.support.test_domains.test7 import publishing

        assert publishing.domain is not None
        publishing.domain.init()
        assert len(publishing.domain.registry.aggregates) == 1
