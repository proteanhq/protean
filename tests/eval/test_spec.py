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
        """The contexts flatten to one aggregate list, in declaration order, and
        a multi-word aggregate's context is its snake_case slug."""
        _make_task(
            tmp_path,
            "nested",
            spec={
                "project_name": "shop",
                "contexts": {"order": ["Order"], "order_item": ["OrderItem"]},
            },
        )
        spec = read_spec("nested", root=tmp_path)
        assert spec.aggregates == ("Order", "OrderItem")
        assert spec.contexts == (
            ("order", ("Order",)),
            ("order_item", ("OrderItem",)),
        )

    def test_aggregate_aliases_are_read_back_as_scaffold_class_names(
        self, tmp_path: Path
    ) -> None:
        """``protean add aggregate order_item`` builds the class ``OrderItem``,
        so the spec stores ``OrderItem``. Keeping the alias would leave the
        scorer with no declared context for the ``OrderItem`` the gold IR
        carries, and it would score the task's layout as matching whatever the
        produced project did."""
        _make_task(
            tmp_path,
            "aliases",
            spec={
                "project_name": "p",
                "contexts": {"order": ["order"], "order_item": ["orderItem"]},
            },
        )
        spec = read_spec("aliases", root=tmp_path)
        assert spec.aggregates == ("Order", "OrderItem")
        assert spec.contexts == (
            ("order", ("Order",)),
            ("order_item", ("OrderItem",)),
        )

    def test_a_flat_aggregate_alias_is_normalized_too(self, tmp_path: Path) -> None:
        """The flat form normalizes the same way, so both spec forms name the
        classes the gold project will carry."""
        _make_task(
            tmp_path, "flat", spec={"project_name": "p", "aggregates": ["orderItem"]}
        )
        assert read_spec("flat", root=tmp_path).aggregates == ("OrderItem",)

    @pytest.mark.parametrize("contexts", [["Order"], "", 0, False, None])
    def test_a_non_object_contexts_field_is_an_error(
        self, tmp_path: Path, contexts: object
    ) -> None:
        """A supplied ``contexts`` that is not an object is malformed, including
        the falsey values that would otherwise read as an absent field. ``None``
        is the JSON ``null`` case: the key is there, so the spec supplied a
        contexts value, and it is not an object."""
        _make_task(tmp_path, "bad", spec={"project_name": "p", "contexts": contexts})
        with pytest.raises(ValueError, match="non-object contexts"):
            read_spec("bad", root=tmp_path)

    def test_a_null_contexts_does_not_fall_back_to_the_flat_list(
        self, tmp_path: Path
    ) -> None:
        """A spec writing ``"contexts": null`` alongside a flat ``aggregates``
        list is malformed, not a flat spec: reading it as an absent field would
        build a gold the spec never declared."""
        _make_task(
            tmp_path,
            "bad",
            spec={"project_name": "p", "contexts": None, "aggregates": ["Order"]},
        )
        with pytest.raises(ValueError, match="non-object contexts"):
            read_spec("bad", root=tmp_path)

    @pytest.mark.parametrize("members", ["Order", ["Order", ""], [1], {"a": "b"}])
    def test_a_context_that_does_not_name_a_list_of_names_is_an_error(
        self, tmp_path: Path, members: object
    ) -> None:
        """A bare string would iterate into one-character aggregate names, and an
        empty or non-string member names no aggregate at all. Both are read
        errors, not a gold built from nonsense."""
        _make_task(
            tmp_path, "bad", spec={"project_name": "p", "contexts": {"order": members}}
        )
        with pytest.raises(ValueError, match="must name a list of aggregate names"):
            read_spec("bad", root=tmp_path)

    def test_a_context_the_gold_would_split_in_two_is_an_error(
        self, tmp_path: Path
    ) -> None:
        """``protean add aggregate`` puts each aggregate in its own slice module,
        so a context naming two aggregates is a grouping the gold cannot build.
        It fails at read time rather than scaffolding a project whose contexts
        are not the declared ones."""
        _make_task(
            tmp_path,
            "bad",
            spec={"project_name": "p", "contexts": {"sales": ["Order", "Cart"]}},
        )
        with pytest.raises(ValueError, match="the gold builds as order, cart"):
            read_spec("bad", root=tmp_path)

    def test_a_context_named_other_than_its_aggregate_slug_is_an_error(
        self, tmp_path: Path
    ) -> None:
        """The gold builds ``Order`` into the ``order`` module, so a context
        calling it ``orders`` declares a context the gold never produces."""
        _make_task(
            tmp_path,
            "bad",
            spec={"project_name": "p", "contexts": {"orders": ["Order"]}},
        )
        with pytest.raises(ValueError, match="the gold builds as order"):
            read_spec("bad", root=tmp_path)

    def test_a_context_is_checked_against_the_class_slug_not_the_raw_name(
        self, tmp_path: Path
    ) -> None:
        """``aB`` slugs to ``a_b`` on its own, but the class it emits, ``AB``,
        slugs to ``ab``. The gold scaffolds from the class name, so
        ``{"a_b": ["aB"]}`` would build the context ``ab`` and the gold would
        miss its own declared context."""
        _make_task(
            tmp_path,
            "bad",
            spec={"project_name": "p", "contexts": {"a_b": ["aB"]}},
        )
        with pytest.raises(ValueError, match="the gold builds as ab"):
            read_spec("bad", root=tmp_path)

    def test_naming_both_contexts_and_aggregates_is_an_error(
        self, tmp_path: Path
    ) -> None:
        """The two are alternative forms of the same list. Reading the contexts
        and ignoring the flat list would silently drop ``Order`` from the gold
        and change the score with no error."""
        _make_task(
            tmp_path,
            "bad",
            spec={
                "project_name": "p",
                "aggregates": ["Order"],
                "contexts": {"payment": ["Payment"]},
            },
        )
        with pytest.raises(ValueError, match="names both contexts and aggregates"):
            read_spec("bad", root=tmp_path)

    def test_a_context_naming_no_aggregate_is_an_error(self, tmp_path: Path) -> None:
        _make_task(
            tmp_path, "bad", spec={"project_name": "p", "contexts": {"order": []}}
        )
        with pytest.raises(ValueError, match="the gold builds as nothing"):
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
