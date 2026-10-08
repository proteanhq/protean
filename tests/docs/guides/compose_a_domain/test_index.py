"""The example on the Set Up the Domain guide behaves as the page says."""

from pathlib import Path

import pytest

from protean import Domain
from tests.docs.support import DOCS_SRC, load_example

pytestmark = pytest.mark.no_test_domain


def test_a_bare_domain_takes_its_root_path_from_the_calling_file():
    example = load_example("guides/compose-a-domain/index/001.py")

    assert isinstance(example.domain, Domain)
    assert Path(example.domain.root_path) == DOCS_SRC / "guides/compose-a-domain/index"


def test_a_bare_domain_initializes_with_no_elements():
    example = load_example("guides/compose-a-domain/index/001.py")
    example.domain.init(traverse=False)

    assert example.domain.registry.elements == {}
