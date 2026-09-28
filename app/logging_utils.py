"""Small network-error logging helper."""

import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

logger = logging.getLogger("crawler")


def log_fetch_error(
    error: Exception,
    *,
    url: str,
    phase: str = "request",
) -> None:
    """choose log severity and include tracebacks only for unexpected failures."""
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        host = ""

    if not isinstance(error, (HTTPError, URLError, OSError)):
        logger.exception(
            "%s_unexpected_failure host=%s",
            phase,
            host,
            exc_info=(type(error), error, error.__traceback__),
        )
        return

    status = error.code if isinstance(error, HTTPError) else None
    level = (
        logging.WARNING
        if status is None or status == 429 or status >= 500
        else logging.DEBUG
    )
    logger.log(
        level,
        "%s_failed host=%s error=%s status=%s",
        phase,
        host,
        f"http_{status}" if status is not None else type(error).__name__,
        status,
    )
