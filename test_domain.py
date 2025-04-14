"""
Simple test domain to demonstrate the FastAPI server
"""

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String


class Person(BaseAggregate):
    """Person Aggregate"""

    name = String(max_length=50, required=True)
    age = Integer(default=0)


# Initialize the domain
domain = Domain(__name__)

# Register the aggregate
domain.register(Person)
