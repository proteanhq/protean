"""Test Aggregates functionality with Sample Domain Artifacts"""

import pytest

from passlib.hash import pbkdf2_sha256
from uuid import UUID

from tests.support.sample_domain.profile.domain.model.user import User


class TestUserAggregate:
    """Tests for User Aggregate"""

    def test_init(self):
        """Test that User Aggregate can be initialized successfully"""
        user = User.build(email='john.doe@gmail.com', username='johndoe', password='a1b2c3d4e5')
        assert user is not None

    def test_identity(self):
        """Test that a User Aggregate object has a unique identity"""
        user = User.build(email='john.doe@gmail.com', username='johndoe', password='a1b2c3d4e5')
        assert user.id is not None

        try:
            uuid_obj = UUID(str(user.id))
        except ValueError:
            pytest.fail("ID is not valid UUID")

        assert str(uuid_obj) == user.id

    def test_equivalence(self):
        """Test that two User objects with the same ID are treated as equal"""
        user1 = User.build(email='john.doe@gmail.com', username='johndoe', password='a1b2c3d4e5')
        user2 = user1.clone()

        user2.username = "janedoe"
        assert user1 == user2

    def test_persistence(self):
        """Test that the User Aggregate can be persisted successfully"""
        user = User.create(email='john.doe@gmail.com', username='johndoe', password='a1b2c3d4e5')
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
        user = User.create(email='john.doe@gmail.com', username='johndoe', password='a1b2c3d4e5')
        db_user = User.get(user.id)

        assert db_user is not None
        try:
            UUID(user.id)
        except ValueError:
            pytest.fail("ID is not valid UUID")

    def test_password_hash(self):
        """Test that passwords are hashed as part of entity initialization"""
        user = User.create(email='john.doe@gmail.com', username='johndoe', password='a1b2c3d4e5')
        assert pbkdf2_sha256.verify('a1b2c3d4e5', user.password)
