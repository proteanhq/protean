# --8<-- [start:configure-logging]
from protean.utils.logging import configure_logging

configure_logging(
    level=None,
    format="auto",
    log_dir=None,
    log_file_prefix=None,
    max_bytes=10 * 1024 * 1024,
    backup_count=5,
    extra_processors=None,
    per_logger=None,
    dict_config=None,
    redact=None,
)
# --8<-- [end:configure-logging]
