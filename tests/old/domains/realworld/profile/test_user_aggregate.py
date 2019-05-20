"""Test Aggregates functionality with Sample Domain Artifacts"""
import datetime

# Standard Library Imports
from collections import OrderedDict
from uuid import UUID

# Protean
import pytest

from passlib.hash import pbkdf2_sha256
from protean.core.exceptions import IncorrectUsageError
from protean.core.field.embedded import ValueObjectField
from tests.old.support.domains.realworld.profile.domain.model.user import Email, User, Follower, Favorite
from tests.old.support.domains.realworld.article.domain.model.article import Article


class TestUserAggregate:
    """Tests for User Aggregate"""

    def test_user_fields(self):
        """Test User Aggregate structure"""
        declared_fields_keys = list(OrderedDict(sorted(User.meta_.declared_fields.items())).keys())
        assert declared_fields_keys == ['bio', 'email', 'id', 'image', 'password', 'token', 'username']

        attribute_keys = list(OrderedDict(sorted(User.meta_.attributes.items())).keys())
        assert attribute_keys == ['bio', 'email_address', 'id', 'image', 'password', 'token', 'username']

        assert isinstance(User.meta_.declared_fields['email'], ValueObjectField)

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

    def test_persistence(self, test_domain):
        """Test that the User Aggregate can be persisted successfully"""
        user = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='a1b2c3d4e5')
        assert user is not None
        assert user.id is not None

        try:
            UUID(user.id)
        except ValueError:
            pytest.fail("ID is not valid UUID")

    def test_retrieval(self, test_domain):
        """Test that the User Aggregate can be retrieved successfully
        and it retains its state
        """
        user = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='a1b2c3d4e5')
        db_user = test_domain.get_repository(User).get(user.id)

        assert db_user is not None
        assert db_user.email is not None
        assert db_user.email == Email.build(address='john.doe@gmail.com')
        assert db_user.email_address == 'john.doe@gmail.com'
        try:
            UUID(user.id)
        except ValueError:
            pytest.fail("ID is not valid UUID")

    def test_password_hash(self, test_domain):
        """Test that passwords are hashed as part of entity initialization"""
        user = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='a1b2c3d4e5')
        assert pbkdf2_sha256.verify('a1b2c3d4e5', user.password)


class TestFollower:
    """Tests for Follower Entity"""

    @pytest.mark.skip(reason="DDD Implementation Pending")
    def test_direct_init(self):
        """Test that a Follower Entity cannot be instantiated on its own"""
        user1 = User(email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        user2 = User(email='jane.doe@gmail.com', username='janedoe', password='secret')

        with pytest.raises(IncorrectUsageError):
            Follower.create(user_id=user1.id, follower_id=user2.id, followed_on=datetime.utcnow())

    def test_follow(self, test_domain):
        """Test initialization of Follower Entity under User Aggregate"""

        user1 = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        user2 = test_domain.get_repository(User).create(
            email=Email.build(address='jane.doe@gmail.com'), username='janedoe', password='secret')

        user1.follow(user2)

        assert user2.id in [follower.user.id for follower in user1.follows]
        assert user1.id in [follower.follower.id for follower in user2.followed_by]


class TestFavorite:
    """Tests for Favorite Entity"""

    def test_init(self, test_domain):
        """Test initialization of Favorite Entity"""
        user = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret')
        article = test_domain.get_repository(Article).create(
            slug='how-to-train-your-dragon',
            title='How to train your dragon', description='Ever wonder how?',
            body='It takes a Jacobian', author=user)

        # FIXME This is a much more elegant method of handling entities under aggregates
        # favorite = user.favorites.add(article=article)
        favorite = test_domain.get_repository(Favorite).create(user=user, article=article)
        assert favorite is not None
        assert favorite.id is not None
        assert favorite.article == article
        assert favorite.user == user

        required_fields = [field_name for field_name in Favorite.meta_.declared_fields
                           if Favorite.meta_.declared_fields[field_name].required]
        assert len(required_fields) == 3
        assert all(field in required_fields for field in ['article', 'user', 'favorited_at'])
