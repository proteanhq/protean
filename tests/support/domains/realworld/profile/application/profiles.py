"""Use Cases for the Profile functionality"""

from protean.core.entity import BaseEntity
from protean.core.exceptions import ObjectNotFoundError
from protean.core.transport import ResponseFailure
from protean.core.transport import ResponseSuccess
from protean.core.transport import Status
from protean.core.transport import RequestObjectFactory
from protean.core.usecase import UseCase


GetProfileRequestObject = RequestObjectFactory.construct(
    'GetProfileRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('username', str, {'required': True})])


class GetProfileUseCase(UseCase):
    """Fetch Profile by Username"""

    def process_request(self, request_object):
        """Process Fetch Logged-in User Request"""
        try:
            user = request_object.entity_cls.find_by(username=request_object.username)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'username': 'Profile not found'})

        return ResponseSuccess(Status.SUCCESS, user)


FollowProfileRequestObject = RequestObjectFactory.construct(
    'FollowProfileRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('username', str, {'required': True}),
     ('token', str, {'required': True})])


class FollowProfileUseCase(UseCase):
    """Follow Profile by Username"""

    def process_request(self, request_object):
        """Process request for following profile by username"""
        try:
            logged_in_user = request_object.entity_cls.find_by(token=request_object.token)
            profile = request_object.entity_cls.find_by(username=request_object.username)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'token': 'Token is invalid'})

        logged_in_user.follow(profile)
        return ResponseSuccess(Status.SUCCESS, profile)


class UnfollowProfileUseCase(UseCase):
    """Unfollow Profile by Username"""

    def process_request(self, request_object):
        """Process request for following profile by username"""
        try:
            logged_in_user = request_object.entity_cls.find_by(token=request_object.token)
            profile = request_object.entity_cls.find_by(username=request_object.username)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'token': 'Token is invalid'})

        logged_in_user.unfollow(profile)
        return ResponseSuccess(Status.SUCCESS, profile)
