"""" Exceptions used by the JWT Authentication Backend """


class JWTBackendException(Exception):
    """
    Base except which all flask_jwt_extended errors extend
    """
    pass


class JWTDecodeError(JWTBackendException):
    """
    An error decoding a JWT
    """
    pass


class CSRFError(JWTBackendException):
    """
    An error with CSRF protection
    """
    pass
