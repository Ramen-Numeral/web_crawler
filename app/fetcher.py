"""Download HTML pages and extract normalized links."""

from datetime import datetime, timezone
from time import perf_counter
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from settings import settings

from .helpers import is_valid_url, normalize_url
from .logging_utils import log_fetch_error
from .models import FetchedResult
from .politeness import PolitenessManager


class Fetcher:
    user_agent = "Spiderman"

    def __init__(self):
        self._politeness = PolitenessManager(self.user_agent) #shared manners cache for this fetcher

    def fetch(self, url: str) -> FetchedResult:
        try:
            manners = self._politeness.get_manners(url) #load or reuse robots rules and timing
        except Exception as error:
            log_fetch_error(error, url=url, phase="robots")
            return FetchedResult( #skip this url without retry
                retrievable=False,
                retry=False,
                error=f"robots_{type(error).__name__}",
            )

        robots_ok = self._politeness.allowed(url)
        if robots_ok is None:
            return FetchedResult( #wait for robots.txt before trying the page
                retrievable=True,
                retry=True,
                manners=self._politeness.snapshot(manners),
            )

        if not robots_ok:
            return FetchedResult( #robots denied; skip the page request
                retrievable=False,
                retry=False,
                error="robots_disallowed",
                manners=self._politeness.snapshot(manners),
            )

        if not self._politeness.reserve(manners): #check host delay and backoff under the lock
            return FetchedResult( #tell orchestrator to wait and try again
                retrievable=True,
                retry=True,
                manners=self._politeness.snapshot(manners),
            )

        try:
            crawled_at = datetime.now(timezone.utc).isoformat()
            result = self.get_links(url) #fetch response and extract valid html links
            result.manners = self._politeness.snapshot(manners) #attach a copy of timing state
            result.attempted = True #an HTTP request was made
            result.crawled_at = crawled_at
            return result
        except Exception as error:
            try:
                #log the request error
                log_fetch_error(error, url=url)
                if isinstance(error, HTTPError):
                    # Do not retry this page URL, but respect the server's
                    # rate limit for other URLs on the same origin.
                    if error.code == 429:
                        self._politeness.rate_limited(manners, error)
                    return FetchedResult(
                        retrievable=False,
                        retry=False,
                        attempted=True,
                        crawled_at=datetime.now(timezone.utc).isoformat(),
                        status=error.code,
                        error=f"http_{error.code}",
                        manners=self._politeness.snapshot(manners),
                    )
                # let orchestrator know not to push back onto a heap
                return FetchedResult(
                    retrievable=False,
                    retry=False,
                    attempted=True,
                    crawled_at=datetime.now(timezone.utc).isoformat(),
                    error=type(error).__name__,
                    manners=self._politeness.snapshot(manners),
                )
            finally:
                #get outta here
                if isinstance(error, HTTPError):
                    error.close()

    def get_links(self, url: str) -> FetchedResult:
        started = perf_counter() #measure elapsed request and parsing time
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=settings.REQUEST_TIMEOUT) as response:
            final_url = normalize_url(response.geturl())
            status = response.getcode()
            content_type = response.headers.get_content_type()
            #record non-html responses without reading or parsing the body
            if content_type != "text/html":
                return FetchedResult(
                    retrievable=True,
                    retry=False,
                    status=status,
                    final_url=final_url,
                    content_type=content_type,
                    elapsed=perf_counter() - started,
                )
            #plz don't fill my poor macbook air with massive file :/
            html = response.read(settings.MAX_CONTENT_LENGTH + 1)
            if len(html) > settings.MAX_CONTENT_LENGTH:
                return FetchedResult(
                    retrievable=True,
                    retry=False,
                    status=status,
                    final_url=final_url,
                    content_type=content_type,
                    bytes_read=len(html),
                    error="body_too_large",
                    elapsed=perf_counter() - started,
                )
        # yay, we did it, these links can be enqueued
        return FetchedResult(
            retrievable=True,
            retry=False,
            links=self._extract_links(html, final_url),
            status=status,
            final_url=final_url,
            content_type=content_type,
            bytes_read=len(html),
            elapsed=perf_counter() - started,
        )

    def _extract_links(self, html: bytes, final_url: str) -> set[str]:
        soup = BeautifulSoup(html, "lxml")
        base = soup.find("base", href=True)
        try:
            base_url = urljoin(final_url, base["href"]) if base else final_url
        except ValueError:
            base_url = final_url

        links: set[str] = set()
        for tag in soup.find_all("a", href=True):
            try:
                link = normalize_url(urljoin(base_url, tag["href"]))
            except ValueError:
                continue

            # validation also checks the shared settings.BANNED_EXTENSIONS set.
            if is_valid_url(link):
                links.add(link)

        return links
