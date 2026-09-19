"""Unit tests for the sidecar spec: reading it and discovering scorable tasks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.eval.spec import SPEC_FILE, TaskSpec, list_task_specs, read_spec
from tests.eval.transcript import TASK_FILE, TASKS_DIRNAME

pytestmark = pytest.mark.no_test_domain


def _make_task(
    root: Path, task_id: str, *, task: bool = True, spec: dict | None
) -> None:
    """Lay out a task directory under *root* with an optional task.md/spec.json."""
    task_dir = root / TASKS_DIRNAME / task_id
    task_dir.mkdir(parents=True)
    if task:
        (task_dir / TASK_FILE).write_text("do the thing\n", encoding="utf-8")
    if spec is not None:
        (task_dir / SPEC_FILE).write_text(json.dumps(spec), encoding="utf-8")


class TestReadSpec:
    def test_reads_the_committed_place_order_spec(self) -> None:
        spec = read_spec("place_order")
        assert spec == TaskSpec(
            task_id="place_order", project_name="place_order", aggregates=("Order",)
        )

    def test_missing_project_name_is_an_error(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t", spec={"aggregates": ["Order"]})
        with pytest.raises(ValueError, match="no project_name"):
            read_spec("t", root=tmp_path)

    def test_no_aggregates_is_an_error(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t", spec={"project_name": "t"})
        with pytest.raises(ValueError, match="no aggregates"):
            read_spec("t", root=tmp_path)

    def test_a_task_with_no_spec_file_raises_file_not_found(
        self, tmp_path: Path
    ) -> None:
        """A task carrying no ``spec.json`` is a read error, not a silent empty
        build."""
        _make_task(tmp_path, "t", spec=None)
        with pytest.raises(FileNotFoundError):
            read_spec("t", root=tmp_path)

    def test_reads_the_committed_order_and_payment_nested_spec(self) -> None:
        """A multi-context spec's ``contexts`` object flattens to the aggregate
        list the gold builder reads, and keeps the declared grouping."""
        spec = read_spec("order_and_payment")
        assert spec.project_name == "order_and_payment"
        assert spec.aggregates == ("Order", "Payment")
        assert spec.contexts == (("order", ("Order",)), ("payment", ("Payment",)))

    def test_a_nested_contexts_spec_flattens_in_declaration_order(
        self, tmp_path: Path
    ) -> None:
        """A context holding two aggregates flattens both, in order, and a flat
        spec leaves ``contexts`` empty (one default context)."""
        _make_task(
            tmp_path,
            "nested",
            spec={
                "project_name": "shop",
                "contexts": {"sales": ["Order", "Cart"], "billing": ["Invoice"]},
            },
        )
        spec = read_spec("nested", root=tmp_path)
        assert spec.aggregates == ("Order", "Cart", "Invoice")
        assert spec.contexts == (
            ("sales", ("Order", "Cart")),
            ("billing", ("Invoice",)),
        )

    def test_a_non_object_contexts_field_is_an_error(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "bad", spec={"project_name": "p", "contexts": ["Order"]})
        with pytest.raises(ValueError, match="non-object contexts"):
            read_spec("bad", root=tmp_path)

    def test_an_empty_contexts_object_falls_back_to_no_aggregates(
        self, tmp_path: Path
    ) -> None:
        """An empty ``contexts`` names no aggregate and no flat list backs it, so
        it fails the same way a spec with no aggregates does."""
        _make_task(tmp_path, "empty", spec={"project_name": "p", "contexts": {}})
        with pytest.raises(ValueError, match="no aggregates"):
            read_spec("empty", root=tmp_path)

    def test_malformed_spec_json_raises(self, tmp_path: Path) -> None:
        """A spec that is not valid JSON surfaces the decode error rather than
        scoring a broken task."""
        task_dir = tmp_path / TASKS_DIRNAME / "t"
        task_dir.mkdir(parents=True)
        (task_dir / TASK_FILE).write_text("do the thing\n", encoding="utf-8")
        (task_dir / SPEC_FILE).write_text("{not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            read_spec("t", root=tmp_path)


class TestListTaskSpecs:
    def test_committed_place_order_is_discovered_from_its_files(self) -> None:
        """AC2: the task is declarative. The discovery finds ``place_order`` from
        its ``task.md`` + ``spec.json`` alone, so adding a task is adding those
        two files with no harness edit."""
        assert "place_order" in list_task_specs()

    def test_a_task_missing_its_spec_is_skipped(self, tmp_path: Path) -> None:
        _make_task(
            tmp_path, "with_spec", spec={"project_name": "p", "aggregates": ["A"]}
        )
        _make_task(tmp_path, "no_spec", spec=None)
        assert list_task_specs(root=tmp_path) == ["with_spec"]

    def test_a_spec_without_a_task_prompt_is_skipped(self, tmp_path: Path) -> None:
        _make_task(
            tmp_path,
            "no_prompt",
            task=False,
            spec={"project_name": "p", "aggregates": ["A"]},
        )
        assert list_task_specs(root=tmp_path) == []
