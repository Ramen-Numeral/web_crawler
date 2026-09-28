"""Two-heap concurrent crawl scheduler."""

import heapq
import json
import logging
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from itertools import count
from pathlib import Path
from time import monotonic

from app.fetcher import Fetcher
from app.helpers import get_domain, get_root_domain, is_valid_url, normalize_url
from app.models import FetchedResult, FrontierNode, WaitingNode
from settings import settings

logger = logging.getLogger(__name__)
fetcher = Fetcher()
_sequence = count()


class Orchestrator:
    def __init__(self, seeds: str | list[str], max_pages: int | None = None):
        self.frontier_heap: list[FrontierNode] = []
        self.waiting_heap: list[WaitingNode] = []
        # normalized urls already queued or visited; separate from the manners cache
        self.seen_table: set[str] = set() 
        # normalized post-redirect URLs whose pages have already been processed
        self.visited_final_urls: set[str] = set()
        self.domain_counts: dict[str, int] = {}
        self.root_domain_counts: dict[str, int] = {}
        self.max_pages = max_pages
        self.scheduled = 0
        self.dropped_urls = 0
        self.visited = 0
        self.http_attempts = 0
        self.robots_skips = 0
        self.successful_pages = 0
        self.total_bytes = 0
        self.status_counts: dict[str, int] = {}
        self.started_at = time.monotonic()
        log_path = Path(settings.LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_file = log_path.open("w", encoding="utf-8")

        if isinstance(seeds, str):
            seeds = [seeds]
        self.seeds = list(seeds)
        for seed in self.seeds:
            self.enqueue(seed, depth=0)

    def enqueue(
        self,
        url: str,
        depth: int,
        priority: float | None = None,
    ) -> None:
        norm_url = normalize_url(url)
       
        # skip invalid or already queued urls before adding more heap work
        if not is_valid_url(norm_url):
            return
        if norm_url in self.seen_table:
            return
        if len(self.frontier_heap) + len(self.waiting_heap) >= settings.MAX_PENDING_URLS:
            self.dropped_urls += 1 #keep pending work bounded during long runs
            return
        # mark the url seen when queued so another page cannot queue it again
        self.seen_table.add(norm_url)

        # prefer less-visited hosts and root domains within the same depth
        page_priority = 1.0 / (self.domain_counts.get(get_domain(norm_url), 0) + 1)
        domain_priority = 1.0 / (
            self.root_domain_counts.get(get_root_domain(norm_url), 0) + 1
        )
        if priority is None:
            # heapq pops the smallest value, so negate the novelty score
            priority = -(page_priority + 0.5 * domain_priority)

        node = FrontierNode(
            depth=depth,
            priority=priority,
            sequence=next(_sequence),
            url=norm_url,
            page_priority=page_priority,
            domain_priority=domain_priority,
        )

        heapq.heappush(
            self.frontier_heap,
            node,
        )

    def defer( #waiting queue manager
        self,
        node: FrontierNode,
        ready_at,
    ) -> None:
        waiting_node = WaitingNode(
            ready_at,
            sequence=next(_sequence),
            node=node,
        )

        heapq.heappush(
            self.waiting_heap,
            waiting_node,
        )

    def promote_waiting(self) -> None:
        now = monotonic()
        # move ready urls back; the frontier heap orders them by depth
        while self.waiting_heap and self.waiting_heap[0].ready_at <= now:
            waiting_node = heapq.heappop(self.waiting_heap)

            heapq.heappush(
                self.frontier_heap,
                waiting_node.node,
            )

    def process_result(
        self,
        node: FrontierNode,
        result: FetchedResult,
    ) -> None:
        if result.attempted: #log and count actual page requests, including failures
            # stat maxxxx
            self._log_visit(node, result)
            self.visited += 1
            self.http_attempts += 1
            self.total_bytes += result.bytes_read
            status_key = str(result.status) if result.status is not None else "error"
            self.status_counts[status_key] = self.status_counts.get(status_key, 0) + 1
            if result.error is None and result.status is not None and 200 <= result.status < 300:
                self.successful_pages += 1
        # requests skipped before fetch do not use the page budget
        elif not result.retry:
            self.robots_skips += 1

        if not result.retrievable:
            return
        
        if result.retry:
            self.defer(
                node,
                result.manners.get_ready_at(),
            )
            return

        final_url = normalize_url(result.final_url or node.url)
        duplicate_destination = final_url in self.visited_final_urls
        self.visited_final_urls.add(final_url)

        domain = get_domain(final_url)
        root_domain = get_root_domain(final_url)
        self.domain_counts[domain] = self.domain_counts.get(domain, 0) + 1
        self.root_domain_counts[root_domain] = (
            self.root_domain_counts.get(root_domain, 0) + 1
        )

        if duplicate_destination:
            return

        for link in result.links:
            self.enqueue(
                url=link,
                depth=node.depth + 1,
            )

    def _log_visit(self, node: FrontierNode, result: FetchedResult) -> None:
        record = {
            "record_type": "page",
            "visit_order": self.visited + 1,
            "url": node.url,
            "final_url": result.final_url,
            "crawled_at": result.crawled_at,
            "depth": node.depth,
            "page_priority": node.page_priority,
            "domain_priority": node.domain_priority,
            "status": result.status,
            "content_type": result.content_type,
            "bytes": result.bytes_read,
            "elapsed_seconds": result.elapsed,
            "error": result.error,
        }
        self.log_file.write(json.dumps(record) + "\n")
        if (self.visited + 1) % 100 == 0:
            self.log_file.flush()

    def _log_summary(self) -> None:
        total_time = time.monotonic() - self.started_at
        summary = {
            "record_type": "summary",
            "pages_crawled": self.visited,
            "http_attempts": self.http_attempts,
            "urls_scheduled": self.scheduled,
            "urls_dropped_at_capacity": self.dropped_urls,
            "successful_pages": self.successful_pages,
            "robots_skips": self.robots_skips,
            "total_size_bytes": self.total_bytes,
            "total_time_seconds": round(total_time, 3),
            "pages_per_second": round(self.successful_pages / total_time, 3) if total_time else 0,
            "status_counts": self.status_counts,
            "404_errors": self.status_counts.get("404", 0),
            "403_errors": self.status_counts.get("403", 0),
            "429_errors": self.status_counts.get("429", 0),
            "seeds": self.seeds,
        }
        self.log_file.write(json.dumps(summary) + "\n")
        self.log_file.flush()

    def _has_work(
        self,
        active: dict[Future, FrontierNode],
    ) -> bool:
        return bool(self.frontier_heap or self.waiting_heap or active)

    def _submit_ready(
        self,
        executor: ThreadPoolExecutor,
        active: dict[Future, FrontierNode],
    ) -> None:
        # count active workers against the remaining request budget
        while (
            self.frontier_heap
            and len(active) < settings.MAX_WORKERS
            and (self.max_pages is None or self.http_attempts + len(active) < self.max_pages)
        ):
            node = heapq.heappop(self.frontier_heap)

            future = executor.submit(
                fetcher.fetch,
                node.url,
            )

            active[future] = node
            self.scheduled += 1

    def _next_timeout(self) -> float | None:
        if not self.waiting_heap:
            return None

        return max(
            0.0,
            self.waiting_heap[0].ready_at - monotonic(),
        )

    def _wait_and_process(
        self,
        active: dict[Future, FrontierNode],
    ) -> None:
        if active:
            done, _ = wait(
                active,
                timeout=self._next_timeout(),
                return_when=FIRST_COMPLETED,
            )

            for future in done:
                node = active.pop(future)

                try:
                    result = future.result()
                except Exception:
                    logger.exception(
                        "worker_failed url=%s",
                        node.url,
                    )
                    continue

                self.process_result(
                    node,
                    result,
                )

            return

        timeout = self._next_timeout()

        if timeout is not None:
            time.sleep(timeout)

    def run(self) -> None:
    #all that just for this little loop? yup
        active: dict[Future, FrontierNode] = {}

        if self.max_pages is not None and self.max_pages < 0:
            raise ValueError("max_pages must be nonnegative")

        executor = ThreadPoolExecutor(max_workers=settings.MAX_WORKERS)
        interrupted = False
        try:
            while active or (
                (self.max_pages is None or self.http_attempts < self.max_pages)
                and (self.frontier_heap or self.waiting_heap)
            ):
                self.promote_waiting()
                self._submit_ready(executor, active)
                self._wait_and_process(active)
        except KeyboardInterrupt:
            # Write the summary before shutting down workers.  Waiting for
            # network requests here can otherwise make a second Ctrl-C abort
            # cleanup before the summary is written.
            interrupted = True
            for future in active:
                future.cancel()
            self._log_summary()
            raise
        finally:
            executor.shutdown(wait=not interrupted, cancel_futures=interrupted)
            if not interrupted:
                self._log_summary()
            self.log_file.close()
