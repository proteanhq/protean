# Protean
from protean.core.field.basic import String


class UserStruct:
    username = String(max_length=50)
    password = String(max_length=255)
