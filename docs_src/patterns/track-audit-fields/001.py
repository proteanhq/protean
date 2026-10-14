# --8<-- [start:base]
from protean import Domain
from protean.fields import DateTime, String

domain = Domain()


@domain.aggregate(abstract=True, auto_add_id_field=False)
class Audited:
    created_at: DateTime(auto_now_add=True)  # stamped once, on create
    updated_at: DateTime(auto_now=True)  # stamped on every save
    created_by: String(max_length=50)
    updated_by: String(max_length=50)


@domain.aggregate
class Article(Audited):
    title: String(max_length=200)
    body: String(max_length=5000)


# --8<-- [end:base]


# --8<-- [start:enricher]
from protean.utils.globals import g


@domain.aggregate_enricher
def stamp_audit_user(aggregate):
    if not hasattr(
        aggregate, "updated_by"
    ):  # a framework record, such as an outbox row
        return
    user = g.get("current_user")
    aggregate.updated_by = user
    if aggregate.created_by is None:  # set once, on create; preserved after
        aggregate.created_by = user


# --8<-- [end:enricher]


# --8<-- [start:supply]
def publish_hello():
    with domain.domain_context(current_user="alice"):
        repo = domain.repository_for(Article)
        repo.add(Article(title="Hello", body="..."))


# --8<-- [end:supply]


# --8<-- [start:round_trip]
def create_then_update():
    # Create, as "alice"
    with domain.domain_context(current_user="alice"):
        repo = domain.repository_for(Article)
        article = Article(title="Draft", body="...")
        repo.add(article)
        article_id = article.id

    stored = domain.repository_for(Article).get(article_id)
    # stored.created_at and stored.updated_at are set
    # stored.created_by == stored.updated_by == "alice"

    # Update, as "bob"
    with domain.domain_context(current_user="bob"):
        repo = domain.repository_for(Article)
        article = repo.get(article_id)
        article.title = "Published"
        repo.add(article)

    final = domain.repository_for(Article).get(article_id)
    # final.created_at unchanged; final.updated_at advanced
    # final.created_by == "alice"; final.updated_by == "bob"
    return stored, final


# --8<-- [end:round_trip]

domain.init(traverse=False)
