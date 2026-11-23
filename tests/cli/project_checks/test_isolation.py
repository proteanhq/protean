"""Data one generated test writes is gone before the next test runs.

Runs inside a project that ``protean new`` generates, under the project's own
``conftest.py``. The tests depend on file order: the first writes, the second
requires the repository to be empty.
"""

from scaffolded.domain import scaffolded as domain
from scaffolded.example.aggregate import Example

from protean.utils.globals import _domain_context_stack


def test_1_writes_an_example() -> None:
    example = Example.create(name="Leaky")
    domain.repository_for(Example).add(example)

    assert domain.repository_for(Example).get(example.id).name == "Leaky"


def test_2_sees_no_example() -> None:
    assert domain.repository_for(Example).query.all().total == 0


def test_3_runs_in_exactly_one_domain_context() -> None:
    assert len(_domain_context_stack._var.get([])) == 1
