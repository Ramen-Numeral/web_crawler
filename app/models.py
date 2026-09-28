"""Records and heap nodes passed between crawler components."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic


@dataclass
class FetchedResult:
    """consumed as: reject if not retrievable; defer if retry is true; otherwise process links."""

    retrievable: bool
    retry: bool
    links: set[str] = field(default_factory=set)
    status: int | None = None
    error: str | None = None
    manners: Manners | None = None  # snapshot, not live entry
    final_url: str | None = None
    content_type: str | None = None
    bytes_read: int = 0
    elapsed: float = 0.0
    attempted: bool = False
    crawled_at: str | None = None


@dataclass
class Manners:
    last_fetched: float = 0.0
    delay_time: float = 0.0
    retry_until: float = 0.0

    def get_ready_at(self) -> float:
        """return the absolute monotonic deadline when timing permits a request."""
        return max(self.last_fetched + self.delay_time, self.retry_until)

    def can_fetch_now(self) -> bool:
        return monotonic() >= self.get_ready_at()

    def mark_fetched(self) -> None:
        self.last_fetched = monotonic()


@dataclass(order=True)
class FrontierNode:
    """order by depth, priority, then sequence; exclude the URL."""

    url: str = field(compare=False)
    depth: int
    priority: float
    sequence: int
    page_priority: float = field(compare=False, default=0.0)
    domain_priority: float = field(compare=False, default=0.0)


@dataclass(order=True)
class WaitingNode:
    """order by ready_at, then sequence; exclude the frontier node."""

    ready_at: float
    sequence: int
    node: FrontierNode = field(compare=False)
