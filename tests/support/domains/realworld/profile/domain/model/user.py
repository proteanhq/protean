"""User Aggregate"""
from __future__ import annotations

# Protean
from passlib.hash import pbkdf2_sha256
from protean import Aggregate, ValueObject
from protean.core import field


@ValueObject(aggregate='user', bounded_context='identity')
class Email:
    """An email address, with two clearly identified parts:
        * local_part
        * domain_part
    """

    address = field.String(max_length=254)

    def __init__(self, *template, local_part=None, domain_part=None, **kwargs):
        super(Email, self).__init__(*template, **kwargs)
        self.local_part = local_part
        self.domain_part = domain_part

        if self.local_part and self.domain_part:
            self.address = '@'.join([self.local_part, self.domain_part])

    @classmethod
    def build(cls, **values):
        assert 'address' in values

        if '@' not in values['address']:
            raise ValueError('Email address is invalid. Must contain \'@\'')
        local_part, _, domain_part = values['address'].partition('@')

        return cls.build_from_parts(local_part, domain_part)

    @classmethod
    def build_from_parts(cls, local_part, domain_part):
        if len(local_part) + len(domain_part) > 255:
            raise ValueError('Email address is too long')
        return cls(local_part=local_part, domain_part=domain_part)

    def _clone_with_values(self, **kwargs):
        # FIXME Find a way to do this generically and move method to `BaseValueObject`
        local = kwargs.pop('local', None)
        domain = kwargs.pop('domain', None)
        return Email(local_part=local or self.local_part,
                     domain_part=domain or self.domain_part)


@Aggregate(aggregate='user', bounded_context='identity', root=True)
class User:
    email = field.ValueObject(Email)
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
