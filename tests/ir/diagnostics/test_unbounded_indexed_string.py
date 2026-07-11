"""Diagnostics: TestUnboundedIndexedString."""

from protean import Domain
from protean.core.index import Index
from protean.core.value_object import BaseValueObject
from protean.fields import ValueObject
from protean.fields.simple import Integer, String, Text
from protean.ir.builder import IRBuilder
from protean.utils import fqn


def _unbounded_findings(ir: dict) -> list[dict]:
    """Diagnostics with code ``UNBOUNDED_INDEXED_STRING``."""
    return [d for d in ir["diagnostics"] if d["code"] == "UNBOUNDED_INDEXED_STRING"]


class TestUnboundedIndexedString:
    """UNBOUNDED_INDEXED_STRING flags string fields that are both indexed and
    unbounded — the DDL is unportable across engines."""

    def test_indexed_text_field_flagged(self):
        domain = Domain(name="UnboundedText", root_path=".")

        @domain.aggregate(indexes=[Index("body")])
        class Note:
            body = Text()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _unbounded_findings(ir)
        assert len(findings) == 1, findings
        finding = findings[0]
        assert finding["field"] == "body"
        assert finding["element"] == fqn(Note)
        assert finding["category"] == "persistence"
        assert finding["level"] == "warning"
        # Message names the aggregate, the index, and the unbounded type.
        assert "Note" in finding["message"]
        assert "body" in finding["message"]
        assert "`Text`" in finding["message"]

    def test_indexed_string_max_length_none_flagged(self):
        """``String(max_length=None)`` is the residual unbounded ``String``
        path — the extractor emits no ``max_length`` key, so it fires."""
        domain = Domain(name="UnboundedStringNone", root_path=".")

        @domain.aggregate(indexes=[Index("code")])
        class Coupon:
            code = String(max_length=None)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _unbounded_findings(ir)
        assert len(findings) == 1, findings
        assert findings[0]["field"] == "code"
        assert "`String`" in findings[0]["message"]

    def test_composite_index_flags_only_unbounded_field(self):
        domain = Domain(name="Composite", root_path=".")

        @domain.aggregate(indexes=[Index("slug", "body")])
        class Article:
            slug = String(max_length=120)
            body = Text()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _unbounded_findings(ir)
        assert len(findings) == 1, findings
        assert findings[0]["field"] == "body"

    def test_same_field_in_two_indexes_yields_two_findings(self):
        """One finding per index occurrence, not deduped per field. Naming the
        two indexes distinctly proves each finding maps to its own index rather
        than one index being double-counted."""
        domain = Domain(name="TwoIndexes", root_path=".")

        @domain.aggregate(
            indexes=[
                Index("body", name="ix_post_body"),
                Index("body", "created_at", name="ix_post_body_created"),
            ]
        )
        class Post:
            body = Text()
            created_at = String(max_length=40)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _unbounded_findings(ir)
        assert len(findings) == 2, findings
        assert all(f["field"] == "body" for f in findings)
        # Each declared index is attributed exactly once (not one index twice).
        messages = " ".join(f["message"] for f in findings)
        assert "`ix_post_body`" in messages
        assert "`ix_post_body_created`" in messages

    def test_repeated_field_in_one_index_yields_single_finding(self):
        """A field named twice in the *same* index is one occurrence — the
        rule dedupes within an index so a degenerate ``Index("body", "body")``
        does not double-count."""
        domain = Domain(name="RepeatedField", root_path=".")

        @domain.aggregate(indexes=[Index("body", "body")])
        class Note:
            body = Text()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _unbounded_findings(ir)
        assert len(findings) == 1, findings
        assert findings[0]["field"] == "body"

    def test_unnamed_index_renders_placeholder(self):
        domain = Domain(name="Unnamed", root_path=".")

        @domain.aggregate(indexes=[Index("body")])
        class Note:
            body = Text()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _unbounded_findings(ir)
        assert len(findings) == 1, findings
        assert "`(unnamed)`" in findings[0]["message"]

    def test_named_index_renders_its_name(self):
        domain = Domain(name="Named", root_path=".")

        @domain.aggregate(indexes=[Index("body", name="ix_note_body")])
        class Note:
            body = Text()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _unbounded_findings(ir)
        assert len(findings) == 1, findings
        assert "`ix_note_body`" in findings[0]["message"]

    def test_schema_conformance(self):
        """The finding carries the #774 schema surface: category, a non-empty
        rule, and a field-specific suggestion."""
        domain = Domain(name="Schema", root_path=".")

        @domain.aggregate(indexes=[Index("body")])
        class Note:
            body = Text()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        finding = _unbounded_findings(ir)[0]
        assert finding["category"] == "persistence"
        assert finding["rule"]["rationale"]
        assert finding["rule"]["fix"]
        assert "body" in finding["suggestion"]

    def test_suppress_checks_removes_finding(self):
        """Per-element ``suppress_checks`` resolves against the aggregate FQN
        in ``element``."""
        domain = Domain(name="Suppressed", root_path=".")

        @domain.aggregate(
            indexes=[Index("body")],
            suppress_checks=["UNBOUNDED_INDEXED_STRING"],
        )
        class Note:
            body = Text()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _unbounded_findings(ir) == []

    # ── Negative matrix — each asserts no finding and no exception ──

    def test_indexed_bounded_string_not_flagged(self):
        domain = Domain(name="Bounded", root_path=".")

        @domain.aggregate(indexes=[Index("slug")])
        class Article:
            slug = String(max_length=120)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _unbounded_findings(ir) == []

    def test_indexed_default_string_not_flagged(self):
        """Default ``String()`` carries ``max_length=255`` and must NOT fire —
        the regression guard against flagging every default string."""
        domain = Domain(name="DefaultString", root_path=".")

        @domain.aggregate(indexes=[Index("slug")])
        class Article:
            slug = String()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _unbounded_findings(ir) == []

    def test_indexed_integer_not_flagged(self):
        domain = Domain(name="IntIndex", root_path=".")

        @domain.aggregate(indexes=[Index("count")])
        class Tally:
            count = Integer()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _unbounded_findings(ir) == []

    def test_non_indexed_text_not_flagged(self):
        """The rule keys off index membership, not the field alone."""
        domain = Domain(name="NonIndexed", root_path=".")

        @domain.aggregate(indexes=[Index("slug")])
        class Article:
            slug = String(max_length=120)
            body = Text()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _unbounded_findings(ir) == []

    def test_aggregate_with_no_indexes_not_flagged(self):
        """``aggregate.get("indexes", [])`` handles the absent-key case."""
        domain = Domain(name="NoIndexes", root_path=".")

        @domain.aggregate
        class Article:
            body = Text()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _unbounded_findings(ir) == []

    def test_raw_index_skipped(self):
        """RawIndex entries carry no ``fields`` key and are skipped."""
        domain = Domain(name="RawIndex", root_path=".")

        @domain.aggregate(
            indexes=[Index.from_sql("postgresql", "CREATE INDEX gx ON note (body)")]
        )
        class Note:
            body = Text()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _unbounded_findings(ir) == []

    def test_value_object_attribute_reference_skipped(self):
        """An index over a value-object mapped attribute (absent from the
        scalar fields dict) is skipped, not raised.

        The value object here carries an *unbounded* ``Text`` attribute, so this
        also pins the documented scope limit: value-object attributes are not
        walked, so an unbounded one is deliberately **not** flagged. (Using a
        bounded street would have hidden that behind the ``field is None`` skip.)
        """
        domain = Domain(name="VOIndex", root_path=".")

        @domain.value_object
        class Meta(BaseValueObject):
            note = Text()

        @domain.aggregate(indexes=[Index("meta_note")])
        class Location:
            meta = ValueObject(Meta)
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Scope limit: an unbounded VO attribute is not covered by this rule.
        assert _unbounded_findings(ir) == []

    def test_abstract_aggregate_not_flagged(self):
        """Abstract aggregates are non-instantiable bases that emit no table;
        their declared indexes must not be flagged (regression: the rule is
        the only cluster-walker that must honor the abstract skip)."""
        domain = Domain(name="AbstractBase", root_path=".")

        @domain.aggregate(abstract=True, indexes=[Index("body")])
        class Base:
            body = Text()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _unbounded_findings(ir) == []

    def test_multiple_aggregates_attributed_per_element(self):
        """Across two aggregates in one domain, each finding is attributed to
        its own aggregate FQN (proves per-``element`` attribution, not a single
        cluster leaking into another)."""
        domain = Domain(name="MultiAgg", root_path=".")

        @domain.aggregate(indexes=[Index("body")])
        class Note:
            body = Text()

        @domain.aggregate(indexes=[Index("summary")])
        class Article:
            summary = Text()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _unbounded_findings(ir)
        assert len(findings) == 2, findings
        by_element = {f["element"]: f["field"] for f in findings}
        assert by_element[fqn(Note)] == "body"
        assert by_element[fqn(Article)] == "summary"
