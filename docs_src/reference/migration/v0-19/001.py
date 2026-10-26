from protean import Domain

domain = Domain(
    name="Shop",
    config={"enable_outbox": True, "server": {"default_subscription_type": "stream"}},
)


# --8<-- [start:fill]
from protean.utils.outbox import OutboxStatus

UNPUBLISHED = [
    OutboxStatus.PENDING.value,
    OutboxStatus.PROCESSING.value,
    OutboxStatus.FAILED.value,
    OutboxStatus.ABANDONED.value,
]


def fill_stream_category(provider: str = "default", page_size: int = 500) -> int:
    filled = 0
    skipped = 0
    with domain.domain_context():
        repo = domain._get_outbox_repo(provider)
        while True:
            rows = (
                repo.query.filter(
                    partition_key__isnull=False,
                    stream_category__isnull=True,
                    status__in=UNPUBLISHED,
                )
                .order_by(["created_at", "id"])
                .offset(skipped)
                .limit(page_size)
                .all()
                .items
            )
            if not rows:
                return filled
            for row in rows:
                meta = row.metadata_.domain
                if meta is None or meta.stream_category is None:
                    skipped += 1
                    continue
                row.stream_category = meta.stream_category
                repo.add(row)
                filled += 1


# --8<-- [end:fill]
