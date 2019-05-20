"""Test User Aggregate UseCases"""
import datetime
import pytest

from protean.conf import active_config
from protean.core.tasklet import Tasklet

from tests.old.support.domains.realworld.profile.domain.model.user import User, Email
from tests.old.support.domains.realworld.profile.application.users import AuthenticationUseCase
from tests.old.support.domains.realworld.profile.application.users import CurrentUserUseCase
from tests.old.support.domains.realworld.profile.application.users import LoginRequestObject
from tests.old.support.domains.realworld.profile.application.users import LoginUseCase
from tests.old.support.domains.realworld.profile.application.users import RegisterRequestObject
from tests.old.support.domains.realworld.profile.application.users import RegisterUseCase
from tests.old.support.domains.realworld.profile.application.users import UpdateUserRequestObject
from tests.old.support.domains.realworld.profile.application.users import UpdateUserUseCase
from tests.old.support.domains.realworld.profile.application.users import UserFromTokenRequestObject

from tests.old.support.domains.realworld.profile.jwt import encode_access_token


class TestLogin:
    """Test Login Functionality"""

    def test_success(self, test_domain):
        """Test Successful Login"""
        user = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'),
            username='johndoe', password='secret',
            bio='I work at Webmart', image='https://234ssll.xfg')

        payload = {'email': 'john.doe@gmail.com', 'password': 'secret'}
        response = Tasklet.perform(User, LoginUseCase, LoginRequestObject, payload=payload)

        assert response.is_successful
        assert response.code.value == 200
        assert isinstance(response.value, User)
        assert user.email == Email.build(address='john.doe@gmail.com')

    def test_failure_invalid_email(self, test_domain):
        """Test Invalid Email Login"""
        test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'),
            username='johndoe', password='secret')

        payload = {'email': 'john.doe1@gmail.com', 'password': 'secret'}
        response = Tasklet.perform(User, LoginUseCase, LoginRequestObject, payload=payload)

        assert not response.is_successful
        assert response.code.value == 401
        assert response.errors == [{'email': 'Login Failed'}]

    def test_failure_invalid_password(self, test_domain):
        """Test Invalid Password Login"""
        test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'),
            username='johndoe', password='secret')

        payload = {'email': 'john.doe@gmail.com', 'password': 'secret1'}
        response = Tasklet.perform(User, LoginUseCase, LoginRequestObject, payload=payload)

        assert not response.is_successful
        assert response.code.value == 401
        assert response.errors == [{'password': 'Login Failed'}]


class TestAuthentication:
    """Test Authentication Functionality"""

    def test_success(self, test_domain):
        """Test Successful Authentication with JWT Token"""
        test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'),
            username='johndoe', password='secret')

        payload = {'email': 'john.doe@gmail.com', 'password': 'secret'}
        response = Tasklet.perform(User, LoginUseCase, LoginRequestObject, payload=payload)

        payload = {'token': response.value.token}
        response = Tasklet.perform(User, AuthenticationUseCase,
                                   UserFromTokenRequestObject, payload=payload)
        assert response.is_successful

    def test_failure_expired(self, test_domain):
        """Test Expired JWT Token Login"""
        user = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'),
            username='johndoe', password='secret')

        # Generate the dummy jwt token, that has already expired in the past
        token_data, access_token = encode_access_token(
            identity={'user_id': user.id},
            secret=active_config.SECRET_KEY,
            algorithm=active_config.JWT_ALGORITHM,
            expires_delta=datetime.timedelta(minutes=-60),
            fresh=False,
            csrf=False,
            identity_claim_key='identity',
            user_claims=None,
            user_claims_key=None,
        )

        payload = {'token': access_token}
        response = Tasklet.perform(User, AuthenticationUseCase,
                                   UserFromTokenRequestObject, payload=payload)
        assert not response.is_successful
        assert response.code.value == 401
        assert response.errors == {'token': 'Invalid JWT Token'}

    def test_failure_invalid_token(self, test_domain):
        """Test Login failure due to invalid Token"""
        test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'),
            username='johndoe', password='secret')

        payload = {'token': 'foo-invalid-value-bar'}
        response = Tasklet.perform(User, AuthenticationUseCase,
                                   UserFromTokenRequestObject, payload=payload)
        assert not response.is_successful
        assert response.code.value == 401
        assert response.errors == {'token': 'Invalid JWT Token'}


class TestRegistration:
    """Test Registration Functionality"""

    def test_success(self, test_domain):
        """Test Successful User Registration"""
        payload = {'address': 'john.doe@gmail.com', 'password': 'secret', 'username': 'johndoe',
                   'bio': 'I work at Webmart', 'image': 'https://234ssll.xfg'}
        response = Tasklet.perform(User, RegisterUseCase, RegisterRequestObject, payload=payload)

        assert response.is_successful
        assert response.code.value == 201
        assert isinstance(response.value, User)
        assert response.value.email == Email.build(address='john.doe@gmail.com')
        assert response.value.email_address == 'john.doe@gmail.com'
        assert response.value.username == 'johndoe'

    def test_validation_failure(self, test_domain):
        """Test that validation errors are thrown correctly"""
        payload = {'address': 'john.doe@gmail.com', 'password': 'secret',
                   'bio': 'I work at Webmart', 'image': 'https://234ssll.xfg'}
        response = Tasklet.perform(User, RegisterUseCase, RegisterRequestObject, payload=payload)

        assert not response.is_successful
        assert response.code.value == 422
        # FIXME Nest under `errors`
        assert response.value == {'code': 422, 'errors': [{'username': 'is required'}]}


class TestCurrentUser:
    """Test Fetch Current User Functionality"""

    def test_success(self, test_domain):
        """Test Successful User Fetch from JWT Token"""
        test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'),
            username='johndoe', password='secret')

        payload = {'email': 'john.doe@gmail.com', 'password': 'secret'}
        response = Tasklet.perform(User, LoginUseCase, LoginRequestObject, payload=payload)

        payload = {'token': response.value.token}
        response = Tasklet.perform(User, CurrentUserUseCase,
                                   UserFromTokenRequestObject, payload=payload)
        assert response.is_successful

    def test_failure_invalid_token(self, test_domain):
        """Test Login failure due to invalid Token"""
        test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'),
            username='johndoe', password='secret')

        payload = {'token': 'foo-invalid-value-bar'}
        response = Tasklet.perform(User, CurrentUserUseCase,
                                   UserFromTokenRequestObject, payload=payload)
        assert not response.is_successful
        assert response.code.value == 404
        assert response.errors == {'token': 'User does not exist'}


class TestUpdateUser:
    """Test User Update Functionality"""

    def test_success(self, test_domain):
        """Test Successful User Registration"""
        user = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'),
            username='johndoe', password='secret', token='adjflkasjoiwhnrs',
            bio='I work at Webmart', image='https://234ssll.xfg')

        payload = {'token': user.token,
                   'data': {
                    'address': 'changed.john.doe@gmail.com',
                    'password': 'changed.secret',
                    'username': 'changed.johndoe',
                    'bio': 'changed.I work at Webmart',
                    'image': 'changed.https://234ssll.xfg'}}
        response = Tasklet.perform(User, UpdateUserUseCase, UpdateUserRequestObject,
                                   payload=payload)

        assert response.is_successful
        assert response.code.value == 200
        assert isinstance(response.value, User)
        assert response.value.email == Email.build(address='changed.john.doe@gmail.com')
        assert response.value.username == 'changed.johndoe'

    @pytest.mark.xfail
    def test_validation_failure(self, test_domain):
        """Test that validation errors are thrown correctly"""
        user = test_domain.get_repository(User).create(
            email=Email.build(address='john.doe@gmail.com'),
            username='johndoe', password='secret', token='adjflkasjoiwhnrs',
            bio='I work at Webmart', image='https://234ssll.xfg')

        payload = {'token': user.token,
                   'data': {'address': 'john.doe@gmail.com', 'password': 'secret', 'username': None}}
        response = Tasklet.perform(User, UpdateUserUseCase, UpdateUserRequestObject,
                                   payload=payload)

        assert not response.is_successful
        assert response.code.value == 422
        # FIXME Nest under `errors`
        assert response.value == {'code': 422,
                                  'errors': [{'username': ['is required']}]}
