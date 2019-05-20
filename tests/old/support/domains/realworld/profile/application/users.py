"""Use Cases for the User Aggregate"""
from jwt.exceptions import DecodeError
from jwt.exceptions import ExpiredSignatureError
from passlib.hash import pbkdf2_sha256

from protean import Domain
from protean.conf import active_config
from protean.core.entity import BaseEntity
from protean.core.exceptions import ObjectNotFoundError
from protean.core.transport import ResponseFailure
from protean.core.transport import ResponseSuccess
from protean.core.transport import Status
from protean.core.transport import RequestObjectFactory
from protean.core.usecase.base import UseCase

from tests.old.support.domains.realworld.profile.domain.model.user import Email, User
from tests.old.support.domains.realworld.profile.exceptions import JWTDecodeError
from tests.old.support.domains.realworld.profile.jwt import encode_access_token, decode_jwt


LoginRequestObject = RequestObjectFactory.construct(
    'LoginRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('email', str, {'required': True}),
     ('password', str, {'required': True})])


class LoginUseCase(UseCase):
    """Authentication a user by email/password"""

    def process_request(self, request_object):
        """Process Login Request"""
        repo = Domain().get_repository(request_object.entity_cls)
        user = repo.query.filter(email_address=request_object.email).first

        if not user:
            return ResponseFailure.build_response(
                code=Status.UNAUTHORIZED,
                errors=[{'email': 'Login Failed'}])

        if pbkdf2_sha256.verify(request_object.password, user.password):
            # Build the identity to be encoded in the jwt
            identity = {
                'user_id': user.id
            }

            # Generate the jwt token and return in response
            token_data, access_token = encode_access_token(
                identity=identity,
                secret=active_config.SECRET_KEY,
                algorithm=active_config.JWT_ALGORITHM,
                expires_delta=active_config.JWT_ACCESS_TOKEN_EXPIRES,
                fresh=False,
                csrf=False,
                identity_claim_key='identity',
                user_claims=None,
                user_claims_key=None,
            )
            # Store the just-generated Access Token for future reference
            Domain().get_repository(User).update(user, token=access_token)

            return ResponseSuccess(Status.SUCCESS, user)

        return ResponseFailure.build_response(
            code=Status.UNAUTHORIZED,
            errors=[{'password': 'Login Failed'}])


UserFromTokenRequestObject = RequestObjectFactory.construct(
    'UserFromTokenRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('token', str, {'required': True})])


class AuthenticationUseCase(UseCase):
    """
    This class encapsulates the Use Case for Basic Authentication
    """

    def process_request(self, request_object):
        """Process Authentication Request"""
        # Get the decode key for the alg
        decode_key = active_config.SECRET_KEY

        # Decode and validate the jwt
        try:
            jwt_data = decode_jwt(
                encoded_token=request_object.token,
                secret=decode_key,
                algorithm=active_config.JWT_ALGORITHM,
                identity_claim_key=active_config.JWT_IDENTITY_CLAIM
            )
        except (JWTDecodeError, DecodeError, ExpiredSignatureError):
            return ResponseFailure(
                Status.UNAUTHORIZED, {'token': f'Invalid JWT Token'})

        # Find the identity in the decoded jwt
        identity = jwt_data.get(active_config.JWT_IDENTITY_CLAIM, None)
        try:
            repo = Domain().get_repository(request_object.entity_cls)
            user = repo.get(identity.get('user_id'))
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.UNAUTHORIZED,
                {'token': 'User does not exist'})

        return ResponseSuccess(Status.SUCCESS, user)


RegisterRequestObject = RequestObjectFactory.construct(
    'RegisterRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('address', str, {'required': True}),
     ('password', str, {'required': True}),
     ('username', str, {'required': True}),
     ('bio', str),
     ('image', str)])


class RegisterUseCase(UseCase):
    """Register a new user"""

    def process_request(self, request_object):
        """Process Registration Request"""
        repo = Domain().get_repository(request_object.entity_cls)
        user = repo.create(
            address=request_object.address,
            password=request_object.password,
            username=request_object.username,
            bio=request_object.bio,
            image=request_object.image)

        return ResponseSuccess(Status.SUCCESS_CREATED, user)


class CurrentUserUseCase(UseCase):
    """Fetch Current User from valid token"""

    def process_request(self, request_object):
        """Process Fetch Logged-in User Request"""
        try:
            repo = Domain().get_repository(request_object.entity_cls)
            user = repo.find_by(token=request_object.token)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'token': 'User does not exist'})

        return ResponseSuccess(Status.SUCCESS, user)


UpdateUserRequestObject = RequestObjectFactory.construct(
    'UpdateUserRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('token', str, {'required': True}),
     ('data', dict, {'required': True})])


class UpdateUserUseCase(UseCase):
    """Update details for an existing user"""

    def process_request(self, request_object):
        """Process User Update Request"""

        try:
            repo = Domain().get_repository(request_object.entity_cls)
            user = repo.find_by(token=request_object.token)
        except ObjectNotFoundError:
            return ResponseFailure(
                Status.NOT_FOUND,
                {'token': 'User does not exist'})

        # FIXME What is the key to be expected here?
        if 'address' in request_object.data:
            user.email = Email.build(address=request_object.data['address'])
        if 'username' in request_object.data:
            user.username = request_object.data['username']
        if 'password' in request_object.data:
            user.password = request_object.data['password']
        if 'bio' in request_object.data:
            user.bio = request_object.data['bio']
        if 'image' in request_object.data:
            user.image = request_object.data['image']
        Domain().get_repository(User).save(user)

        return ResponseSuccess(Status.SUCCESS, user)
