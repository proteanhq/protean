# Protean
from protean.core.aggregate import BaseAggregate
from protean.core.data_transfer_object import BaseDataTransferObject
from protean.core.field.basic import Integer, String


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    email = String(max_length=255, required=True)
    age = Integer(default=21)
    address1 = String(max_length=255, required=True)
    address2 = String(max_length=255)
    city = String(max_length=50, required=True)
    province = String(max_length=50, required=True)
    country = String(max_length=2, required=True)

    def basic_info(self):
        return PersonBasicDetails(first_name=self.first_name, last_name=self.last_name, email=self.email)


class PersonBasicDetails(BaseDataTransferObject):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    email = String(max_length=255, required=True)
