"""The projector lookup snippets: which exception they teach catching.

``error-handling.md`` and ``cross-aggregate.md`` each carry a fenced snippet
that looks up a projection record that may not exist yet and reacts to a miss.
Both must catch ``ObjectNotFoundError``, the one exception ``repo.get()``
raises for a missing record (``protean.core.repository``): a bare
``except Exception`` would also swallow connection errors and validation
failures that should propagate, and ``NotFoundError`` is not a real class in
``protean`` (importing it raises ``ImportError``, and referencing it bare
raises ``NameError`` on the first miss).

``tests/dx/test_plugin.py`` already guards pack against render drift, but
drift is all it checks: a pack edit that reintroduces one of the wrong
exceptions and then reruns ``build-plugin`` keeps pack and render matched and
every one of those tests green. This is the standing guard for the exception
type itself, so that regression cannot slip back in unnoticed.
"""

from __future__ import annotations

from pathlib import Path

from protean import dx
from protean.dx.pack import REFERENCES_DIR as REFERENCES_DIRNAME

PACK_ROOT = Path(str(dx.pack_files()))
REFERENCES_DIR = PACK_ROOT / dx.SKILLS_DIR / "projector" / REFERENCES_DIRNAME

WRONG_EXCEPTIONS = ("except Exception:", "except NotFoundError:")
IMPORT_LINE = "from protean.exceptions import ObjectNotFoundError"


def _assert_snippet_catches_only_object_not_found_error(filename: str) -> None:
    text = (REFERENCES_DIR / filename).read_text()

    for wrong in WRONG_EXCEPTIONS:
        assert wrong not in text, (
            f"{filename} must not catch a lookup miss with {wrong!r}; "
            "repo.get() raises ObjectNotFoundError, and this snippet is the "
            "one users copy for handling a missing projection record"
        )
    assert "except ObjectNotFoundError:" in text, (
        f"{filename} must catch ObjectNotFoundError around the lookup that may miss"
    )
    assert IMPORT_LINE in text, (
        f"{filename} must import ObjectNotFoundError from protean.exceptions "
        "so the snippet is copy-paste runnable"
    )


def test_error_handling_snippet_catches_only_object_not_found_error():
    _assert_snippet_catches_only_object_not_found_error("error-handling.md")


def test_cross_aggregate_snippet_catches_only_object_not_found_error():
    _assert_snippet_catches_only_object_not_found_error("cross-aggregate.md")
