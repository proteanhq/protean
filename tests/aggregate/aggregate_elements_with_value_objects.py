from enum import Enum

from protean import BaseAggregate, BaseValueObject
from protean.fields import String, ValueObject


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
