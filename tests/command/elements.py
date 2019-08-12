from protean.core.field.basic import String

from protean.core.command import BaseCommand


class UserRegistrationCommand(BaseCommand):
    email = String(required=True, max_length=250)
    username = String(required=True, max_length=50)
    password = String(required=True, max_length=255)
