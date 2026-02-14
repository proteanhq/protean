from protean import Domain
from protean.fields import HasOne, List, ValueObject
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.value_object
class Address:
    street: Annotated[str, Field(max_length=100)] | None = None
    city: Annotated[str, Field(max_length=25)] | None = None
    state: Annotated[str, Field(max_length=25)] | None = None
    country: Annotated[str, Field(max_length=25)] | None = None


@domain.entity(part_of="Order")
class Customer:
    name: Annotated[str, Field(max_length=50)]
    email: Annotated[str, Field(max_length=254)]
    addresses = List(content_type=ValueObject(Address))


@domain.aggregate
class Order:
    customer = HasOne(Customer)
