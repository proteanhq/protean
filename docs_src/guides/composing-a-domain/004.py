from protean import Domain
from protean.fields import ValueObject
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.value_object
class Address:
    address1: Annotated[str, Field(max_length=255)]
    address2: Annotated[str, Field(max_length=255)] | None = None
    address3: Annotated[str, Field(max_length=255)] | None = None
    city: Annotated[str, Field(max_length=25)]
    state: Annotated[str, Field(max_length=25)]
    country: Annotated[str, Field(max_length=2)]
    zip: Annotated[str, Field(max_length=6)]


@domain.aggregate
class User:
    first_name: Annotated[str, Field(max_length=50)] | None = None
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int | None = None
    address = ValueObject(Address)
