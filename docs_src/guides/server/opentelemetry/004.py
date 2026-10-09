from protean import Domain

# --8<-- [start:imports]
from protean.utils.telemetry import get_tracer, set_span_error

# --8<-- [end:imports]

domain = Domain(
    name="Catalog",
    config={"telemetry": {"enabled": True, "exporter": "console"}},
)

_cache = {"sku-1": "Blue mug"}


# --8<-- [start:span]
def cache_get(key: str) -> str:
    tracer = get_tracer(domain)  # or self._domain.tracer, current_domain.tracer

    with tracer.start_as_current_span(
        "protean.cache.get",
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        span.set_attribute("protean.cache.key", key)
        try:
            return _cache[key]  # the actual work
        except Exception as exc:
            set_span_error(span, exc)
            raise


# --8<-- [end:span]
