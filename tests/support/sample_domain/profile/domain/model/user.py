"""User Aggregate"""
from passlib.hash import pbkdf2_sha256

from protean import Aggregate
from protean.core import field


@Aggregate
class User:
    email = field.String(max_length=50)
    token = field.String(max_length=1024)
    username = field.String(max_length=50)
    password = field.String(max_length=255)

    @classmethod
    def build(cls, *template, **kwargs):
        """In addition to instantiating a User object:
            * hash password
        """
        instance = super(User, cls).build(*template, **kwargs)

        instance.password = pbkdf2_sha256.hash(instance.password)

        return instance
