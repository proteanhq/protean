"""A domain that hand-rolls raw SQL, for the --opportunities CLI tests.

It reaches for ``sqlalchemy.text(...)`` in two places, which the query API has
covered since 0.16.0. The functions are never called; only their source is read
by the opportunity detector.
"""

from sqlalchemy import text

from protean import Domain
from protean.fields import String

domain = Domain(name="OPP_TEXT")


@domain.aggregate
class Report:
    name = String()


def count_reports(session):
    return session.execute(text("SELECT count(*) FROM report"))


def unnamed_reports(session):
    return session.execute(text("SELECT * FROM report WHERE name IS NULL"))
