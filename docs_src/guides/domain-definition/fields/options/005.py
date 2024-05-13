import random

from protean.domain import Domain
from protean.fields import Integer

domain = Domain(__name__)

dice_sides = [4, 6, 8, 10, 12, 20]


@domain.aggregate
class Dice:
    sides = Integer(default=lambda: random.choice(dice_sides))

    def throw(self):
        return random.randint(1, self.sides)
