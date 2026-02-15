"""Tests for _prepare_pydantic_namespace in utils/__init__.py.

Covers uncovered lines:
- Lines 296-297: FieldSpec with identifier=True in namespace
- Lines 300-305: FieldSpec with identifier=True in annotations
- Lines 311-318: String annotation with identifier markers
- Lines 322-329: Annotated[type, Field(..., identifier=True)]
- Lines 334-337: Direct FieldInfo default with identifier
"""

from typing import Annotated
from uuid import UUID

from pydantic import Field as PydanticField

from protean.core.entity import BaseEntity
from protean.fields.spec import FieldSpec
from protean.utils import _prepare_pydantic_namespace


class TestPrepareNamespaceIdentifierDetection:
    """Test that _prepare_pydantic_namespace detects identifiers in various forms."""

    def test_fieldspec_identifier_in_namespace(self):
        """Lines 296-297: FieldSpec with identifier=True found in namespace."""
        spec = FieldSpec(str, identifier=True)
        new_dict = {
            "my_id": spec,
            "__annotations__": {},
        }
        _prepare_pydantic_namespace(new_dict, BaseEntity, {})
        # Should NOT inject an auto "id" field since identifier exists
        assert "id" not in new_dict.get("__annotations__", {}) or "id" not in new_dict

    def test_fieldspec_identifier_in_annotations(self):
        """Lines 303-305: FieldSpec with identifier=True in annotations."""
        spec = FieldSpec(str, identifier=True)
        new_dict = {
            "__annotations__": {"my_id": spec},
        }
        _prepare_pydantic_namespace(new_dict, BaseEntity, {})
        # Should NOT inject an auto "id" field since identifier exists
        annots = new_dict["__annotations__"]
        assert "id" not in annots or not isinstance(
            annots.get("id"), (type(str | int | UUID),)
        )

    def test_string_annotation_double_quote_identifier(self):
        """Lines 313-314: String annotation with "identifier": True."""
        new_dict = {
            "__annotations__": {
                "my_id": 'Annotated[str, Field(json_schema_extra={"identifier": True})]'
            },
        }
        _prepare_pydantic_namespace(new_dict, BaseEntity, {})
        annots = new_dict["__annotations__"]
        # id should not be injected because the string annotation contains identifier marker
        assert "id" not in annots

    def test_string_annotation_single_quote_identifier(self):
        """Lines 316-317: String annotation with 'identifier': True."""
        new_dict = {
            "__annotations__": {
                "my_id": "Annotated[str, Field(json_schema_extra={'identifier': True})]"
            },
        }
        _prepare_pydantic_namespace(new_dict, BaseEntity, {})
        annots = new_dict["__annotations__"]
        # id should not be injected
        assert "id" not in annots

    def test_annotated_field_info_identifier(self):
        """Lines 322-327: Annotated[type, FieldInfo] with identifier."""
        field = PydanticField(json_schema_extra={"identifier": True})
        annot = Annotated[str, field]
        new_dict = {
            "__annotations__": {"my_id": annot},
        }
        _prepare_pydantic_namespace(new_dict, BaseEntity, {})
        annots = new_dict["__annotations__"]
        # id should not be injected
        assert "id" not in annots

    def test_direct_field_info_default_identifier(self):
        """Lines 334-337: Direct FieldInfo default with identifier."""
        field_info = PydanticField(json_schema_extra={"identifier": True})
        new_dict = {
            "__annotations__": {"my_id": str},
            "my_id": field_info,
        }
        _prepare_pydantic_namespace(new_dict, BaseEntity, {})
        annots = new_dict["__annotations__"]
        # id should not be injected
        assert "id" not in annots

    def test_no_identifier_injects_auto_id(self):
        """Lines 339-344: No identifier found → auto id injected."""
        new_dict = {
            "__annotations__": {"name": str},
        }
        _prepare_pydantic_namespace(new_dict, BaseEntity, {})
        annots = new_dict["__annotations__"]
        # Auto id should be injected
        assert "id" in annots
        assert "id" in new_dict

    def test_auto_add_id_field_false_skips_injection(self):
        """Line 285: auto_add_id_field=False skips identifier detection."""
        new_dict = {
            "__annotations__": {"name": str},
        }
        _prepare_pydantic_namespace(new_dict, BaseEntity, {"auto_add_id_field": False})
        annots = new_dict["__annotations__"]
        # id should not be injected when auto_add_id_field=False
        assert "id" not in annots

    def test_private_fields_skipped_in_namespace_scan(self):
        """Lines 293, 302, 310: Fields starting with _ are skipped."""
        spec = FieldSpec(str, identifier=True)
        new_dict = {
            "_private": spec,
            "__annotations__": {"_private_annot": spec},
        }
        _prepare_pydantic_namespace(new_dict, BaseEntity, {})
        # Private fields should be skipped, so auto id IS injected
        annots = new_dict["__annotations__"]
        assert "id" in annots
