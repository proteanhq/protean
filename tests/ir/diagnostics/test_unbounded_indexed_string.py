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
        """One finding per index occurrence, not deduped per field."""
        domain = Domain(name="TwoIndexes", root_path=".")

        @domain.aggregate(indexes=[Index("body"), Index("body", "created_at")])
        class Post:
            body = Text()
            created_at = String(max_length=40)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _unbounded_findings(ir)
        assert len(findings) == 2, findings
        assert all(f["field"] == "body" for f in findings)

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
        scalar fields dict) is skipped, not raised."""
        domain = Domain(name="VOIndex", root_path=".")

        @domain.value_object
        class Address(BaseValueObject):
            street = String(max_length=100)

        @domain.aggregate(indexes=[Index("address_street")])
        class Location:
            address = ValueObject(Address)
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _unbounded_findings(ir) == []
