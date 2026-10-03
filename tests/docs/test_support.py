"""Tests for ``load_example``, the helper the docs_src tests load examples with."""

import sys

import pytest

from protean import Domain
from tests.docs.support import load_example, module_name_for

pytestmark = pytest.mark.no_test_domain


def test_module_name_is_built_from_the_path():
    assert (
        module_name_for("guides/getting-started/es-tutorial/ch08.py")
        == "docs_src_guides_getting_started_es_tutorial_ch08"
    )


def test_loads_an_example_and_registers_it():
    module = load_example("guides/getting-started/hello.py")

    assert module.__name__ == "docs_src_guides_getting_started_hello"
    assert sys.modules[module.__name__] is module
    assert isinstance(module.domain, Domain)
    with module.domain.domain_context():
        task = module.Task(title="Buy groceries")
        repo = module.domain.repository_for(module.Task)
        repo.add(task)
        assert repo.get(task.id).title == "Buy groceries"
        assert repo.get(task.id).done is False


def test_a_missing_example_raises():
    with pytest.raises(FileNotFoundError, match="no docs_src example at nope.py"):
        load_example("nope.py")


def test_a_failing_example_is_not_left_in_sys_modules(tmp_path):
    (tmp_path / "broken.py").write_text("raise RuntimeError('boom')\n")

    with pytest.raises(RuntimeError, match="boom"):
        load_example("broken.py", root=tmp_path)

    assert module_name_for("broken.py") not in sys.modules
