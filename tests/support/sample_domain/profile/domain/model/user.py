"""User Aggregate"""
from __future__ import annotations
from passlib.hash import pbkdf2_sha256

from protean import Aggregate, ValueObject
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


@ValueObject
class Email:
    """An email address, with two clearly identified parts:
        * local_part
        * domain_part
    """

    local_part = field.String(max_length=64)
    domain_part = field.String(max_length=255)

    @classmethod
    def from_address(cls, address: str) -> Email:
        if '@' not in address:
            raise ValueError('Email address is invalid. Must contain \'@\'')
        local_part, _, domain_part = address.partition('@')
        return cls.build(local_part, domain_part)

    @classmethod
    def build(cls, local_part, domain_part):
        if len(local_part) + len(domain_part) > 255:
            raise ValueError('Email address is too long')
        return cls(dict(local_part=local_part, domain_part=domain_part))

    def replace(self, local=None, domain=None):
        return Email(local_part=local or self._parts[0],
                     domain_part=domain or self._parts[1])
