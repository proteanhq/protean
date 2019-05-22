from protean.core.value_object import BaseValueObject
from protean.core.field.basic import String


class Email(BaseValueObject):
    """An email address, with two clearly identified parts:
        * local_part
        * domain_part
    """

    address = String(max_length=254)

    def __init__(self, *template, local_part=None, domain_part=None, **kwargs):
        super(Email, self).__init__(*template, **kwargs)
        self.local_part = local_part
        self.domain_part = domain_part

        if self.local_part and self.domain_part:
            self.address = '@'.join([self.local_part, self.domain_part])

    @classmethod
    def from_address(cls, address):
        if not cls.validate(address):
            raise ValueError('Email address is invalid')

        local_part, _, domain_part = address.partition('@')

        return cls(local_part=local_part, domain_part=domain_part)

    @classmethod
    def from_parts(cls, local_part, domain_part):
        return cls(local_part=local_part, domain_part=domain_part)

    @classmethod
    def validate(cls, address):
        if type(address) is not str:
            return False
        if '@' not in address:
            return False
        if len(address) > 255:
            return False

        return True


class MyOrgEmail(Email):
    pass
