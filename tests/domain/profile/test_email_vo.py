"""Test Value Object functionality with Sample Domain Artifacts"""

# Protean
from tests.support.sample_domain.profile.domain.model.user import Email


class TestEmailVO:
    """Tests for User Aggregate"""

    def test_init_build_from_parts(self):
        """Test that Email VO can be initialized successfully"""
        email = Email.build_from_parts('john.doe', 'gmail.com')
        assert email is not None
        assert email.local_part == 'john.doe'
        assert email.domain_part == 'gmail.com'

    def test_init_build(self):
        """Test that Email VO can be initialized successfully"""
        email = Email.build(address='john.doe@gmail.com')
        assert email is not None
        assert email.local_part == 'john.doe'
        assert email.domain_part == 'gmail.com'

    def test_equivalence(self):
        """Test that two Email VOs are equal if their values are equal"""
        email1 = Email.build(address='john.doe@gmail.com')
        email2 = Email.build(address='john.doe@gmail.com')

        assert email1 == email2

        email3 = Email.build(address='john.doe@gmail.com')
        email4 = Email.build(address='jane.doe@gmail.com')

        assert email3 != email4
