# Protean
from protean.core.aggregate import BaseAggregate
from protean.core.broker.subscriber import BaseSubscriber
from protean.core.domain_event import BaseDomainEvent
from protean.core.email import BaseEmail
from protean.core.exceptions import InsufficientDataError, InvalidDataError
from protean.core.field.basic import Integer, String
from protean.core.field.embedded import AggregateField
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
            email=person_dict['email'],
            first_name=person_dict['first_name'],
            last_name=person_dict['last_name'],
            age=person_dict['age'],
            )

        # Publish Event via the domain
        current_domain.publish(PersonAdded(person=newcomer))

        return newcomer


class PersonAdded(BaseDomainEvent):
    person = AggregateField(Person)


class WelcomeEmail(BaseEmail):
    """Emailer to welcome new additions"""
    SUBJECT = 'Welcome to ABC!'
    TEMPLATE = """
        Hi %FIRST_NAME%!

        Welcome to ABC!

        Regards,
        Team
    """

    def __init__(self, to=None, data=None):
        if to is None or data is None:
            raise InsufficientDataError("`to` and `data` fields are mandatory")

        if not isinstance(data, dict):
            raise InvalidDataError("`data` should be a dict")

        super().__init__(subject=self.SUBJECT, template=self.TEMPLATE, data=data, to=to)


class WelcomeNewPerson(BaseSubscriber):
    """Subscriber that notifies an external SSO system
    that a new person was added into the system
    """

    class Meta:
        domain_event_cls = PersonAdded

    def notify(self, domain_event):
        email = WelcomeEmail(to=domain_event.person.email, data=domain_event.person.to_dict())
        current_domain.send_email(email)
