"""Unit tests for the MCP tool functions in :mod:`protean.mcp.tools`.

These are the plain functions the server wraps; they answer from the installed
framework and import no MCP SDK. The tests point them at a real fixture domain
and a scaffolded temp project, so they exercise the same paths the server does.
"""

from pathlib import Path

import pytest

from protean.mcp import tools
from tests.shared import module_unavailable

# A clean domain that passes every check (the one `protean check` tests use).
CLEAN_DOMAIN = "tests/support/domains/test19/domain19.py:domain"


def _write_project(root: Path, package: str = "myproj") -> Path:
    """Lay down the minimum of a canonical project: ``src/<package>/domain.py``
    plus an empty ``shared/`` sibling. Returns the project root."""
    package_dir = root / "src" / package
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "domain.py").write_text(
        f'from protean.domain import Domain\n\ndomain = Domain(name="{package}")\n',
        encoding="utf-8",
    )
    shared = package_dir / "shared"
    shared.mkdir()
    (shared / "__init__.py").write_text("", encoding="utf-8")
    return root


@pytest.mark.no_test_domain
class TestReadTools:
    def test_check_returns_the_full_report(self):
        report = tools.check(CLEAN_DOMAIN)
        assert set(report) == {"domain", "status", "errors", "diagnostics", "counts"}
        assert report["status"] == "pass"
        assert report["errors"] == []

    def test_validate_reports_a_clean_domain_valid(self):
        result = tools.validate(CLEAN_DOMAIN)
        assert result["valid"] is True
        assert result["status"] == "pass"
        assert result["errors"] == []
        assert result["counts"]["errors"] == 0

    def test_introspect_returns_the_ir(self):
        ir = tools.introspect(CLEAN_DOMAIN)
        # The IR carries the domain topology; these keys are its stable shape.
        for key in ("domain", "elements", "ir_version"):
            assert key in ir

    def test_a_missing_domain_raises_a_clean_error(self):
        with pytest.raises(tools.McpToolError, match="Error loading Protean domain"):
            tools.check("tests/support/domains/does_not_exist.py:domain")

    def test_a_broken_domain_module_surfaces_as_a_clean_error(self, tmp_path):
        # A domain module with a syntax error raises SyntaxError (not
        # NoDomainException) while importing; it must still reach the caller as a
        # clean McpToolError, not a hidden server crash.
        bad = tmp_path / "bad_domain.py"
        bad.write_text("this is ! not valid python\n", encoding="utf-8")

        with pytest.raises(tools.McpToolError, match="Error loading Protean domain"):
            tools.check(str(bad))

    def test_check_defaults_to_a_domain_in_the_working_directory(
        self, tmp_path, monkeypatch
    ):
        # With no `domain`, the tool discovers a domain from the working directory,
        # the same "." default `protean check` uses.
        (tmp_path / "domain.py").write_text(
            'from protean.domain import Domain\n\ndomain = Domain(name="CWDDOMAIN")\n',
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)

        assert tools.check()["domain"] == "CWDDOMAIN"

    def test_check_translates_a_prepare_failure(self, monkeypatch):
        # `check` prepares the domain (importing the rest of its package); a
        # failure there must surface as a clean McpToolError.
        def boom(self, *args, **kwargs):
            raise RuntimeError("prepare blew up")

        monkeypatch.setattr("protean.domain.Domain.check", boom)

        with pytest.raises(tools.McpToolError, match="Error checking Protean domain"):
            tools.check(CLEAN_DOMAIN)

    def test_introspect_translates_an_init_failure(self, monkeypatch):
        def boom(self, *args, **kwargs):
            raise RuntimeError("init blew up")

        monkeypatch.setattr("protean.domain.Domain.init", boom)

        with pytest.raises(
            tools.McpToolError, match="Error initialising Protean domain"
        ):
            tools.introspect(CLEAN_DOMAIN)

    def test_introspect_translates_a_to_ir_failure(self, monkeypatch):
        def boom(self, *args, **kwargs):
            raise RuntimeError("ir build blew up")

        monkeypatch.setattr("protean.domain.Domain.to_ir", boom)

        with pytest.raises(
            tools.McpToolError, match="Error introspecting Protean domain"
        ):
            tools.introspect(CLEAN_DOMAIN)


class TestExplain:
    def test_explains_a_known_code(self):
        result = tools.explain("UNHANDLED_EVENT")
        assert result["code"] == "UNHANDLED_EVENT"
        assert result["category"]
        assert result["level"]
        assert result["meaning"]
        assert result["rationale"]
        assert result["fix"]
        assert result["kind"] in {"lint", "raise", "staleness"}
        assert "resolution" in result

    def test_a_code_is_matched_case_insensitively(self):
        assert tools.explain("unhandled_event")["code"] == "UNHANDLED_EVENT"

    def test_an_unknown_code_raises_with_suggestions(self):
        with pytest.raises(tools.McpToolError) as exc:
            tools.explain("UNHANDLED_EVEN")
        message = str(exc.value)
        assert "Unknown diagnostic code" in message
        assert "UNHANDLED_EVENT" in message  # the close-match suggestion

    def test_explains_a_code_that_carries_a_resolution(self):
        # A code whose failure a deterministic command clears returns that command
        # on the wire (command/args/display), not None.
        result = tools.explain("IR_STALE")
        assert result["resolution"] is not None
        assert result["resolution"]["command"]
        assert result["resolution"]["display"]

    def test_explain_needs_no_mcp_sdk(self):
        # The tool logic answers from the framework alone; the SDK is only the
        # transport. Prove it by explaining a code with `mcp` uninstalled.
        with module_unavailable("mcp"):
            result = tools.explain("UNHANDLED_EVENT")
        assert result["code"] == "UNHANDLED_EVENT"


class TestScaffold:
    def test_preview_writes_nothing(self, tmp_path):
        project = _write_project(tmp_path / "proj")

        result = tools.scaffold("aggregate", "Order", project=str(project))

        assert result["applied"] is False
        assert "written" not in result
        assert len(result["files"]) > 0
        assert result["preview"]
        assert result["plan"]["operations"]
        # The slice directory must not exist: preview touches nothing.
        assert not (project / "src" / "myproj" / "order").exists()

    def test_preview_defaults_the_project_to_the_working_directory(
        self, tmp_path, monkeypatch
    ):
        project = _write_project(tmp_path / "proj")
        monkeypatch.chdir(project)

        result = tools.scaffold("aggregate", "Order")  # no `project` argument

        assert result["applied"] is False
        assert len(result["files"]) > 0

    def test_apply_writes_the_slice_on_consent(self, tmp_path):
        project = _write_project(tmp_path / "proj")

        result = tools.scaffold("aggregate", "Order", project=str(project), apply=True)

        assert result["applied"] is True
        assert len(result["written"]) > 0
        assert set(result["written"]) == set(result["files"])
        assert (project / "src" / "myproj" / "order").is_dir()

    def test_an_unsupported_element_raises(self, tmp_path):
        project = _write_project(tmp_path / "proj")

        with pytest.raises(tools.McpToolError, match="Unsupported element type"):
            tools.scaffold("widget", "Order", project=str(project))

    def test_apply_over_an_existing_slice_raises(self, tmp_path):
        # apply_plan is create-only, so re-applying the same slice hits files that
        # already exist. The ApplyError must surface as a clean McpToolError.
        project = _write_project(tmp_path / "proj")
        tools.scaffold("aggregate", "Order", project=str(project), apply=True)

        with pytest.raises(tools.McpToolError):
            tools.scaffold("aggregate", "Order", project=str(project), apply=True)
