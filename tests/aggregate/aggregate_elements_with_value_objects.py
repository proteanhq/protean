from enum import Enum

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields import ValueObject


class FileType(Enum):
    PDF = "PDF"
    PPT = "PPT"


class File(BaseValueObject):
    url: str | None = None
    type: FileType | None = None


class Resource(BaseAggregate):
    title: str
    associated_file = ValueObject(File)
