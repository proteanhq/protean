"""Test fixtures for custom lint rules.

These callables are referenced by dotted path in custom lint rule tests.
Each follows the signature ``(ir: dict) -> list[dict]``.
"""


def good_rule(ir: dict) -> list[dict]:
    """A well-behaved custom rule that returns valid diagnostics."""
    return [
        {
            "code": "CUSTOM_CHECK",
            "element": "test.element",
            "level": "info",
            "message": "Custom rule found something",
        }
    ]


def multi_result_rule(ir: dict) -> list[dict]:
    """Returns multiple diagnostics."""
    return [
        {
            "code": "CUSTOM_A",
            "element": "test.a",
            "level": "warning",
            "message": "First custom finding",
        },
        {
            "code": "CUSTOM_B",
            "element": "test.b",
            "level": "info",
            "message": "Second custom finding",
        },
    ]


def empty_rule(ir: dict) -> list[dict]:
    """A rule that finds nothing."""
    return []


def raising_rule(ir: dict) -> list[dict]:
    """A rule that raises an exception."""
    raise RuntimeError("Something went wrong in the rule")


def bad_return_type(ir: dict) -> str:
    """Returns wrong type (str instead of list)."""
    return "not a list"


def missing_keys_rule(ir: dict) -> list[dict]:
    """Returns dicts missing required keys."""
    return [{"code": "PARTIAL", "message": "missing element and level"}]


def bad_level_rule(ir: dict) -> list[dict]:
    """Returns a dict with an invalid level value."""
    return [
        {
            "code": "BAD_LEVEL",
            "element": "test.element",
            "level": "critical",
            "message": "Invalid level value",
        }
    ]


def error_level_rule(ir: dict) -> list[dict]:
    """Returns a dict with 'error' level — not allowed for custom rules."""
    return [
        {
            "code": "CUSTOM_ERROR",
            "element": "test.element",
            "level": "error",
            "message": "Custom rules cannot use error level",
        }
    ]


def non_dict_item_rule(ir: dict) -> list[dict]:
    """Returns a list containing a non-dict item."""
    return ["not a dict"]
