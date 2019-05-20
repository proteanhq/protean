"""Test Profile UseCases"""
from protean.core.tasklet import Tasklet

from tests.old.support.domains.realworld.profile.domain.model.user import User, Email
from tests.old.support.domains.realworld.profile.application.profiles import GetProfileRequestObject
from tests.old.support.domains.realworld.profile.application.profiles import GetProfileUseCase
from tests.old.support.domains.realworld.profile.application.profiles import FollowProfileRequestObject
from tests.old.support.domains.realworld.profile.application.profiles import FollowProfileUseCase
from tests.old.support.domains.realworld.profile.application.profiles import UnfollowProfileUseCase


class TestGetProfile:
    """Test Get Profile Usecase"""
    # FIXME Implementation different test cases for Auth and Non-Auth

    def test_success(self, test_domain):
        """Test Successful profile fetch"""

        test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret1')
        user2 = test_domain.get_repository(User).create(
            email=Email.build(address='jane.doe@gmail.com'), username='janedoe', password='secret2')

        payload = {'username': 'janedoe'}
        response = Tasklet.perform(User, GetProfileUseCase, GetProfileRequestObject,
                                   payload=payload)

        assert response.is_successful
        assert isinstance(response.value, User)
        assert response.value.id == user2.id

    def test_failure(self, test_domain):
        """Test failed profile fetch"""

        test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret1')
        test_domain.get_repository(User).create(
            email=Email.build(address='jane.doe@gmail.com'), username='janedoe', password='secret2')

        payload = {'username': 'janedoe1'}
        response = Tasklet.perform(
            User, GetProfileUseCase, GetProfileRequestObject,
            payload=payload)

        assert not response.is_successful
        assert response.code.value == 404


class TestFollowProfile:
    """Test Follow Profile Usecase"""
    # FIXME Test that user cannot follow hisself

    def test_success(self, test_domain):
        """Test Successful profile follow"""

        user1 = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret1')
        user2 = test_domain.get_repository(User).create(
            email=Email.build(address='jane.doe@gmail.com'), username='janedoe', password='secret2')

        payload = {'token': user1.token, 'username': user2.username}
        response = Tasklet.perform(User, FollowProfileUseCase, FollowProfileRequestObject,
                                   payload=payload)

        assert response.is_successful
        assert response.value.id == user2.id
        user_follows = [follow.user_id for follow in user1.follows]
        assert user2.id in user_follows

    def test_failure(self, test_domain):
        """Test Failure in profile follow"""

        user1 = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret1')
        test_domain.get_repository(User).create(
            email=Email.build(address='jane.doe@gmail.com'), username='janedoe', password='secret2')

        payload = {'username': 'janedoe1'}
        response = Tasklet.perform(User, FollowProfileUseCase, FollowProfileRequestObject,
                                   payload=payload)

        assert not response.is_successful
        assert response.code.value == 422
        assert user1.follows is None


class TestUnfollowProfile:
    """Test Unfollow Profile Usecase"""
    # FIXME Test that user cannot unfollow hisself

    def test_success(self, test_domain):
        """Test Successful profile unfollow"""

        user1 = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret1')
        user2 = test_domain.get_repository(User).create(
            email=Email.build(address='jane.doe@gmail.com'), username='janedoe', password='secret2')

        payload = {'token': user1.token, 'username': user2.username}
        response = Tasklet.perform(User, FollowProfileUseCase, FollowProfileRequestObject,
                                   payload=payload)

        assert response.is_successful
        assert response.value.id == user2.id
        user_follows = [follow.user_id for follow in user1.follows]
        assert user2.id in user_follows

        response = Tasklet.perform(User, UnfollowProfileUseCase, FollowProfileRequestObject,
                                   payload=payload)
        refreshed_user1 = test_domain.get_repository(User).get(user1.id)
        assert refreshed_user1.follows is None

    def test_failure(self, test_domain):
        """Test Failure in profile follow"""

        user1 = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'), username='johndoe', password='secret1')
        user2 = test_domain.get_repository(User).create(
            email=Email.build(address='jane.doe@gmail.com'), username='janedoe', password='secret2')

        payload = {'token': user1.token, 'username': user2.username}
        response = Tasklet.perform(User, FollowProfileUseCase, FollowProfileRequestObject,
                                   payload=payload)

        payload = {'username': 'janedoe1'}
        response = Tasklet.perform(User, UnfollowProfileUseCase, FollowProfileRequestObject,
                                   payload=payload)

        assert not response.is_successful
        assert response.code.value == 422

        refreshed_user1 = test_domain.get_repository(User).get(user1.id)
        assert refreshed_user1.follows is not None
