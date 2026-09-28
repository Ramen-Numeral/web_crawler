"""Command-line entry point."""

import argparse
import time

from settings import settings

from .orchestrator import Orchestrator
from .search import SearchError, search


def main() -> None:
    parser = argparse.ArgumentParser(description="A small priority web crawler")
    parser.add_argument("query", help="search query used to find seed pages")
    parser.add_argument(
        "--max-pages", type=int, default=None,
        help="optional request-attempt limit; unlimited by default",
    )
    parser.add_argument("--log-file", default=None)
    args = parser.parse_args()

    if args.log_file:
        object.__setattr__(settings, "LOG_FILE", args.log_file)

    try:
        seeds = search(args.query)
    except SearchError as error:
        parser.error(str(error))

    print(f"Seeds: {len(seeds)}")
    for seed in seeds:
        print(f"  {seed}")

    crawler = Orchestrator(seeds, max_pages=args.max_pages)
    try:
        crawler.run()
    except KeyboardInterrupt:
        print("\ncrawl stopped")
    print(f"Visited {crawler.visited} URLs; log written to {settings.LOG_FILE}")
    elapsed = time.monotonic() - crawler.started_at
    throughput = crawler.successful_pages / elapsed if elapsed else 0
    print(
        "Stats: "
        f"attempts={crawler.http_attempts}, "
        f"successful={crawler.successful_pages}, "
        f"robots_skips={crawler.robots_skips}, "
        f"bytes={crawler.total_bytes}, "
        f"throughput={throughput:.3f} successful pages/sec"
    )


if __name__ == "__main__":
    main()
