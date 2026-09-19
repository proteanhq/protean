"""Unit tests for the eval harness: workspace, tools, the run loop, the
transcript format, verify discovery, and live-driver resolution."""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import pytest

from protean.dx.pack import PACK_VERSION, iter_skills
from tests.eval import tools as tools_module
from tests.eval.discovery import discover_domain_arg
from tests.eval.drivers import (
    LIVE_DRIVER_ENV_VAR,
    Conversation,
    LiveDriverError,
    ReplayDriver,
    resolve_live_driver,
)
from tests.eval.runner import (
    RunnerError,
    build_pack_prompt,
    record,
    replay,
    run,
)
from tests.eval.tools import (
    TOOL_SPECS,
    TOOLS,
    _summarize_verify,
    execute_tool_call,
    run_verify,
)
from tests.eval.transcript import (
    ToolCall,
    Transcript,
    Turn,
    list_transcripts,
    transcript_path,
    transcripts_dir,
)
from tests.eval.workspace import Workspace, WorkspaceError

pytestmark = pytest.mark.no_test_domain

# A complete, verify-green single-file slice: aggregate + invariant + command +
# command handler. Its one write path clears the command-handler warning.
GREEN_DOMAIN = """\
from protean import Domain, current_domain, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import String

domain = Domain(name="Store")


@domain.aggregate
class Order:
    customer_name = String(max_length=100, required=True)
    status = String(max_length=20, default="PLACED")

    @classmethod
    def place(cls, customer_name: str) -> "Order":
        return cls(customer_name=customer_name)

    @invariant.post
    def customer_name_is_present(self) -> None:
        if not self.customer_name:
            raise ValidationError({"customer_name": ["Customer name is required"]})


@domain.command(part_of=Order)
class PlaceOrder:
    customer_name = String(max_length=100, required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> None:
        order = Order.place(customer_name=command.customer_name)
        current_domain.repository_for(Order).add(order)
"""

# An aggregate with no command handler: check gates on the warning, so verify
# fails.
ANEMIC_DOMAIN = """\
from protean import Domain
from protean.fields import String

domain = Domain(name="Store")


@domain.aggregate
class Order:
    customer_name = String(max_length=100, required=True)
"""


class TestWorkspace:
    def test_write_tracks_and_read_round_trips(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        relpath = workspace.write("pkg/domain.py", "x = 1\n")
        assert relpath == "pkg/domain.py"
        assert workspace.read("pkg/domain.py") == "x = 1\n"

    def test_read_missing_file_raises(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        with pytest.raises(WorkspaceError):
            workspace.read("missing.py")

    def test_read_binary_file_raises(self, tmp_path: Path) -> None:
        """A non-UTF-8 byproduct (a .pyc, say) is a WorkspaceError, not an
        uncaught UnicodeDecodeError."""
        workspace = Workspace(tmp_path)
        (tmp_path / "blob.pyc").write_bytes(b"\x00\x01\xfe\xff")
        with pytest.raises(WorkspaceError):
            workspace.read("blob.pyc")

    def test_list_dir_marks_directories(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        workspace.write("src/pkg/domain.py", "")
        workspace.write("README.md", "")
        assert workspace.list_dir(".") == ["README.md", "src/"]
        assert workspace.list_dir("src") == ["pkg/"]

    def test_list_dir_on_a_file_raises(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        workspace.write("domain.py", "")
        with pytest.raises(WorkspaceError):
            workspace.list_dir("domain.py")

    def test_absolute_path_is_rejected(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        with pytest.raises(WorkspaceError):
            workspace.write("/etc/passwd", "boom")

    def test_a_backslash_is_a_separator_not_a_filename(self, tmp_path: Path) -> None:
        """A recorded Windows-style path lands the same nested file on every OS,
        so a transcript replays the same tree wherever it runs."""
        workspace = Workspace(tmp_path)
        assert workspace.write("src\\pkg\\domain.py", "x = 1\n") == "src/pkg/domain.py"
        assert (tmp_path / "src" / "pkg" / "domain.py").read_text() == "x = 1\n"
        assert workspace.read("src/pkg/domain.py") == "x = 1\n"

    @pytest.mark.parametrize("rel", ["C:/pkg/domain.py", "C:pkg", "\\\\host\\share\\x"])
    def test_a_windows_drive_or_unc_path_is_rejected(
        self, rel: str, tmp_path: Path
    ) -> None:
        """POSIX `Path` reads `C:/pkg` as an ordinary directory named `C:`;
        neither OS should accept it as a workspace-relative path."""
        workspace = Workspace(tmp_path)
        with pytest.raises(WorkspaceError, match="relative to the workspace"):
            workspace.write(rel, "boom")

    def test_traversal_escape_is_rejected(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        with pytest.raises(WorkspaceError):
            workspace.write("../escape.py", "boom")

    def test_writing_to_the_root_is_rejected(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        with pytest.raises(WorkspaceError):
            workspace.write(".", "boom")

    def test_missing_root_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(WorkspaceError):
            Workspace(tmp_path / "does-not-exist")

    def test_project_hash_is_stable_across_workspaces(self, tmp_path: Path) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        first = Workspace(tmp_path / "a")
        second = Workspace(tmp_path / "b")
        for workspace in (first, second):
            workspace.write("domain.py", "x = 1\n")
            workspace.write("pkg/__init__.py", "")
        assert first.project_hash() == second.project_hash()

    def test_project_hash_changes_with_content(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        workspace.write("domain.py", "x = 1\n")
        before = workspace.project_hash()
        workspace.write("domain.py", "x = 2\n")
        assert workspace.project_hash() != before

    def test_project_hash_ignores_untracked_files(self, tmp_path: Path) -> None:
        """Byproducts a tool drops on disk (a __pycache__, say) are not written
        through the workspace, so they do not move the hash."""
        workspace = Workspace(tmp_path)
        workspace.write("domain.py", "x = 1\n")
        tracked = workspace.project_hash()
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "junk.pyc").write_bytes(b"\x00\x01")
        assert workspace.project_hash() == tracked

    def test_project_hash_skips_a_symlinked_tracked_file(self, tmp_path: Path) -> None:
        """A tracked file swapped for a symlink (a generated test could point it
        at a host file) is skipped, so the hash never reflects outside data."""
        outside = tmp_path / "outside.txt"
        outside.write_text("host secret", encoding="utf-8")
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir()
        workspace = Workspace(ws_dir)
        workspace.write("keep.py", "x = 1\n")
        workspace.write("swapped.py", "y = 2\n")
        (ws_dir / "swapped.py").unlink()
        (ws_dir / "swapped.py").symlink_to(outside)

        survivor_dir = tmp_path / "only"
        survivor_dir.mkdir()
        survivor = Workspace(survivor_dir)
        survivor.write("keep.py", "x = 1\n")

        assert workspace.project_hash() == survivor.project_hash()

    def test_project_hash_skips_a_file_under_a_symlinked_directory(
        self, tmp_path: Path
    ) -> None:
        """A symlink anywhere in the path (here a tracked file's parent dir
        swapped for a symlink to an outside dir) must not pull in host data."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "keep.py").write_text("host secret\n", encoding="utf-8")
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir()
        workspace = Workspace(ws_dir)
        workspace.write("root.py", "x = 1\n")
        workspace.write("pkg/keep.py", "real\n")
        (ws_dir / "pkg" / "keep.py").unlink()
        (ws_dir / "pkg").rmdir()
        (ws_dir / "pkg").symlink_to(outside, target_is_directory=True)

        survivor_dir = tmp_path / "only"
        survivor_dir.mkdir()
        survivor = Workspace(survivor_dir)
        survivor.write("root.py", "x = 1\n")

        assert workspace.project_hash() == survivor.project_hash()

    def test_project_hash_skips_a_tracked_file_deleted_out_of_band(
        self, tmp_path: Path
    ) -> None:
        """A tracked file that vanishes is skipped, so the hash equals a
        workspace that only ever wrote the survivor."""
        workspace = Workspace(tmp_path)
        workspace.write("keep.py", "x = 1\n")
        workspace.write("gone.py", "y = 2\n")
        (tmp_path / "gone.py").unlink()

        (tmp_path / "only").mkdir()
        survivor = Workspace(tmp_path / "only")
        survivor.write("keep.py", "x = 1\n")

        assert workspace.project_hash() == survivor.project_hash()

    def test_root_is_resolved_in_place(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A relative root is resolved at construction, so path checks and the
        verify subprocess stay anchored to the same directory even after the
        process changes its working directory."""
        (tmp_path / "ws").mkdir()
        (tmp_path / "elsewhere").mkdir()
        monkeypatch.chdir(tmp_path)
        workspace = Workspace(Path("ws"))
        monkeypatch.chdir(tmp_path / "elsewhere")

        assert workspace.root == (tmp_path / "ws").resolve()
        workspace.write("domain.py", "x = 1\n")
        assert (tmp_path / "ws" / "domain.py").is_file()

    def test_the_written_set_takes_no_constructor_argument(
        self, tmp_path: Path
    ) -> None:
        """Only write() tracks a file, so the hash cannot be seeded with paths
        the workspace never wrote."""
        (tmp_path / "preexisting.py").write_text("x = 1\n", encoding="utf-8")
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with pytest.raises(TypeError):
            Workspace(tmp_path, {"preexisting.py"})  # type: ignore[call-arg]
        assert Workspace(tmp_path).project_hash() == Workspace(empty_dir).project_hash()


class TestTools:
    def test_write_then_read_via_tool_calls(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        wrote = execute_tool_call(
            workspace, ToolCall("write_file", {"path": "a.py", "content": "hi\n"})
        )
        assert wrote == {"ok": True, "path": "a.py"}
        read = execute_tool_call(workspace, ToolCall("read_file", {"path": "a.py"}))
        assert read == {"ok": True, "content": "hi\n"}

    def test_read_missing_file_is_feedback_not_a_crash(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        result = execute_tool_call(workspace, ToolCall("read_file", {"path": "no.py"}))
        assert result["ok"] is False
        assert "no.py" in result["error"]

    def test_write_to_a_bad_path_is_feedback_not_a_crash(self, tmp_path: Path) -> None:
        """A live model writing to an escaping path gets a correctable error,
        not a crashed run."""
        workspace = Workspace(tmp_path)
        result = execute_tool_call(
            workspace, ToolCall("write_file", {"path": "../escape.py", "content": "x"})
        )
        assert result["ok"] is False
        assert "escape" in result["error"] or "workspace" in result["error"]

    def test_non_string_path_is_feedback(self, tmp_path: Path) -> None:
        """A schema-invalid path type is a correctable error, not a crash."""
        workspace = Workspace(tmp_path)
        result = execute_tool_call(
            workspace, ToolCall("write_file", {"path": 1, "content": "x"})
        )
        assert result["ok"] is False
        assert "string" in result["error"]

    def test_non_string_content_is_feedback(self, tmp_path: Path) -> None:
        """A schema-invalid content type is a correctable error, not a crash."""
        workspace = Workspace(tmp_path)
        result = execute_tool_call(
            workspace, ToolCall("write_file", {"path": "a.py", "content": None})
        )
        assert result["ok"] is False
        assert "string" in result["error"]

    def test_nul_byte_in_path_is_feedback(self, tmp_path: Path) -> None:
        """A NUL byte in a path reaches the filesystem as a ValueError; it must
        come back as feedback, not crash the run."""
        workspace = Workspace(tmp_path)
        result = execute_tool_call(
            workspace, ToolCall("write_file", {"path": "a\x00b.py", "content": "x"})
        )
        assert result["ok"] is False
        assert "NUL" in result["error"]

    def test_reading_a_binary_file_is_feedback(self, tmp_path: Path) -> None:
        """A read_file on a non-UTF-8 byproduct comes back as feedback."""
        workspace = Workspace(tmp_path)
        (tmp_path / "blob.pyc").write_bytes(b"\x00\x01\xfe\xff")
        result = execute_tool_call(
            workspace, ToolCall("read_file", {"path": "blob.pyc"})
        )
        assert result["ok"] is False
        assert "UTF-8" in result["error"]

    def test_list_dir_on_a_file_is_feedback(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        workspace.write("domain.py", "")
        result = execute_tool_call(
            workspace, ToolCall("list_dir", {"path": "domain.py"})
        )
        assert result["ok"] is False
        assert "domain.py" in result["error"]

    def test_list_dir_defaults_to_root(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        workspace.write("domain.py", "")
        result = execute_tool_call(workspace, ToolCall("list_dir", {}))
        assert result == {"ok": True, "entries": ["domain.py"]}

    def test_run_verify_dispatch_uses_the_resolved_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The verify subprocess runs against the workspace's resolved root, so
        a relative root plus a later chdir cannot verify another directory."""
        (tmp_path / "ws").mkdir()
        (tmp_path / "elsewhere").mkdir()
        monkeypatch.chdir(tmp_path)
        workspace = Workspace(Path("ws"))
        monkeypatch.chdir(tmp_path / "elsewhere")

        seen: list[Path] = []

        def _fake_run_verify(root: Path | str) -> dict[str, object]:
            seen.append(Path(root))
            return {"ok": True, "verdict": "pass"}

        monkeypatch.setattr(tools_module, "run_verify", _fake_run_verify)
        execute_tool_call(workspace, ToolCall("run_verify", {}))

        assert seen == [(tmp_path / "ws").resolve()]

    def test_unknown_tool_is_feedback(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        result = execute_tool_call(workspace, ToolCall("delete_everything", {}))
        assert result["ok"] is False
        assert "unknown tool" in result["error"]

    def test_non_string_tool_name_is_feedback(self, tmp_path: Path) -> None:
        """An unhashable (non-string) tool name must not raise on the registry
        lookup; it comes back as feedback."""
        workspace = Workspace(tmp_path)
        result = execute_tool_call(workspace, ToolCall(["not", "a", "name"], {}))
        assert result["ok"] is False
        assert "tool name must be a string" in result["error"]

    def test_bad_arguments_are_feedback(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        # write_file needs content; omitting it must come back as a bad call.
        result = execute_tool_call(workspace, ToolCall("write_file", {"path": "a.py"}))
        assert result["ok"] is False
        assert "bad arguments" in result["error"]

    def test_an_unexpected_tool_error_propagates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A tool raising something other than a workspace error is a real bug,
        so it propagates rather than being mislabeled as feedback."""

        def _boom(workspace: Workspace) -> dict:
            raise ValueError("internal bug")

        monkeypatch.setitem(TOOLS, "boom", _boom)
        with pytest.raises(ValueError, match="internal bug"):
            execute_tool_call(Workspace(tmp_path), ToolCall("boom", {}))

    def test_tool_specs_cover_every_registered_tool(self) -> None:
        assert {spec["name"] for spec in TOOL_SPECS} == set(TOOLS)


class TestRunVerify:
    def test_green_project_passes(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        workspace.write("domain.py", GREEN_DOMAIN)
        result = execute_tool_call(workspace, ToolCall("run_verify", {}))
        assert result["ok"] is True
        assert result["verdict"] == "pass"
        assert result["codes"] == []

    def test_anemic_project_fails_with_the_command_handler_warning(
        self, tmp_path: Path
    ) -> None:
        workspace = Workspace(tmp_path)
        workspace.write("domain.py", ANEMIC_DOMAIN)
        result = execute_tool_call(workspace, ToolCall("run_verify", {}))
        assert result["ok"] is False
        assert result["verdict"] == "fail"
        assert "AGGREGATE_WITHOUT_COMMAND_HANDLER" in result["codes"]

    def test_src_layout_project_passes(self, tmp_path: Path) -> None:
        """A src-layout project is discovered by its path and verifies green,
        exercising the discovered `-d` argument end-to-end."""
        workspace = Workspace(tmp_path)
        workspace.write("src/store/domain.py", GREEN_DOMAIN)
        result = run_verify(workspace.root)
        assert result["verdict"] == "pass"

    def test_an_init_error_names_the_workspace_by_placeholder(
        self, tmp_path: Path
    ) -> None:
        """An init ``ImportError`` traceback quotes the domain module's full
        path. Recording verifies in a temporary directory and a replay verifies
        in another, so the absolute path has to be scrubbed or the same turns
        would report a divergence."""
        workspace = Workspace(tmp_path)
        workspace.write("domain.py", "import nosuchmodule_for_the_eval_harness\n")

        result = run_verify(workspace.root)

        assert result["verdict"] == "fail"
        joined = "\n".join(result["errors"])
        assert "nosuchmodule_for_the_eval_harness" in joined
        assert str(workspace.root) not in joined
        assert "<workspace>/domain.py" in joined

    def test_run_verify_accepts_a_path_string(self, tmp_path: Path) -> None:
        (tmp_path / "domain.py").write_text(GREEN_DOMAIN, encoding="utf-8")
        result = run_verify(str(tmp_path))
        assert result["verdict"] == "pass"

    def test_unparseable_output_is_a_failed_verdict(self) -> None:
        result = _summarize_verify("not json at all", exit_code=2)
        assert result["ok"] is False
        assert result["verdict"] == "fail"
        assert result["exit_code"] == 2
        assert "error" in result

    def test_unparseable_output_carries_a_stderr_tail(self) -> None:
        result = _summarize_verify("garbage", exit_code=3, stderr="Traceback\nBoom!")
        assert result["ok"] is False
        assert "Boom!" in result["error"]

    def test_non_object_json_is_a_failed_verdict(self) -> None:
        """No JSON object in the output is a failed verdict."""
        for payload in ("[1, 2, 3]", "null", '"a string"', "no json here"):
            result = _summarize_verify(payload, exit_code=0)
            assert result["ok"] is False
            assert result["verdict"] == "fail"
            assert "error" in result

    def test_a_pass_verdict_with_a_nonzero_exit_is_a_fail(self) -> None:
        """A fabricated or truncated envelope claiming pass alongside a non-zero
        exit is not trusted."""
        payload = '{"data": {"verdict": "pass", "stages": {"check": {}}}}'
        result = _summarize_verify(payload, exit_code=5)
        assert result["ok"] is False
        assert result["verdict"] == "fail"

    def test_envelope_is_decoded_amid_stray_stdout(self) -> None:
        """A generated domain may print during import; the envelope is still
        decoded from the surrounding output."""
        envelope = (
            '{"data": {"verdict": "pass", "stages": {'
            '"init": {"status": "pass"}, '
            '"check": {"status": "pass", "counts": {"errors": 0, "warnings": 0, "infos": 0}, "diagnostics": []}, '
            '"tests": {"status": "pass"}}}}'
        )
        result = _summarize_verify(
            f"initializing widgets...\n{envelope}\n", exit_code=0
        )
        assert result["ok"] is True
        assert result["verdict"] == "pass"

    def test_a_missing_stage_is_not_a_pass(self) -> None:
        """A pass is derived from the stage tree; an envelope claiming pass with
        a stage missing (or not itself pass) is a fail even at exit 0."""
        payload = (
            '{"data": {"verdict": "pass", "stages": {'
            '"init": {"status": "pass"}, "check": {"status": "pass"}}}}'
        )
        result = _summarize_verify(payload, exit_code=0)
        assert result["ok"] is False
        assert result["verdict"] == "fail"

    def test_init_and_test_stage_failures_are_surfaced(self) -> None:
        """An init import error or a failing test suite is the actionable
        feedback run_verify must hand back."""
        payload = (
            '{"data": {"verdict": "fail", "stages": {'
            '"init": {"status": "fail", "error": "cannot import name Widget"}, '
            '"check": {"status": "pass"}, '
            '"tests": {"status": "fail", "returncode": 1, "failed": 2}}}}'
        )
        result = _summarize_verify(payload, exit_code=3)
        assert result["verdict"] == "fail"
        assert any("import name Widget" in msg for msg in result["errors"])
        assert any("tests failed" in msg for msg in result["errors"])

    def test_the_trailing_envelope_wins_over_an_earlier_one(self) -> None:
        """verify prints its envelope last; a stray JSON object printed earlier
        (e.g. by a generated module) must not be taken as the verdict."""
        fake = '{"data": {"verdict": "pass"}}'
        real = (
            '{"data": {"verdict": "fail", "stages": {"check": {"counts": '
            '{"errors": 1, "warnings": 0, "infos": 0}, "diagnostics": []}}}}'
        )
        result = _summarize_verify(f"{fake}\n{real}\n", exit_code=4)
        assert result["verdict"] == "fail"

    def test_check_errors_are_surfaced(self) -> None:
        """A config or fatal check error carries no diagnostic; its code and
        message must still reach the agent."""
        payload = (
            '{"data": {"verdict": "fail", "stages": {"check": {"errors": '
            '[{"code": "INVALID_LINT_CONFIG", "message": "[lint].level is invalid"}], '
            '"diagnostics": []}}}}'
        )
        result = _summarize_verify(payload, exit_code=4)
        assert result["verdict"] == "fail"
        assert "INVALID_LINT_CONFIG" in result["codes"]
        assert any("lint" in msg for msg in result["errors"])

    def test_a_timeout_fails_and_kills_the_process_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hung verify times out to a failed verdict and its process group is
        killed, so the nested pytest cannot outlive the call."""
        killed: dict[str, int] = {}

        class _FakePopen:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.pid = 4242
                self.returncode: int | None = None
                self._calls = 0

            def communicate(self, timeout: float | None = None) -> tuple[str, str]:
                self._calls += 1
                if self._calls == 1:
                    raise subprocess.TimeoutExpired(cmd="verify", timeout=timeout)
                return ("", "")

        monkeypatch.setattr(tools_module.subprocess, "Popen", _FakePopen)
        monkeypatch.setattr(tools_module.os, "getpgid", lambda pid: pid)
        monkeypatch.setattr(
            tools_module.os,
            "killpg",
            lambda pgid, sig: killed.__setitem__("pgid", pgid),
        )
        (tmp_path / "domain.py").write_text(GREEN_DOMAIN, encoding="utf-8")

        result = run_verify(tmp_path)

        assert result["ok"] is False
        assert result["verdict"] == "fail"
        assert "timed out" in result["error"]
        assert killed["pgid"] == 4242

    def test_a_timeout_still_fails_when_the_kill_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A kill that cannot land (the tree exited between the timeout and the
        signal, or the OS refuses it) must not lose the timeout's failed
        verdict, and the process is still reaped."""
        reaped: list[bool] = []

        class _FakePopen:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.pid = 4242
                self.returncode: int | None = None
                self._calls = 0

            def communicate(self, timeout: float | None = None) -> tuple[str, str]:
                self._calls += 1
                if self._calls == 1:
                    raise subprocess.TimeoutExpired(cmd="verify", timeout=timeout)
                reaped.append(True)
                return ("", "")

            def kill(self) -> None:
                raise PermissionError("not permitted")

        monkeypatch.setattr(tools_module.subprocess, "Popen", _FakePopen)
        monkeypatch.setattr(tools_module.os, "getpgid", lambda pid: pid)

        def _killpg(pgid: int, sig: int) -> None:
            raise ProcessLookupError("no such process group")

        monkeypatch.setattr(tools_module.os, "killpg", _killpg)
        (tmp_path / "domain.py").write_text(GREEN_DOMAIN, encoding="utf-8")

        result = run_verify(tmp_path)

        assert result["verdict"] == "fail"
        assert "timed out" in result["error"]
        assert reaped == [True]


class TestDomainDiscovery:
    def test_root_domain_uses_default_discovery(self, tmp_path: Path) -> None:
        (tmp_path / "domain.py").write_text(
            "from protean import Domain\n", encoding="utf-8"
        )
        assert discover_domain_arg(tmp_path) is None

    def test_src_layout_is_addressed_by_path(self, tmp_path: Path) -> None:
        package = tmp_path / "src" / "store"
        package.mkdir(parents=True)
        (package / "domain.py").write_text(
            "from protean import Domain\n\nstore = Domain(name='Store')\n",
            encoding="utf-8",
        )
        assert discover_domain_arg(tmp_path) == "src/store/domain.py"

    def test_no_domain_uses_default_discovery(self, tmp_path: Path) -> None:
        assert discover_domain_arg(tmp_path) is None

    def test_multiple_src_domains_use_default_discovery(self, tmp_path: Path) -> None:
        for name in ("store", "billing"):
            package = tmp_path / "src" / name
            package.mkdir(parents=True)
            (package / "domain.py").write_text(
                f"from protean import Domain\n\n{name} = Domain(name='{name}')\n",
                encoding="utf-8",
            )
        assert discover_domain_arg(tmp_path) is None


class TestRunLoop:
    def test_run_produces_files_and_stops(self, tmp_path: Path) -> None:
        turns = (
            Turn(
                "write it",
                (ToolCall("write_file", {"path": "domain.py", "content": "x = 1\n"}),),
            ),
            Turn("done", ()),
        )
        result = run("task", ReplayDriver(turns), workspace=Workspace(tmp_path))
        assert (tmp_path / "domain.py").read_text() == "x = 1\n"
        assert len(result.turns) == 2
        assert result.project_hash.startswith("sha256:")

    def test_run_stops_when_the_driver_returns_none(self, tmp_path: Path) -> None:
        """A transcript whose last turn still carries tool calls stops on the
        driver's terminating None, not on an empty-tool-calls final answer."""
        turns = (
            Turn(
                "write it",
                (ToolCall("write_file", {"path": "domain.py", "content": "x = 1\n"}),),
            ),
        )
        result = run("task", ReplayDriver(turns), workspace=Workspace(tmp_path))
        assert len(result.turns) == 1
        assert (tmp_path / "domain.py").read_text() == "x = 1\n"

    def test_run_feeds_tool_results_back_to_the_driver(self, tmp_path: Path) -> None:
        seen_roles: list[list[str]] = []
        captured: dict[str, object] = {}

        class RecordingDriver:
            def __init__(self) -> None:
                self.queue = [
                    Turn(
                        "write",
                        (ToolCall("write_file", {"path": "a.py", "content": "y\n"}),),
                    ),
                    Turn("stop", ()),
                ]

            def next_turn(self, conversation: Conversation) -> Turn | None:
                seen_roles.append([message.role for message in conversation.messages])
                if conversation.messages and conversation.messages[-1].role == "tool":
                    captured["last_tool_result"] = conversation.messages[
                        -1
                    ].tool_results
                if not self.queue:
                    return None
                return self.queue.pop(0)

        run("task", RecordingDriver(), workspace=Workspace(tmp_path))

        assert seen_roles[0] == ["user"]
        assert "tool" in seen_roles[1]
        assert captured["last_tool_result"] == ({"ok": True, "path": "a.py"},)

    def test_run_records_each_turns_tool_results(self, tmp_path: Path) -> None:
        """The returned turns carry what the tools returned, so a recording
        captures what the agent saw. A driver's own results do not count: the
        loop ran the tools."""
        turns = (
            Turn(
                "write then read",
                (
                    ToolCall("write_file", {"path": "a.py", "content": "y\n"}),
                    ToolCall("read_file", {"path": "a.py"}),
                ),
                tool_results=({"ok": False, "error": "a driver's fiction"},),
            ),
            Turn("done", ()),
        )
        result = run("task", ReplayDriver(turns), workspace=Workspace(tmp_path))
        assert result.turns[0].tool_results == (
            {"ok": True, "path": "a.py"},
            {"ok": True, "content": "y\n"},
        )
        assert result.turns[1].tool_results == ()

    def test_a_turn_may_carry_several_tool_calls(self, tmp_path: Path) -> None:
        turns = (
            Turn(
                "write two files and verify",
                (
                    ToolCall("write_file", {"path": "a.py", "content": "a = 1\n"}),
                    ToolCall("write_file", {"path": "b.py", "content": "b = 2\n"}),
                    ToolCall("read_file", {"path": "a.py"}),
                ),
            ),
            Turn("done", ()),
        )
        run("task", ReplayDriver(turns), workspace=Workspace(tmp_path))
        assert (tmp_path / "a.py").exists()
        assert (tmp_path / "b.py").exists()

    def test_run_raises_when_the_driver_never_stops(self, tmp_path: Path) -> None:
        class NeverStops:
            def next_turn(self, conversation: Conversation) -> Turn:
                return Turn("again", (ToolCall("list_dir", {}),))

        with pytest.raises(RunnerError):
            run("task", NeverStops(), workspace=Workspace(tmp_path), max_turns=3)

    def test_run_records_verify_results_in_order(self, tmp_path: Path) -> None:
        """The natural agent loop verifies, fixes, verifies again; the recorded
        results keep that order so the last one is the final verdict."""
        turns = (
            Turn(
                "first cut",
                (
                    ToolCall(
                        "write_file", {"path": "domain.py", "content": ANEMIC_DOMAIN}
                    ),
                ),
            ),
            Turn("check", (ToolCall("run_verify", {}),)),
            Turn(
                "fix it",
                (
                    ToolCall(
                        "write_file", {"path": "domain.py", "content": GREEN_DOMAIN}
                    ),
                ),
            ),
            Turn("check again", (ToolCall("run_verify", {}),)),
            Turn("done", ()),
        )
        result = run("task", ReplayDriver(turns), workspace=Workspace(tmp_path))
        assert len(result.verify_results) == 2
        assert result.verify_results[0]["verdict"] == "fail"
        assert result.verify_results[-1]["verdict"] == "pass"


class TestTranscriptFormat:
    def test_round_trips_through_json(self) -> None:
        transcript = Transcript(
            pack_version="9.9.9",
            task_id="demo",
            task_input="do a thing",
            turns=(
                Turn(
                    "hello", (ToolCall("write_file", {"path": "a.py", "content": "x"}),)
                ),
                Turn("bye", ()),
            ),
            project_hash="sha256:abc",
        )
        assert Transcript.loads(transcript.dumps()) == transcript

    def test_tool_results_round_trip(self) -> None:
        """The recorded results survive serialization; they are the second
        staleness signal, so losing them on save would lose the signal."""
        turn = Turn(
            "verify",
            (ToolCall("run_verify", {}),),
            tool_results=({"ok": True, "verdict": "pass", "codes": []},),
        )
        transcript = Transcript("9.9.9", "demo", "in", (turn,), "sha256:abc")
        assert Transcript.loads(transcript.dumps()) == transcript

    def test_dumps_is_canonical(self) -> None:
        """Sorted keys, two-space indent, trailing newline, so a re-recorded
        transcript diffs cleanly."""
        transcript = Transcript("1.0.0", "demo", "in", (Turn("t"),), "sha256:z")
        text = transcript.dumps()
        assert text.endswith("\n")
        assert '\n  "pack_version"' in text  # two-space indent, sorted first key

    def test_from_dict_tolerates_missing_optional_keys(self) -> None:
        turn = Turn.from_dict({"text": "no tools here"})
        assert turn.tool_calls == ()
        assert turn.tool_results == ()

    def test_save_writes_the_canonical_path(self, tmp_path: Path) -> None:
        transcript = Transcript("1.2.3", "demo", "in", (Turn("t"),), "sha256:z")
        written = transcript.save(tmp_path)
        assert written == transcript_path(tmp_path, "1.2.3", "demo")
        assert list_transcripts(tmp_path, "1.2.3") == [written]
        assert Transcript.load(written) == transcript

    def test_list_transcripts_is_empty_for_an_unknown_version(
        self, tmp_path: Path
    ) -> None:
        assert list_transcripts(tmp_path, "0.0.0") == []
        assert not transcripts_dir(tmp_path, "0.0.0").exists()


class TestRecordAndReplay:
    @staticmethod
    def _write_task(root: Path) -> tuple[Turn, ...]:
        task_dir = root / "tasks" / "demo"
        task_dir.mkdir(parents=True)
        (task_dir / "task.md").write_text("build a thing\n", encoding="utf-8")
        return (
            Turn(
                "write",
                (ToolCall("write_file", {"path": "domain.py", "content": "x = 1\n"}),),
            ),
            Turn("done", ()),
        )

    def test_record_captures_the_run_keyed_to_the_pack(self, tmp_path: Path) -> None:
        turns = self._write_task(tmp_path)

        transcript = record("demo", ReplayDriver(turns), root=tmp_path)

        assert transcript.pack_version == PACK_VERSION
        assert transcript.task_id == "demo"
        assert transcript.task_input == "build a thing\n"
        assert transcript.project_hash.startswith("sha256:")
        # The recorded turns are the driver's, with the results the tools
        # returned filled in.
        assert [turn.text for turn in transcript.turns] == ["write", "done"]
        assert transcript.turns[0].tool_calls == turns[0].tool_calls
        assert transcript.turns[0].tool_results == ({"ok": True, "path": "domain.py"},)

    def test_record_then_replay_lands_the_same_hash(self, tmp_path: Path) -> None:
        turns = self._write_task(tmp_path)
        transcript = record("demo", ReplayDriver(turns), root=tmp_path)

        (tmp_path / "replay").mkdir()
        result = replay(transcript, workspace=Workspace(tmp_path / "replay"))

        assert result.project_hash == transcript.project_hash
        assert result.result_divergences == ()

    def test_replay_flags_a_recorded_result_the_tools_no_longer_return(
        self, tmp_path: Path
    ) -> None:
        """The staleness signal the project hash cannot give: the hash covers
        only the files the agent wrote, so a tool that now answers differently
        has to be caught by comparing the recorded result."""
        turns = self._write_task(tmp_path)
        transcript = record("demo", ReplayDriver(turns), root=tmp_path)
        stale = dataclasses.replace(
            transcript,
            turns=(
                dataclasses.replace(
                    transcript.turns[0],
                    tool_results=({"ok": True, "path": "somewhere-else.py"},),
                ),
                *transcript.turns[1:],
            ),
        )

        (tmp_path / "replay").mkdir()
        result = replay(stale, workspace=Workspace(tmp_path / "replay"))

        # The project still lands: replay runs the recorded calls, not the
        # recorded results. Only the comparison catches it.
        assert result.project_hash == transcript.project_hash
        assert len(result.result_divergences) == 1
        assert "turn 0 call 0 (write_file)" in result.result_divergences[0]
        assert "somewhere-else.py" in result.result_divergences[0]

    def test_replay_flags_a_result_count_that_does_not_match(
        self, tmp_path: Path
    ) -> None:
        """A hand-edited transcript whose recorded results do not line up with
        its calls is stale too, and must not compare position by position."""
        turns = self._write_task(tmp_path)
        transcript = record("demo", ReplayDriver(turns), root=tmp_path)
        stale = dataclasses.replace(
            transcript,
            turns=(
                dataclasses.replace(
                    transcript.turns[0],
                    tool_results=({"ok": True}, {"ok": True}),
                ),
                *transcript.turns[1:],
            ),
        )

        (tmp_path / "replay").mkdir()
        result = replay(stale, workspace=Workspace(tmp_path / "replay"))

        assert result.result_divergences == (
            "turn 0: recorded 2 tool results, recomputed 1",
        )

    def test_replay_flags_recorded_turns_it_never_replayed(
        self, tmp_path: Path
    ) -> None:
        """A transcript carrying turns after a final answer never replays its
        tail: ``run`` stops at the final answer. When the tail is read-only, the
        project hash and the last replayed verify both still pass, so the turn
        count is the only thing left to catch it."""
        turns = self._write_task(tmp_path)
        transcript = record("demo", ReplayDriver(turns), root=tmp_path)
        stale = dataclasses.replace(
            transcript,
            turns=(
                *transcript.turns,
                Turn(
                    "a read the replay never reaches",
                    (ToolCall("read_file", {"path": "domain.py"}),),
                    ({"ok": True, "content": "x = 1\n"},),
                ),
            ),
        )

        (tmp_path / "replay").mkdir()
        result = replay(stale, workspace=Workspace(tmp_path / "replay"))

        assert result.project_hash == transcript.project_hash
        assert result.result_divergences == ("replayed 2 turns of the 3 recorded",)

    def test_replay_ignores_verify_error_text_it_cannot_reproduce(
        self, tmp_path: Path
    ) -> None:
        """A verify result's free-form text quotes paths from the machine that
        recorded it, so it is not a replay invariant; the structured fields
        are."""
        task_dir = tmp_path / "tasks" / "demo"
        task_dir.mkdir(parents=True)
        (task_dir / "task.md").write_text("build a thing\n", encoding="utf-8")
        turns = (
            Turn(
                "write and verify",
                (
                    ToolCall(
                        "write_file", {"path": "domain.py", "content": GREEN_DOMAIN}
                    ),
                    ToolCall("run_verify", {}),
                ),
            ),
        )
        transcript = record("demo", ReplayDriver(turns), root=tmp_path)
        recorded_verify = dict(transcript.turns[0].tool_results[1])
        assert recorded_verify["verdict"] == "pass"
        elsewhere = dataclasses.replace(
            transcript,
            turns=(
                dataclasses.replace(
                    transcript.turns[0],
                    tool_results=(
                        transcript.turns[0].tool_results[0],
                        {**recorded_verify, "errors": ["a traceback from elsewhere"]},
                    ),
                ),
            ),
        )

        (tmp_path / "replay").mkdir()
        result = replay(elsewhere, workspace=Workspace(tmp_path / "replay"))

        assert result.result_divergences == ()

    def test_replay_still_flags_a_changed_verify_verdict(self, tmp_path: Path) -> None:
        """Dropping the free-form text from the comparison keeps the verdict and
        the diagnostic codes in it."""
        task_dir = tmp_path / "tasks" / "demo"
        task_dir.mkdir(parents=True)
        (task_dir / "task.md").write_text("build a thing\n", encoding="utf-8")
        turns = (
            Turn(
                "write and verify",
                (
                    ToolCall(
                        "write_file", {"path": "domain.py", "content": GREEN_DOMAIN}
                    ),
                    ToolCall("run_verify", {}),
                ),
            ),
        )
        transcript = record("demo", ReplayDriver(turns), root=tmp_path)
        stale = dataclasses.replace(
            transcript,
            turns=(
                dataclasses.replace(
                    transcript.turns[0],
                    tool_results=(
                        transcript.turns[0].tool_results[0],
                        {
                            **transcript.turns[0].tool_results[1],
                            "codes": ["SOME_OLD_CODE"],
                        },
                    ),
                ),
            ),
        )

        (tmp_path / "replay").mkdir()
        result = replay(stale, workspace=Workspace(tmp_path / "replay"))

        assert len(result.result_divergences) == 1
        assert "SOME_OLD_CODE" in result.result_divergences[0]

    def test_replay_without_recorded_results_reports_no_divergence(
        self, tmp_path: Path
    ) -> None:
        """A transcript recorded before results were captured has nothing to
        compare, so it replays on the hash alone rather than failing."""
        turns = self._write_task(tmp_path)
        transcript = record("demo", ReplayDriver(turns), root=tmp_path)
        bare = dataclasses.replace(
            transcript,
            turns=tuple(
                dataclasses.replace(turn, tool_results=()) for turn in transcript.turns
            ),
        )

        (tmp_path / "replay").mkdir()
        result = replay(bare, workspace=Workspace(tmp_path / "replay"))

        assert result.project_hash == transcript.project_hash
        assert result.result_divergences == ()


class TestPackPrompt:
    def test_prompt_includes_agents_and_every_skill(self) -> None:
        prompt = build_pack_prompt()
        assert prompt.strip()
        skills = iter_skills()
        assert len(skills) > 0
        for skill in skills:
            assert f"# Skill: {skill}" in prompt


# Module-level factories so PROTEAN_EVAL_LIVE_DRIVER can name them as
# "tests.eval.test_runner:<factory>".
def make_fake_driver(system_prompt: str, tool_specs: list[dict]) -> ReplayDriver:
    return ReplayDriver((Turn("noop", ()),))


def make_bad_driver(system_prompt: str, tool_specs: list[dict]) -> str:
    return "not a driver"


class _NonCallableNextTurn:
    next_turn = 1  # present but not callable


def make_uncallable_driver(
    system_prompt: str, tool_specs: list[dict]
) -> _NonCallableNextTurn:
    return _NonCallableNextTurn()


# A module attribute that is not callable, so it cannot be a driver factory.
not_a_factory = 42


class TestLiveDriverResolution:
    def test_unset_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(LIVE_DRIVER_ENV_VAR, raising=False)
        assert resolve_live_driver("prompt", TOOL_SPECS) is None

    def test_malformed_spec_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(LIVE_DRIVER_ENV_VAR, "no-colon-here")
        with pytest.raises(LiveDriverError):
            resolve_live_driver("prompt", TOOL_SPECS)

    def test_valid_spec_builds_the_driver(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            LIVE_DRIVER_ENV_VAR, "tests.eval.test_runner:make_fake_driver"
        )
        driver = resolve_live_driver("prompt", TOOL_SPECS)
        assert driver is not None
        assert driver.next_turn(Conversation("prompt")) == Turn("noop", ())

    def test_a_factory_that_returns_a_non_driver_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            LIVE_DRIVER_ENV_VAR, "tests.eval.test_runner:make_bad_driver"
        )
        with pytest.raises(LiveDriverError):
            resolve_live_driver("prompt", TOOL_SPECS)

    def test_a_non_callable_next_turn_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            LIVE_DRIVER_ENV_VAR, "tests.eval.test_runner:make_uncallable_driver"
        )
        with pytest.raises(LiveDriverError):
            resolve_live_driver("prompt", TOOL_SPECS)

    def test_a_non_callable_factory_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(LIVE_DRIVER_ENV_VAR, "tests.eval.test_runner:not_a_factory")
        with pytest.raises(LiveDriverError):
            resolve_live_driver("prompt", TOOL_SPECS)

    def test_missing_attribute_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            LIVE_DRIVER_ENV_VAR, "tests.eval.test_runner:nonexistent_factory"
        )
        with pytest.raises(AttributeError):
            resolve_live_driver("prompt", TOOL_SPECS)

    def test_missing_module_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(LIVE_DRIVER_ENV_VAR, "tests.eval.no_such_module:make_driver")
        with pytest.raises(ModuleNotFoundError):
            resolve_live_driver("prompt", TOOL_SPECS)


def test_tools_module_exposes_the_expected_public_names() -> None:
    # Guards the run loop's dispatch surface against an accidental rename.
    assert set(TOOLS) == {"write_file", "read_file", "list_dir", "run_verify"}
    assert hasattr(tools_module, "execute_tool_call")
