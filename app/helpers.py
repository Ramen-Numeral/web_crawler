"""URL and domain helpers shared by the crawler."""

from datetime import datetime
from urllib.parse import (
    quote,
    unquote_plus,
    urlparse,
    urlsplit,
    urlunsplit,
)

import tldextract

from settings import settings

user_agent = 'SpiderMan'

_tld_extractor = tldextract.TLDExtract(
    suffix_list_urls=(), include_psl_private_domains=True, cache_dir=None
)

# lookup to prevent revisiting pages where a tracking param has been set.
_TRACKING_PARAMS = frozenset(
    {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "_hsenc", "_hsmi"}
)


def _is_tracking_param(name: str) -> bool:
    name = name.lower()
    return name in _TRACKING_PARAMS or name.startswith("utm_")


def normalize_url(url: str) -> str:
    parts = urlsplit(url)

    # leave invalid or non-HTTP URLs for is_valid_url() to reject.
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return urlunsplit(parts._replace(fragment=""))

    # get_origin handles hostname casing, IPv6 brackets, and default ports.
    scheme, _, host = get_origin(url).partition("://")

    # preserve credentials if the URL has them.
    if "@" in parts.netloc:
        userinfo = parts.netloc.rsplit("@", 1)[0]
        host = f"{userinfo}@{host}"

    # encode literal spaces/Unicode, but preserve existing % escapes.
    path = quote(parts.path, safe="/%:@!$&'()*+,;=-._~")

    # remove tracking fields without decoding and rebuilding other fields.
    fields = []
    for field in parts.query.split("&"):
        name = unquote_plus(field.partition("=")[0])
        if not _is_tracking_param(name):
            fields.append(field)

    return urlunsplit((scheme, host, path, "&".join(fields), ""))


def is_valid_url(url: str) -> bool:
    """
    
    checks if the url is one of the banned domains (archival domains like wikipedia)
    and otherwise valid (no banned extension, etc.)

    """
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        blocked = any(host == domain or host.endswith(f".{domain}") for domain in settings.BANNED_DOMAINS)
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and len(url) <= settings.MAX_URL_LENGTH
            and not blocked
            # broad filter for crawler traps
            and "cgi" not in parsed.path.lower() #CGI gen'd pages
            and "/special:" not in parsed.path.lower() #skip wiki style util pages
            and "action=edit" not in parsed.query.lower()  #skip pages that will dead end with an unfulfillable action
            and not any(
                parsed.path.lower().endswith(ext) for ext in settings.BANNED_EXTENSIONS
            )
        )
    except ValueError:
        return False


def get_domain(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def get_origin(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if ":" in hostname:
        hostname = f"[{hostname}]"
    port = parsed.port
    #check if port belongs in origin scheme
    if port is not None and (parsed.scheme, port) not in (("http", 80), ("https", 443)): 
        hostname = f"{hostname}:{port}"
    return f"{parsed.scheme.lower()}://{hostname}"


def get_root_domain(url: str) -> str:
    hostname = get_domain(url)
    result = _tld_extractor(hostname)
    return f"{result.domain}.{result.suffix}" if result.suffix else hostname


def seconds_elapsed(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds()
