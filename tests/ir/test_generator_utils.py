"""Tests for the IR generator base utilities.

Covers: mermaid_escape, mermaid_fence, short_name, module_path,
field_type_label, field_summary, sanitize_mermaid_id.
"""

from protean.ir.generators.base import (
    field_summary,
    field_type_label,
    mermaid_escape,
    mermaid_fence,
    module_path,
    sanitize_mermaid_id,
    short_name,
)


# ------------------------------------------------------------------
# mermaid_escape
# ------------------------------------------------------------------


class TestMermaidEscape:
    def test_plain_text_unchanged(self):
        assert mermaid_escape("Order") == "Order"

    def test_empty_string(self):
        assert mermaid_escape("") == ""

    def test_brackets_escaped(self):
        result = mermaid_escape("dict[str, int]")
        assert result == '"dict[str, int]"'

    def test_curly_braces_escaped(self):
        result = mermaid_escape("{value}")
        assert result == '"{value}"'

    def test_parens_escaped(self):
        result = mermaid_escape("func(x)")
        assert result == '"func(x)"'

    def test_angle_brackets_escaped(self):
        result = mermaid_escape("List<int>")
        assert result == '"List<int>"'

    def test_pipe_escaped(self):
        result = mermaid_escape("A | B")
        assert result == '"A | B"'

    def test_hash_escaped(self):
        result = mermaid_escape("item #1")
        assert result == '"item #1"'

    def test_ampersand_escaped(self):
        result = mermaid_escape("A & B")
        assert result == '"A & B"'

    def test_embedded_quotes_escaped(self):
        result = mermaid_escape('say "hello"')
        assert result == '"say #quot;hello#quot;"'

    def test_multiple_special_chars(self):
        result = mermaid_escape("A[B]{C}")
        assert result == '"A[B]{C}"'


# ------------------------------------------------------------------
# mermaid_fence
# ------------------------------------------------------------------


class TestMermaidFence:
    def test_basic_fence(self):
        result = mermaid_fence("graph LR\n  A --> B")
        assert result == "```mermaid\ngraph LR\n  A --> B\n```"

    def test_fence_with_title(self):
        result = mermaid_fence("graph TD\n  X --> Y", title="My Diagram")
        assert result.startswith("## My Diagram\n")
        assert "```mermaid" in result
        assert result.endswith("```")

    def test_empty_body(self):
        result = mermaid_fence("")
        assert result == "```mermaid\n\n```"

    def test_body_with_backticks_uses_longer_fence(self):
        body = "A --> B\n```\nC --> D"
        result = mermaid_fence(body)
        assert result.startswith("````mermaid\n")
        assert result.endswith("\n````")

    def test_body_with_long_backtick_run(self):
        body = "A --> B\n`````\nC --> D"
        result = mermaid_fence(body)
        assert result.startswith("``````mermaid\n")
        assert result.endswith("\n``````")


# ------------------------------------------------------------------
# short_name
# ------------------------------------------------------------------


class TestShortName:
    def test_fqn(self):
        assert short_name("ecommerce.ordering.Order") == "Order"

    def test_already_short(self):
        assert short_name("Order") == "Order"

    def test_empty_string(self):
        assert short_name("") == ""

    def test_single_dot(self):
        assert short_name("a.B") == "B"


# ------------------------------------------------------------------
# module_path
# ------------------------------------------------------------------


class TestModulePath:
    def test_fqn(self):
        assert module_path("ecommerce.ordering.Order") == "ecommerce.ordering"

    def test_no_module(self):
        assert module_path("Order") == ""

    def test_single_dot(self):
        assert module_path("a.B") == "a"


# ------------------------------------------------------------------
# field_type_label
# ------------------------------------------------------------------


class TestFieldTypeLabel:
    def test_standard_string(self):
        assert field_type_label({"kind": "standard", "type": "String"}) == "String"

    def test_auto(self):
        assert field_type_label({"kind": "auto"}) == "Auto"

    def test_value_object(self):
        result = field_type_label({"kind": "value_object", "target": "app.Address"})
        assert result == "Address"

    def test_has_one(self):
        result = field_type_label({"kind": "has_one", "target": "app.Profile"})
        assert result == "Profile"

    def test_reference(self):
        result = field_type_label({"kind": "reference", "target": "app.User"})
        assert result == "User"

    def test_has_many(self):
        result = field_type_label({"kind": "has_many", "target": "app.OrderItem"})
        assert result == "OrderItem[]"

    def test_value_object_list(self):
        result = field_type_label({"kind": "value_object_list", "target": "app.Tag"})
        assert result == "List[Tag]"

    def test_list_with_content_type(self):
        result = field_type_label(
            {"kind": "list", "type": "List", "content_type": "String"}
        )
        assert result == "List[String]"

    def test_list_without_content_type(self):
        result = field_type_label({"kind": "list", "type": "List"})
        assert result == "List"

    def test_dict(self):
        assert field_type_label({"kind": "dict", "type": "Dict"}) == "Dict"

    def test_missing_kind_defaults_to_standard(self):
        assert field_type_label({"type": "Float"}) == "Float"

    def test_missing_type_returns_question_mark(self):
        assert field_type_label({"kind": "standard"}) == "?"

    def test_has_many_missing_target(self):
        assert field_type_label({"kind": "has_many"}) == "?[]"

    def test_value_object_missing_target(self):
        assert field_type_label({"kind": "value_object"}) == "value_object"

    def test_value_object_list_missing_target(self):
        assert field_type_label({"kind": "value_object_list"}) == "List[?]"


# ------------------------------------------------------------------
# field_summary
# ------------------------------------------------------------------


class TestFieldSummary:
    def test_simple_field(self):
        assert field_summary({"kind": "standard", "type": "Integer"}) == "Integer"

    def test_required_field(self):
        result = field_summary({"kind": "standard", "type": "String", "required": True})
        assert result == "String (required)"

    def test_identifier_field(self):
        result = field_summary({"kind": "auto", "identifier": True})
        assert result == "Auto (identifier)"

    def test_identifier_suppresses_required_and_unique(self):
        result = field_summary(
            {"kind": "auto", "identifier": True, "required": True, "unique": True}
        )
        assert result == "Auto (identifier)"

    def test_unique_field(self):
        result = field_summary({"kind": "standard", "type": "String", "unique": True})
        assert result == "String (unique)"

    def test_required_and_unique(self):
        result = field_summary(
            {"kind": "standard", "type": "String", "required": True, "unique": True}
        )
        assert result == "String (required, unique)"


# ------------------------------------------------------------------
# sanitize_mermaid_id
# ------------------------------------------------------------------


class TestSanitizeMermaidId:
    def test_fqn(self):
        assert (
            sanitize_mermaid_id("ecommerce.ordering.Order")
            == "ecommerce_ordering_Order"
        )

    def test_already_clean(self):
        assert sanitize_mermaid_id("Order") == "Order"

    def test_hyphens_and_spaces(self):
        assert sanitize_mermaid_id("my-app order") == "my_app_order"

    def test_multiple_specials_collapsed(self):
        assert sanitize_mermaid_id("a..b") == "a_b"

    def test_leading_trailing_stripped(self):
        assert sanitize_mermaid_id(".Order.") == "Order"

    def test_empty_string_returns_fallback(self):
        assert sanitize_mermaid_id("") == "node"

    def test_only_special_chars_returns_fallback(self):
        assert sanitize_mermaid_id("...") == "node"
