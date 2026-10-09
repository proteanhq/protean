# --8<-- [start:imports]
import logging
import os

import httpx

# --8<-- [end:imports]
from protean import Domain

# --8<-- [start:alert]
logger = logging.getLogger(__name__)
_SLACK_WEBHOOK = os.environ.get("SLACK_DLQ_WEBHOOK")


def on_dlq_alert(dlq_stream: str, depth: int, threshold: int) -> None:
    """Post a Slack message when a DLQ crosses its depth threshold."""
    if not _SLACK_WEBHOOK:
        logger.warning(
            "DLQ alert: %s depth=%d threshold=%d", dlq_stream, depth, threshold
        )
        return

    try:
        httpx.post(
            _SLACK_WEBHOOK,
            json={
                "text": (
                    f":warning: DLQ `{dlq_stream}` has {depth} messages "
                    f"(threshold {threshold}). Investigate before replaying."
                )
            },
            timeout=2.0,
        )
    except httpx.HTTPError:
        logger.exception("Failed to post DLQ alert to Slack")


# --8<-- [end:alert]

# The page sets these keys under [server.dlq] in domain.toml. The callback path
# names this module, so the engine imports the function defined above.
domain = Domain(
    name="Orders",
    config={
        "server": {
            "dlq": {
                "enabled": True,
                "retention_hours": 168,
                "alert_threshold": 100,
                "alert_callback": f"{__name__}.on_dlq_alert",
            }
        }
    },
)
