"""Diagnostics: TestLintTableConfigValidation."""

import pytest

from protean import Domain
from protean.exceptions import ConfigurationError
from protean.fields.simple import String
from protean.ir.builder import IRBuilder, validate_lint_table

BAD_COMMAND_VERBS = ["adjust", [1], [""], ["void-it"], [True], [["adjust"]]]


class TestLintTableConfigValidation:
    """``[lint]`` itself must be a table — non-CLI entry points (``protean
    generate``, materialize hooks, staleness detection) build the IR directly
    without going through ``protean check``'s validation, so the builder must
    reject a malformed ``[lint]`` before any ``[lint]``-scoped rule reads it."""

    def test_non_table_lint_raises_configuration_error(self):
        domain = Domain(name="BadLintTable", root_path=".")
        domain.config["lint"] = 5

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        with pytest.raises(ConfigurationError, match=r"\[lint\] must be a table"):
            IRBuilder(domain).build()

    def test_non_table_lint_raises_before_aggregate_size_limit_read(self):
        """``aggregate_size_limit`` runs before the suppression
        stage in ``_collect_diagnostics`` — the guard must fire before *any*
        rule reads ``[lint]``, not just before ``_apply_suppressions``."""
        domain = Domain(name="BadLintTableEarly", root_path=".")
        domain.config["lint"] = "not-a-table"

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        with pytest.raises(ConfigurationError, match=r"\[lint\] must be a table"):
            IRBuilder(domain).build()


class TestLintOptionTypeValidation:
    """A wrong type for a ``[lint]`` option raises ``ConfigurationError``."""

    @pytest.mark.parametrize(
        "lint, message",
        [
            ({"rules": 5}, r"\[lint\]\.rules must be a list"),
            ({"rules": "my.module"}, r"\[lint\]\.rules must be a list"),
            ({"rules": ["ok.rule", 3]}, r"\[lint\]\.rules must be a list"),
            (
                {"aggregate_size_limit": "5"},
                r"\[lint\]\.aggregate_size_limit must be a non-negative integer",
            ),
            (
                {"aggregate_size_limit": True},
                r"\[lint\]\.aggregate_size_limit must be a non-negative integer",
            ),
            (
                {"aggregate_size_limit": -1},
                r"\[lint\]\.aggregate_size_limit must be a non-negative integer",
            ),
            (
                {"aggregate_size_limit": 5.0},
                r"\[lint\]\.aggregate_size_limit must be a non-negative integer",
            ),
            (
                {"handler_breadth_limit": "5"},
                r"\[lint\]\.handler_breadth_limit must be a non-negative integer",
            ),
            (
                {"handler_breadth_limit": -1},
                r"\[lint\]\.handler_breadth_limit must be a non-negative integer",
            ),
            (
                {"check_infra_imports": "yes"},
                r"\[lint\]\.check_infra_imports must be true or false",
            ),
            (
                {"check_adapter_calls": 1},
                r"\[lint\]\.check_adapter_calls must be true or false",
            ),
            *(
                (
                    {"command_verbs": bad},
                    r"\[lint\]\.command_verbs must be a list of non-empty alphabetic",
                )
                for bad in BAD_COMMAND_VERBS
            ),
        ],
    )
    def test_bad_option_type_raises(self, lint, message):
        domain = Domain(name="BadLintOption", root_path=".")
        domain.config["lint"] = lint

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        with pytest.raises(ConfigurationError, match=message):
            IRBuilder(domain).build()

    def test_valid_options_build(self):
        domain = Domain(name="GoodLintOptions", root_path=".")
        domain.config["lint"] = {
            "rules": [],
            "aggregate_size_limit": 0,
            "handler_breadth_limit": 10,
            "check_infra_imports": True,
            "check_adapter_calls": False,
        }

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Order has no entities, so a limit of 0 is not exceeded.
        codes = [d["code"] for d in ir["diagnostics"]]
        assert "AGGREGATE_TOO_LARGE" not in codes
        assert len(ir["clusters"]) == 1

    def test_bad_level_builds(self):
        # The IR builder does not read ``level``; only ``protean check`` and
        # ``protean verify`` reject a bad one.
        domain = Domain(name="BadLintLevel", root_path=".")
        domain.config["lint"] = {"level": 5}

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert len(ir["clusters"]) == 1


class TestCommandVerbsValidation:
    @pytest.mark.parametrize("bad", BAD_COMMAND_VERBS)
    def test_bad_command_verbs_are_rejected(self, bad):
        assert validate_lint_table({"command_verbs": bad}) == (
            "[lint].command_verbs must be a list of non-empty alphabetic words, "
            f"got {bad!r}."
        )

    @pytest.mark.parametrize("good", [[], ["adjust", "Void"]])
    def test_good_command_verbs_are_accepted(self, good):
        assert validate_lint_table({"command_verbs": good}) is None


class TestDomainCheckRaisesOnBadLintOption:
    @pytest.mark.parametrize("bad", BAD_COMMAND_VERBS)
    def test_bad_command_verbs_raise_from_check(self, bad):
        domain = Domain(name="CheckBadCommandVerbs", root_path=".")
        domain.config["lint"] = {"command_verbs": bad}

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        with pytest.raises(
            ConfigurationError,
            match=r"\[lint\]\.command_verbs must be a list of non-empty alphabetic",
        ):
            domain.check(traverse=False)

    def test_bad_option_raises_from_check(self):
        domain = Domain(name="CheckBadLintOption", root_path=".")
        domain.config["lint"] = {"aggregate_size_limit": "0"}

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        with pytest.raises(
            ConfigurationError,
            match=r"\[lint\]\.aggregate_size_limit must be a non-negative integer",
        ):
            domain.check(traverse=False)

    def test_bad_option_raises_when_validation_errors_skip_the_ir_build(self):
        domain = Domain(name="CheckBadLintWithErrors", root_path=".")
        domain.config["identity_strategy"] = "function"
        domain.config["lint"] = {"suppressions": {"UNHANDLED_EVENT": "x"}}

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        with pytest.raises(
            ConfigurationError,
            match=r"\[lint\]\.suppressions\.UNHANDLED_EVENT must be a non-negative",
        ):
            domain.check(traverse=False)

    def test_other_ir_build_failure_is_reported_as_an_error(self, monkeypatch):
        domain = Domain(name="CheckIRBuildFails", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        def _fail() -> dict:
            raise RuntimeError("IR build failed")

        monkeypatch.setattr(domain, "to_ir", _fail)

        result = domain.check(traverse=False)

        assert result["status"] == "fail"
        assert result["diagnostics"] == []
        assert result["errors"] == [
            {
                "code": "RuntimeError",
                "element": "to_ir",
                "level": "error",
                "message": "Could not build the IR: RuntimeError: IR build failed",
            }
        ]
