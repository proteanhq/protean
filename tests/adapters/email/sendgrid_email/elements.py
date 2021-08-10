from protean.core.aggregate import BaseAggregate
from protean.core.email import BaseEmail
from protean.core.event import BaseEvent
from protean.core.field.basic import Integer, String
from protean.core.subscriber import BaseSubscriber
from protean.exceptions import InsufficientDataError, InvalidDataError
from protean.globals import current_domain


class Person(BaseAggregate):
    email = String(max_length=255, required=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)

    @classmethod
    def add_newcomer(cls, person_dict):
        """Factory method to add a new Person to the system"""
        newcomer = Person(
            email=person_dict["email"],
            first_name=person_dict["first_name"],
            last_name=person_dict["last_name"],
            age=person_dict["age"],
        )

        # Publish Event via the domain
        current_domain.publish(PersonAdded(person=newcomer))

        return newcomer


class PersonAdded(BaseEvent):
    email = String(max_length=255, required=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class WelcomeEmail(BaseEmail):
    """Emailer to welcome new additions"""

    SUBJECT = "Welcome to ABC!"
    TEMPLATE_ID = "d-2709347159b04353aae539cdf4b1217a"

    def __init__(self, to=None, data=None):
        if to is None or data is None:
            raise InsufficientDataError("`to` and `data` fields are mandatory")

        if not isinstance(data, dict):
            raise InvalidDataError({"data": ["should be a dict"]})

        super().__init__(
            subject=self.SUBJECT, template=self.TEMPLATE_ID, data=data, to=to
        )


class WelcomeNewPerson(BaseSubscriber):
    """Subscriber that notifies an external SSO system
    that a new person was added into the system
    """

    class Meta:
        event = PersonAdded

    def notify(self, event):
        email = WelcomeEmail(to=event.email, data=event.to_dict())
        current_domain.send_email(email)
