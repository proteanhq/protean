"""``is_external_io_call`` / ``is_persistence_call``: the shared detection seam.

Both the `IO_INSIDE_UNIT_OF_WORK` upgrade check and the
`HANDLER_PERSISTS_AND_CALLS_OUT` diagnostic ask "does this resolved callee reach
outside the process / reach a repository". Getting the verb gate and the
degenerate inputs right here is what keeps both from either firing on pure
string work or going blind to the common shape.
"""

import pytest

from protean.ir.constants import is_external_io_call, is_persistence_call


class TestIsExternalIoCall:
    @pytest.mark.parametrize(
        "callee",
        [
            "httpx.post",
            "requests.get",
            "aiohttp.request",
            "urllib.request.urlopen",  # unambiguous name, any root
            "some.broker.publish",  # unambiguous name
            "mailer.send_email",
        ],
    )
    def test_a_real_io_call_counts(self, callee):
        assert is_external_io_call(callee) is True

    @pytest.mark.parametrize(
        "callee",
        [
            "urllib.parse.urlencode",  # rooted in an I/O module, pure string work
            "requests.Session",  # a constructor, not a request
            "httpx.Client",  # ditto
            "mymodule.get",  # verb, but not rooted in an I/O module
            "some.local.helper",  # neither
        ],
    )
    def test_a_non_io_call_does_not(self, callee):
        assert is_external_io_call(callee) is False

    @pytest.mark.parametrize("callee", [None, "", "bareword"])
    def test_a_degenerate_callee_is_false_not_an_error(self, callee):
        assert is_external_io_call(callee) is False


class TestIsPersistenceCall:
    @pytest.mark.parametrize(
        "callee",
        [
            "protean.current_domain.repository_for",
            # The dominant import spelling resolves to a different root, so the
            # match is on the trailing accessor name, not the full path.
            "protean.utils.globals.current_domain.repository_for",
            "domain.repository_for",
        ],
    )
    def test_a_repository_access_counts(self, callee):
        assert is_persistence_call(callee) is True

    @pytest.mark.parametrize(
        "callee", [None, "", "repository_for_now", "some.other_for", "repo.get"]
    )
    def test_anything_else_does_not(self, callee):
        assert is_persistence_call(callee) is False
