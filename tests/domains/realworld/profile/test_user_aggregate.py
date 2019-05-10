"""Test Aggregates functionality with Sample Domain Artifacts"""

# Standard Library Imports
from collections import OrderedDict
from uuid import UUID

# Protean
import pytest

from passlib.hash import pbkdf2_sha256
from protean.core.field import ValueObject
from tests.support.domains.realworld.profile.domain.model.user import Email, User


class TestUserAggregate:
    """Tests for User Aggregate"""

    def test_user_fields(self):
        """Test User Aggregate structure"""
        declared_fields_keys = list(OrderedDict(sorted(User.meta_.declared_fields.items())).keys())
        assert declared_fields_keys == ['email', 'id', 'password', 'token', 'username']

        attribute_keys = list(OrderedDict(sorted(User.meta_.attributes.items())).keys())
        assert attribute_keys == ['email_address', 'id', 'password', 'token', 'username']

        assert isinstance(User.meta_.declared_fields['email'], ValueObject)

    def test_init(self):
        """Test that User Aggregate can be initialized successfully"""
        user = User.build(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='a1b2c3d4e5')
        assert user is not None
        assert user.email == Email.build(address='john.doe@gmail.com')
        assert user.password != 'a1b2c3d4e5'

    def test_init_with_email_vo(self):
        """Test that User Aggregate can be initialized successfully"""
        email = Email.build(address='john.doe@gmail.com')
        user = User.build(email=email, username='johndoe', password='a1b2c3d4e5')
        assert user is not None
        assert user.email == email
        assert user.email_address == 'john.doe@gmail.com'

        user.email = None
        assert user.email is None
        assert user.email_address is None

        user.email = Email.build(address='john.doe@gmail.com')
        assert user.email == email
        assert user.email_address == 'john.doe@gmail.com'

        user.email = None
        user.email_address = 'john.doe@gmail.com'  # We don't accept partial updates
        assert user.email_address is None
        assert user.email is None

    def test_vo_values(self):
        """Test that values of VOs are set and retrieved properly"""
        email = Email.build(address='john.doe@gmail.com')
        user = User.build(email=email, username='johndoe', password='a1b2c3d4e5')
        assert user.email == email
        assert isinstance(user.email, Email)
        assert user.email.address == "john.doe@gmail.com"
        user_dict = user.to_dict()
        assert all(attr in user_dict for attr in ['email_address', 'id', 'password', 'token', 'username'])

    def test_identity(self):
        """Test that a User Aggregate object has a unique identity"""
        user = User.build(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='a1b2c3d4e5')
        assert user.id is not None

        try:
            uuid_obj = UUID(str(user.id))
        except ValueError:
            pytest.fail("ID is not valid UUID")

        assert str(uuid_obj) == user.id

    def test_equivalence(self):
        """Test that two User objects with the same ID are treated as equal"""
        user1 = User.build(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='a1b2c3d4e5')
        user2 = user1.clone()

        user2.username = "janedoe"
        assert user1 == user2

    def test_persistence(self):
        """Test that the User Aggregate can be persisted successfully"""
        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='a1b2c3d4e5')
        assert user is not None
        assert user.id is not None

        try:
            UUID(user.id)
        except ValueError:
            pytest.fail("ID is not valid UUID")

    def test_retrieval(self):
        """Test that the User Aggregate can be retrieved successfully
        and it retains its state
        """
        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='a1b2c3d4e5')
        db_user = User.get(user.id)

        assert db_user is not None
        assert db_user.email is not None
        assert db_user.email == Email.build(address='john.doe@gmail.com')
        assert db_user.email_address == 'john.doe@gmail.com'
        try:
            UUID(user.id)
        except ValueError:
            pytest.fail("ID is not valid UUID")

    def test_password_hash(self):
        """Test that passwords are hashed as part of entity initialization"""
        user = User.create(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='a1b2c3d4e5')
        assert pbkdf2_sha256.verify('a1b2c3d4e5', user.password)
