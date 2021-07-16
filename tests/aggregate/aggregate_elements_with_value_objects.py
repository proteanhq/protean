from enum import Enum

from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import String
from protean.core.field.embedded import ValueObject
from protean.core.value_object import BaseValueObject


class FileType(Enum):
    PDF = "PDF"
    PPT = "PPT"


class File(BaseValueObject):
    url = String(max_length=1024)
    type = String(max_length=15, choices=FileType)

    class Meta:
        aggregate_cls = "Resource"


class Resource(BaseAggregate):
    title = String(required=True, max_length=50)
    associated_file = ValueObject(File)
