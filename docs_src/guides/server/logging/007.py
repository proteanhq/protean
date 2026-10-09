from protean import Domain

# isort: split

# --8<-- [start:testing]
from protean.utils.logging import configure_for_testing

configure_for_testing()
# --8<-- [end:testing]

domain = Domain(name="Orders")
