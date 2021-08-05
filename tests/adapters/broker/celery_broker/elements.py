from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.field.basic import Auto, Integer, String
from protean.core.subscriber import BaseSubscriber
from protean.globals import current_domain


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)

    @classmethod
    def add_newcomer(cls, person_dict):
        """Factory method to add a new Person to the system"""
        newcomer = Person(
            first_name=person_dict["first_name"],
            last_name=person_dict["last_name"],
            age=person_dict["age"],
        )

        # Publish Event via the domain
        current_domain.publish(
            PersonAdded(
                id=newcomer.id,
                first_name=newcomer.first_name,
                last_name=newcomer.last_name,
                age=newcomer.age,
            )
        )

        return newcomer


class PersonAdded(BaseEvent):
    id = Auto(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class NotifySSOSubscriber(BaseSubscriber):
    """Subscriber that notifies an external SSO system
    that a new person was added into the system
    """

    class Meta:
        event = PersonAdded

    def __call__(self, domain_event_dict):
        print("Received Event: ", domain_event_dict)
        print("Event class: ", self.meta_.event)

        print("Current domain: ", current_domain.domain_name)
