"""Tests for the IR generator base utilities.

Checks mermaid_escape, mermaid_fence, short_name, module_path,
field_type_label, field_summary and sanitize_mermaid_id.
"""

import pytest

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
    @pytest.mark.parametrize(
        "text, expected",
        [
            pytest.param("Order", "Order", id="plain_text_unchanged"),
            pytest.param("", "", id="empty_string"),
            pytest.param("dict[str, int]", '"dict[str, int]"', id="brackets"),
            pytest.param("{value}", '"{value}"', id="curly_braces"),
            pytest.param("func(x)", '"func(x)"', id="parens"),
            pytest.param("List<int>", '"List<int>"', id="angle_brackets"),
            pytest.param("A | B", '"A | B"', id="pipe"),
            pytest.param("item #1", '"item #1"', id="hash"),
            pytest.param("A & B", '"A & B"', id="ampersand"),
            pytest.param(
                'say "hello"', '"say #quot;hello#quot;"', id="embedded_quotes"
            ),
            pytest.param("A[B]{C}", '"A[B]{C}"', id="multiple_special_chars"),
        ],
    )
    def test_quotes_text_with_mermaid_special_characters(self, text, expected):
        assert mermaid_escape(text) == expected


# ------------------------------------------------------------------
# mermaid_fence
# ------------------------------------------------------------------


class TestMermaidFence:
    @pytest.mark.parametrize(
        "body, expected",
        [
            pytest.param(
                "graph LR\n  A --> B",
                "```mermaid\ngraph LR\n  A --> B\n```",
                id="basic_fence",
            ),
            pytest.param("", "```mermaid\n\n```", id="empty_body"),
            pytest.param(
                "A --> B\n```\nC --> D",
                "````mermaid\nA --> B\n```\nC --> D\n````",
                id="body_with_backticks_uses_longer_fence",
            ),
            pytest.param(
                "A --> B\n`````\nC --> D",
                "``````mermaid\nA --> B\n`````\nC --> D\n``````",
                id="body_with_long_backtick_run",
            ),
        ],
    )
    def test_fence_is_longer_than_any_backtick_run_in_body(self, body, expected):
        assert mermaid_fence(body) == expected

    def test_fence_with_title(self):
        result = mermaid_fence("graph TD\n  X --> Y", title="My Diagram")
        assert result.startswith("## My Diagram\n")
        assert "```mermaid" in result
        assert result.endswith("```")


# ------------------------------------------------------------------
# short_name and module_path
# ------------------------------------------------------------------


class TestShortName:
    @pytest.mark.parametrize(
        "fqn, expected",
        [
            pytest.param("ecommerce.ordering.Order", "Order", id="fqn"),
            pytest.param("Order", "Order", id="already_short"),
            pytest.param("", "", id="empty_string"),
            pytest.param("a.B", "B", id="single_dot"),
        ],
    )
    def test_returns_last_dotted_segment(self, fqn, expected):
        assert short_name(fqn) == expected


class TestModulePath:
    @pytest.mark.parametrize(
        "fqn, expected",
        [
            pytest.param("ecommerce.ordering.Order", "ecommerce.ordering", id="fqn"),
            pytest.param("Order", "", id="no_module"),
            pytest.param("a.B", "a", id="single_dot"),
        ],
    )
    def test_returns_everything_before_last_dot(self, fqn, expected):
        assert module_path(fqn) == expected


# ------------------------------------------------------------------
# field_type_label
# ------------------------------------------------------------------


class TestFieldTypeLabel:
    @pytest.mark.parametrize(
        "field, expected",
        [
            pytest.param(
                {"kind": "standard", "type": "String"}, "String", id="standard_string"
            ),
            pytest.param({"kind": "auto"}, "Auto", id="auto"),
            pytest.param(
                {"kind": "value_object", "target": "app.Address"},
                "Address",
                id="value_object",
            ),
            pytest.param(
                {"kind": "has_one", "target": "app.Profile"}, "Profile", id="has_one"
            ),
            pytest.param(
                {"kind": "reference", "target": "app.User"}, "User", id="reference"
            ),
            pytest.param(
                {"kind": "has_many", "target": "app.OrderItem"},
                "OrderItem[]",
                id="has_many",
            ),
            pytest.param(
                {"kind": "value_object_list", "target": "app.Tag"},
                "List[Tag]",
                id="value_object_list",
            ),
            pytest.param(
                {"kind": "list", "type": "List", "content_type": "String"},
                "List[String]",
                id="list_with_content_type",
            ),
            pytest.param(
                {"kind": "list", "type": "List"}, "List", id="list_without_content_type"
            ),
            pytest.param({"kind": "dict", "type": "Dict"}, "Dict", id="dict"),
            pytest.param(
                {"type": "Float"}, "Float", id="missing_kind_defaults_to_standard"
            ),
            pytest.param(
                {"kind": "standard"}, "?", id="missing_type_returns_question_mark"
            ),
            pytest.param({"kind": "has_many"}, "?[]", id="has_many_missing_target"),
            pytest.param(
                {"kind": "value_object"},
                "value_object",
                id="value_object_missing_target",
            ),
            pytest.param(
                {"kind": "value_object_list"},
                "List[?]",
                id="value_object_list_missing_target",
            ),
        ],
    )
    def test_label_for_field_kind(self, field, expected):
        assert field_type_label(field) == expected


# ------------------------------------------------------------------
# field_summary
# ------------------------------------------------------------------


class TestFieldSummary:
    @pytest.mark.parametrize(
        "field, expected",
        [
            pytest.param(
                {"kind": "standard", "type": "Integer"}, "Integer", id="simple_field"
            ),
            pytest.param(
                {"kind": "standard", "type": "String", "required": True},
                "String (required)",
                id="required_field",
            ),
            pytest.param(
                {"kind": "auto", "identifier": True},
                "Auto (identifier)",
                id="identifier_field",
            ),
            pytest.param(
                {"kind": "auto", "identifier": True, "required": True, "unique": True},
                "Auto (identifier)",
                id="identifier_suppresses_required_and_unique",
            ),
            pytest.param(
                {"kind": "standard", "type": "String", "unique": True},
                "String (unique)",
                id="unique_field",
            ),
            pytest.param(
                {
                    "kind": "standard",
                    "type": "String",
                    "required": True,
                    "unique": True,
                },
                "String (required, unique)",
                id="required_and_unique",
            ),
        ],
    )
    def test_summary_lists_type_and_flags(self, field, expected):
        assert field_summary(field) == expected


# ------------------------------------------------------------------
# sanitize_mermaid_id
# ------------------------------------------------------------------


class TestSanitizeMermaidId:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            pytest.param(
                "ecommerce.ordering.Order", "ecommerce_ordering_Order", id="fqn"
            ),
            pytest.param("Order", "Order", id="already_clean"),
            pytest.param("my-app order", "my_app_order", id="hyphens_and_spaces"),
            pytest.param("a..b", "a_b", id="multiple_specials_collapsed"),
            pytest.param(".Order.", "Order", id="leading_trailing_stripped"),
            pytest.param("", "node", id="empty_string_returns_fallback"),
            pytest.param("...", "node", id="only_special_chars_returns_fallback"),
        ],
    )
    def test_replaces_non_identifier_characters(self, raw, expected):
        assert sanitize_mermaid_id(raw) == expected
