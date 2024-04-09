import os
import sys

from pathlib import Path

import pytest

from protean.utils.domain_discovery import derive_domain
from tests.shared import change_working_directory_to


class TestDomainShellContext:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_return_type(self):
        change_working_directory_to("test9")

        domain = derive_domain("publishing9:domain")

        assert domain is not None
        domain.init()

        context = domain.make_shell_context()
        assert isinstance(context, dict), "The method should return a dictionary"

        assert "domain" in context, "The domain itself should be in the context"
        assert (
            context["domain"] is domain
        ), "The domain in context should be the domain object"

        # Test for elements in the context
        assert (
            "Post" in context
            and context["Post"] is domain.registry.aggregates["publishing9.Post"].cls
        ), "`Post` class should be in the context"
        assert (
            "Comment" in context
            and context["Comment"]
            is domain.registry.entities["publishing9.Comment"].cls
        ), "`Comment` class should be in the context"
