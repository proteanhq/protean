from protean.core.entity import Entity
from protean.core import field


class ImmortalDog(Entity):
    """A Dog who lives forever"""

    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.String(required=True, max_length=15)

    def delete(self):
        """You can't delete me!!"""
        raise SystemError("Deletion Prohibited!")
