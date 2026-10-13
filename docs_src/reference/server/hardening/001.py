from protean import Domain


# --8<-- [start:alert_callback]
def on_dlq_alert(dlq_stream: str, depth: int, threshold: int) -> None: ...


# --8<-- [end:alert_callback]

# The callback path names this module, so the engine imports the function above.
domain = Domain(
    name="Orders",
    config={
        "server": {
            "dlq": {
                "enabled": True,
                "alert_callback": f"{__name__}.on_dlq_alert",
            }
        }
    },
)
