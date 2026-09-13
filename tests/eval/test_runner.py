"""Unit tests for the eval harness: workspace, tools, the run loop, the
transcript format, verify discovery, and live-driver resolution."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from protean.dx.pack import PACK_VERSION
from tests.eval import tools as tools_module
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
    _discover_domain_arg,
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

    def test_unknown_tool_is_feedback(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        result = execute_tool_call(workspace, ToolCall("delete_everything", {}))
        assert result["ok"] is False
        assert "unknown tool" in result["error"]

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
        envelope = '{"data": {"verdict": "pass", "stages": {"check": {"counts": {"errors": 0, "warnings": 0, "infos": 0}, "diagnostics": []}}}}'
        result = _summarize_verify(
            f"initializing widgets...\n{envelope}\n", exit_code=0
        )
        assert result["ok"] is True
        assert result["verdict"] == "pass"

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

    def test_a_timeout_is_reported_as_a_failed_verdict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _timeout(*args: object, **kwargs: object) -> None:
            raise subprocess.TimeoutExpired(cmd="protean verify", timeout=1)

        monkeypatch.setattr(tools_module.subprocess, "run", _timeout)
        (tmp_path / "domain.py").write_text(GREEN_DOMAIN, encoding="utf-8")
        result = run_verify(tmp_path)
        assert result["ok"] is False
        assert result["verdict"] == "fail"
        assert "timed out" in result["error"]


class TestDomainDiscovery:
    def test_root_domain_uses_default_discovery(self, tmp_path: Path) -> None:
        (tmp_path / "domain.py").write_text(
            "from protean import Domain\n", encoding="utf-8"
        )
        assert _discover_domain_arg(tmp_path) is None

    def test_src_layout_is_addressed_by_path(self, tmp_path: Path) -> None:
        package = tmp_path / "src" / "store"
        package.mkdir(parents=True)
        (package / "domain.py").write_text(
            "from protean import Domain\n\nstore = Domain(name='Store')\n",
            encoding="utf-8",
        )
        assert _discover_domain_arg(tmp_path) == "src/store/domain.py"

    def test_no_domain_uses_default_discovery(self, tmp_path: Path) -> None:
        assert _discover_domain_arg(tmp_path) is None

    def test_multiple_src_domains_use_default_discovery(self, tmp_path: Path) -> None:
        for name in ("store", "billing"):
            package = tmp_path / "src" / name
            package.mkdir(parents=True)
            (package / "domain.py").write_text(
                f"from protean import Domain\n\n{name} = Domain(name='{name}')\n",
                encoding="utf-8",
            )
        assert _discover_domain_arg(tmp_path) is None


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
        assert transcript.turns == turns
        assert transcript.project_hash.startswith("sha256:")

    def test_record_then_replay_lands_the_same_hash(self, tmp_path: Path) -> None:
        turns = self._write_task(tmp_path)
        transcript = record("demo", ReplayDriver(turns), root=tmp_path)

        (tmp_path / "replay").mkdir()
        result = replay(transcript, workspace=Workspace(tmp_path / "replay"))

        assert result.project_hash == transcript.project_hash


class TestPackPrompt:
    def test_prompt_includes_agents_and_every_skill(self) -> None:
        from protean.dx.pack import iter_skills

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
