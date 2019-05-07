"""Primary Module to define version and expose packages"""

__version__ = '0.0.11'

# Local/Relative Imports
from .domain import Domain, Entity

# Temporary - Implementation pending
# Support Aggregate annotation as an equivalent of Entity
Aggregate = Entity

__all__ = ('Domain', 'Entity', 'Aggregate')
