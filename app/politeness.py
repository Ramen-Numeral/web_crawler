"""robots.txt rules, host delays, and retry timing."""

from dataclasses import replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from threading import Event, Lock
from time import monotonic
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from settings import settings

from .helpers import get_origin
from .models import Manners

ROBOTS_RETRIES = 2


class PolitenessManager:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self._cache: dict[str, Manners] = {} #shared timing per origin
        self._rules: dict[str, RobotFileParser | None] = {} #parsed robots rules per origin
        self._robots_retrying: set[str] = set() #origins waiting to reload robots.txt
        self._robots_failures: dict[str, int] = {} #cap retries per origin
        self._loading: dict[str, Event] = {} #robots lookups still in progress
        self._lock = Lock()

    def get_manners(self, url: str) -> Manners:
        origin = get_origin(url)
        with self._lock: #lock shared cache and loading state
            manners = self._cache.get(origin)
            if manners is not None and (
                origin not in self._robots_retrying or monotonic() < manners.retry_until
            ):
                return manners
            event = self._loading.get(origin)
            if event is None:
                event = Event()
                self._loading[origin] = event
                owner = True
            else:
                owner = False

        if not owner:
            event.wait() #wait for the other worker's robots lookup
            with self._lock:
                return self._cache[origin]

        try:
            rules, delay, retry_after = check_robots(url, self.user_agent)
        except Exception:
            # failed robots lookup is cached as a deny.
            rules, delay, retry_after = None, None, None

        with self._lock:
            self._rules[origin] = rules
            manners = self._cache.setdefault(origin, Manners())
            manners.delay_time = max(delay or 0.0, settings.DOMAIN_DELAY)
            if retry_after is not None:
                failures = self._robots_failures.get(origin, 0) + 1
                self._robots_failures[origin] = failures
                if failures <= ROBOTS_RETRIES:
                    self._robots_retrying.add(origin)
                    manners.retry_until = max(manners.retry_until, monotonic() + retry_after)
                else:
                    self._robots_retrying.discard(origin) #stop retrying this origin
            else:
                self._robots_retrying.discard(origin)
            self._loading.pop(origin).set() #remove lookup and wake waiting workers
            return manners

    def allowed(self, url: str) -> bool | None:
        with self._lock:
            origin = get_origin(url)
            if origin in self._robots_retrying:
                return None #robots.txt is temporarily unavailable
            rules = self._rules[origin]
        return rules is not None and rules.can_fetch(self.user_agent, url) #check this path

    def reserve(self, manners: Manners) -> bool:
        with self._lock:
            if not manners.can_fetch_now(): #wait for host delay or backoff
                return False

            manners.mark_fetched() #timestamp when this request is reserved
            return True

    def snapshot(self, manners: Manners) -> Manners:
        with self._lock: #copy timing state while locked
            return replace(manners)

    def rate_limited(self, manners: Manners, error: HTTPError) -> None:
        retry_after = get_retry_after(error) #read the 429 Retry-After header
        if retry_after is None: #use a default when absent or invalid
            retry_after = 30.0

        with self._lock: #keep the later retry deadline
            manners.retry_until = max(
                manners.retry_until,
                monotonic() + retry_after,
            )


def check_robots(
    url: str, user_agent: str
) -> tuple[RobotFileParser | None, float | None, float | None]:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    spider_sense = RobotFileParser(robots_url)
    request = Request(robots_url, headers={"User-Agent": user_agent})
    try:
        with urlopen(request, timeout=settings.REQUEST_TIMEOUT) as response:
            contents = response.read(256_000).decode("utf-8", errors="replace")
        spider_sense.parse(contents.splitlines())
    except HTTPError as error:
        try:
            if error.code in (401, 403): #robots access denied
                return None, None, None
            if error.code == 429 or error.code >= 500:
                retry_after = get_retry_after(error)
                return None, None, max(1.0, retry_after if retry_after is not None else 30.0)
        finally:
            error.close()
        spider_sense.parse([]) #other HTTP errors are treated as no robots rules

    #read parsed crawl-delay and request-rate rules
    crawl_delay = spider_sense.crawl_delay(user_agent) 
    request_rate = spider_sense.request_rate(user_agent)
    rate_delay = (
        request_rate.seconds / request_rate.requests
        if request_rate is not None
        else None
    )
    #use the stricter delay
    delay = max(
        (d for d in (crawl_delay, rate_delay) if d is not None),
        default=None,
    )

    return spider_sense, delay, None


def get_retry_after(error: HTTPError) -> float | None:
    value = error.headers.get("Retry-After")

    if value is None: #caller supplies the thirty-second default
        return None

    try:
        return float(value)
    except ValueError:
        pass

    #convert an HTTP date to seconds from now
    try:
        retry_at = parsedate_to_datetime(value)

        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)

        return max(
            0.0,
            (retry_at - datetime.now(timezone.utc)).total_seconds(),
        )
    except (TypeError, ValueError):
        return None
