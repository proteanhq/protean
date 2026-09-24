"""The custom-database-model configuration the aggregate and projection skills teach.

``test_examples.py`` only runs the pack's ``assets/*.py``, and this configuration
cannot live there: every shipped asset imports core only, while a custom database
model needs SQLAlchemy, which sits behind the ``sqlite``/``postgresql`` extras and
is absent from a plain ``pip install protean``. So the guard lives here, where
SQLAlchemy is a dev dependency, and it does two things:

- It builds the documented configuration and asserts the custom model is the one
  the repository actually selects, for an aggregate and for a projection.
- It builds the inert form the docs warn about, ``database_model=`` passed to
  ``@domain.aggregate``, and asserts it silently leaves the auto-generated model
  in place. That is the bug the reference pages were rewritten to stop teaching.

The last test reads the two reference pages, so a page that drifts back to the
inert form fails here instead of shipping as teaching material that does nothing.
"""

from pathlib import Path

import pytest
from sqlalchemy import Column, Text

from protean import dx
from protean.core.database_model import BaseDatabaseModel
from protean.domain import Domain
from protean.fields import Identifier, String

# These build their own domains and read package data; they never touch the
# autouse ``test_domain`` fixture, so skip it and its initialization cost.
pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
REFERENCES = PACK_ROOT / dx.SKILLS_DIR

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the reference pages are read by path",
        allow_module_level=True,
    )


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


class TestAggregateCustomDatabaseModel:
    def test_the_documented_form_selects_the_custom_model(self):
        domain = _sqlite_domain()

        @domain.aggregate
        class User:
            email: String(required=True, max_length=255)
            full_name: String(required=True, max_length=200)

        @domain.database_model(part_of=User, schema_name="users")
        class CustomUserModel(BaseDatabaseModel):
            email = Column(Text, unique=True)

        domain.init(traverse=False)
        with domain.domain_context():
            model = domain.repository_for(User)._database_model

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
        from protean.exceptions import IncorrectUsageError

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
    def test_the_documented_form_selects_the_custom_model(self):
        domain = _sqlite_domain()

        @domain.projection
        class ProductInventory:
            product_id: Identifier(identifier=True)
            name: String(required=True)

        @domain.database_model(part_of=ProductInventory, schema_name="inventory")
        class CustomInventoryModel(BaseDatabaseModel):
            name = Column(Text)

        domain.init(traverse=False)
        with domain.domain_context():
            model = domain.repository_for(ProductInventory)._database_model

            assert model.__tablename__ == "inventory"
            assert isinstance(model.__table__.c.name.type, Text)
            assert "product_id" in model.__table__.c


class TestTheReferencePagesTeachTheWorkingForm:
    @pytest.mark.parametrize(
        ("page", "inert_decorator"),
        [
            ("aggregate/references/configuration.md", "@domain.aggregate("),
            (
                "projection/references/configuration-options.md",
                "@domain.projection(",
            ),
        ],
    )
    def test_the_page_registers_the_model_and_never_passes_it_to_the_element(
        self, page, inert_decorator
    ):
        text = (REFERENCES / page).read_text()

        assert "@domain.database_model(part_of=" in text, (
            f"{page} no longer shows the registration that actually works"
        )
        assert f"{inert_decorator}database_model=" not in text, (
            f"{page} teaches the inert `database_model=` option again; passing a "
            f"model there is accepted and ignored"
        )
