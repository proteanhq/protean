""""Module to test Domain object functionality"""

from protean import Domain


class TestDomain:

    def test_init(self):
        """Test that Domain object can be initialized successfully"""
        domain = Domain(__name__)
        assert domain is not None
