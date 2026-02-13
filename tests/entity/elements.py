from __future__ import annotations

from enum import Enum
from typing import Annotated
from uuid import uuid4

from pydantic import Field, field_validator

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity, invariant
from protean.exceptions import ValidationError
from protean.fields import HasOne


class Account(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    account_number: Annotated[str, Field(max_length=50)]


class AbstractPerson(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    age: int = 5


class ConcretePerson(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    first_name: Annotated[str, Field(max_length=50)]
    last_name: Annotated[str, Field(max_length=50)] | None = None


class Person(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    first_name: Annotated[str, Field(max_length=50)]
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int = 21


class PersonAutoSSN(BaseEntity):
    ssn: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    first_name: Annotated[str, Field(max_length=50)]
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int = 21


class PersonExplicitID(BaseEntity):
    ssn: Annotated[
        str,
        Field(max_length=36, json_schema_extra={"identifier": True}),
    ]
    first_name: Annotated[str, Field(max_length=50)]
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int = 21


class Relative(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    first_name: Annotated[str, Field(max_length=50)]
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int = 21
    relative_of = HasOne(Person)


class Adult(Person):
    pass


class NotAPerson(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    first_name: Annotated[str, Field(max_length=50)]
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int = 21


# Entities to test Meta Info overriding # START #
class DbPerson(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    first_name: Annotated[str, Field(max_length=50)]
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int = 21


class SqlPerson(Person):
    pass


class OrderedPerson(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    first_name: Annotated[str, Field(max_length=50)]
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int = 21


class OrderedPersonSubclass(Person):
    pass


class BuildingStatus(Enum):
    WIP = "WIP"
    DONE = "DONE"


class Area(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: Annotated[str, Field(max_length=50)] | None = None


class Building(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: Annotated[str, Field(max_length=50)] | None = None
    floors: int | None = None
    status: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status_choices(cls, v: str | None) -> str | None:
        if v is not None:
            valid = {c.value for c in BuildingStatus}
            if v not in valid:
                raise ValueError(
                    f"Value '{v}' is not a valid choice. "
                    f"Valid choices are: {sorted(valid)}"
                )
        return v

    def defaults(self):
        if not self.status:
            if self.floors == 4:
                self.status = BuildingStatus.DONE.value
            else:
                self.status = BuildingStatus.WIP.value

    @invariant.post
    def test_building_status_to_be_done_if_floors_above_4(self):
        if (
            self.floors is not None
            and self.floors >= 4
            and self.status != BuildingStatus.DONE.value
        ):
            raise ValidationError(
                {"_entity": ["Building status should be DONE if floors are above 4"]}
            )
