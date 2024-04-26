import logging
import os

logger = logging.getLogger(__name__)


def get_env():
    """Get the environment the app is running in, indicated by the
    :envvar:`PROTEAN_ENV` environment variable. The default is
    ``'production'``.
    """
    return os.environ.get("PROTEAN_ENV") or "production"


def get_debug_flag():
    """Get whether debug mode should be enabled for the app, indicated
    by the :envvar:`PROTEAN_DEBUG` environment variable. The default is
    ``True`` if :func:`.get_env` returns ``'development'``, or ``False``
    otherwise.
    """
    val = os.environ.get("PROTEAN_DEBUG")

    if not val:
        return get_env() == "development"

    return val.lower() not in ("0", "false", "no")
