"""This test file initializes the domain object without an explicit name.

The test is to check if the name is initialized to the module containing the domain file.
"""

from protean.domain import Domain

domain = Domain(__file__)
