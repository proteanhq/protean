"""The custom-database-model configuration the aggregate and projection skills teach.

``test_examples.py`` only runs the pack's ``assets/*.py``, and this configuration
cannot live there: every shipped asset imports core only, while a custom database
model needs SQLAlchemy, which sits behind the ``sqlite``/``postgresql`` extras and
is absent from a plain ``pip install protean``. So the guard lives here, where
SQLAlchemy is a dev dependency.

The snippets are executed, not matched. Each test pulls the fenced ``python``
block straight out of the reference page and runs it, so a page whose code stops
being valid Python, names a column no field backs, or drifts back to the inert
``database_model=`` option fails here. A copy of the snippet kept in this file
would pass while the shipped page rotted, which is the whole failure this guards.

The page is a fragment, not a module: it assumes a ``domain`` and the field types
are already in scope, the way the rest of the page does. The namespace below
supplies exactly those, and nothing the snippet is meant to show for itself. Its
own imports, decorators and columns all have to work.

Two tests pin framework behaviour rather than page text: the inert
``database_model=`` option really is accepted and ignored, and a column with no
matching field really is rejected. Those are the claims the pages make in prose,
so they are asserted here rather than left as assertions about wording.
"""

from pathlib import Path

import pytest
from sqlalchemy import Column, Text

from protean import dx
from protean.core.database_model import BaseDatabaseModel
from protean.domain import Domain
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String

# These build their own domains and read package data; they never touch the
# autouse ``test_domain`` fixture, so skip it and its initialization cost.
pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
REFERENCES = PACK_ROOT / dx.SKILLS_DIR

AGGREGATE_PAGE = "aggregate/references/configuration.md"
PROJECTION_PAGE = "projection/references/configuration-options.md"

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the reference pages are read by path",
        allow_module_level=True,
    )


def _snippet(page: str, heading: str) -> str:
    """Return the first fenced ``python`` block under ``heading`` on ``page``.

    Anchoring on the heading rather than on an index keeps the extraction honest
    when a page gains or loses an unrelated example: a renamed or deleted section
    fails loudly here instead of silently running some other snippet.
    """
    text = (REFERENCES / page).read_text()

    assert heading in text, f"{page} no longer has the section `{heading}`"
    after = text.split(heading, 1)[1]

    _, fence, rest = after.partition("```python\n")
    assert fence, f"{page} section `{heading}` has no python example to run"
    snippet, closing, _ = rest.partition("```")
    assert closing, f"{page} section `{heading}` has an unterminated code fence"

    return snippet


def _python_blocks(page: str) -> list[str]:
    """Return every fenced ``python`` block on ``page``."""
    text = (REFERENCES / page).read_text()
    return [part.split("```", 1)[0] for part in text.split("```python\n")[1:]]


def _sqlite_domain() -> Domain:
    """A domain on the SQLAlchemy SQLite provider.

    A custom model is provider-specific, so the memory provider the other
    examples run on cannot exercise this at all.
    """
    domain = Domain(name="CustomModel")
    domain.config["databases"]["default"] = {
        "provider": "sqlite",
        "database_uri": "sqlite:///:memory:",
    }
    return domain


def _run(snippets: list[str], **scope) -> dict:
    """Execute page snippets in one shared namespace and return it."""
    namespace = dict(scope)
    for snippet in snippets:
        exec(compile(snippet, "<reference-page>", "exec"), namespace)
    return namespace


class TestAggregateCustomDatabaseModel:
    def test_the_pages_snippet_runs_and_selects_the_custom_model(self):
        domain = _sqlite_domain()

        namespace = _run(
            [_snippet(AGGREGATE_PAGE, "### Custom database models")],
            domain=domain,
            String=String,
        )

        assert "CustomUserModel" in namespace, (
            "the page's example no longer registers a custom database model"
        )

        domain.init(traverse=False)
        with domain.domain_context():
            model = domain.repository_for(namespace["User"])._database_model

            # `schema_name` on the model sets the table, so the aggregate's own
            # default name ("user") is not what is created.
            assert model.__tablename__ == "users"
            # The declared column is the custom one, not an auto-generated String.
            assert isinstance(model.__table__.c.email.type, Text)
            assert model.__table__.c.email.unique is True
            # Protean still fills in the fields the model left alone.
            assert "full_name" in model.__table__.c

    def test_the_inert_decorator_option_leaves_the_generated_model_in_place(self):
        # This is what the reference page warns about: passing the model to
        # `@domain.aggregate` is accepted and then ignored, so the aggregate
        # keeps its auto-generated model and the custom mapping never applies.
        domain = _sqlite_domain()

        class DetachedUserModel(BaseDatabaseModel):
            email = Column(Text, unique=True)

        @domain.aggregate(database_model=DetachedUserModel)
        class User:
            email: String(required=True, max_length=255)

        domain.init(traverse=False)
        with domain.domain_context():
            model = domain.repository_for(User)._database_model

            assert model is not DetachedUserModel
            assert model.__tablename__ == "user"
            # Auto-generated from the String field, so it is not the custom Text.
            assert not isinstance(model.__table__.c.email.type, Text)

    def test_a_column_with_no_matching_field_is_rejected(self):
        # The page states this as the constraint that keeps a custom model honest.
        domain = _sqlite_domain()

        @domain.aggregate
        class User:
            email: String(required=True, max_length=255)

        with pytest.raises(IncorrectUsageError) as exc:

            @domain.database_model(part_of=User, schema_name="users")
            class CustomUserModel(BaseDatabaseModel):
                user_id = Column(Text)

        assert "user_id" in str(exc.value)


class TestProjectionCustomDatabaseModel:
    def test_the_pages_snippet_runs_and_selects_the_custom_model(self):
        domain = _sqlite_domain()

        # The custom-model snippet builds on the projection the page defines
        # further up, so both run in one namespace, in page order.
        namespace = _run(
            [
                _snippet(PROJECTION_PAGE, "### Database provider (default)"),
                _snippet(PROJECTION_PAGE, "### Custom database models"),
            ],
            domain=domain,
            Identifier=Identifier,
            String=String,
        )

        assert "CustomInventoryModel" in namespace, (
            "the page's example no longer registers a custom database model"
        )

        domain.init(traverse=False)
        with domain.domain_context():
            projection = namespace["ProductInventory"]
            model = domain.repository_for(projection)._database_model

            assert model.__tablename__ == "inventory"
            assert isinstance(model.__table__.c.name.type, Text)
            assert "product_id" in model.__table__.c


class TestNoPageTeachesTheInertOption:
    @pytest.mark.parametrize(
        ("page", "inert_decorator"),
        [
            (AGGREGATE_PAGE, "@domain.aggregate("),
            (PROJECTION_PAGE, "@domain.projection("),
        ],
    )
    def test_no_code_block_passes_the_model_to_the_element_decorator(
        self, page, inert_decorator
    ):
        # The executed snippets above cover the section that teaches this. This
        # sweeps the page's other examples, where the inert form would run
        # without error and so would not be caught by executing it.
        offenders = [
            block
            for block in _python_blocks(page)
            if f"{inert_decorator}database_model=" in block
        ]

        assert not offenders, (
            f"{page} teaches the inert `database_model=` option again; passing a "
            f"model there is accepted and ignored:\n{offenders}"
        )
