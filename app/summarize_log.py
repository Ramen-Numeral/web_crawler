"""Calculate partial crawl statistics from a JSON-lines crawl log."""

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


def summarize(path: Path) -> dict:
    pages = []
    malformed_lines = 0

    with path.open(encoding="utf-8") as log_file:
        for line in log_file:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines += 1
                continue
            if record.get("record_type") == "page":
                pages.append(record)

    status_counts = Counter(
        str(page["status"]) if page.get("status") is not None else "error"
        for page in pages
    )
    successful_pages = sum(
        page.get("error") is None
        and page.get("status") is not None
        and 200 <= page["status"] < 300
        for page in pages
    )
    timestamps = []
    for page in pages:
        crawled_at = page.get("crawled_at")
        if crawled_at:
            try:
                timestamps.append(datetime.fromisoformat(crawled_at))
            except ValueError:
                pass
    observed_elapsed = (
        (max(timestamps) - min(timestamps)).total_seconds()
        if len(timestamps) >= 2
        else None
    )

    return {
        "record_type": "partial_summary",
        "pages_crawled": len(pages),
        "http_attempts": len(pages),
        "successful_pages": successful_pages,
        "total_size_bytes": sum(page.get("bytes", 0) or 0 for page in pages),
        "observed_elapsed_seconds": observed_elapsed,
        "estimated_throughput_successful_pages_per_sec": (
            successful_pages / observed_elapsed
            if observed_elapsed and observed_elapsed > 0
            else None
        ),
        "status_counts": dict(status_counts),
        "malformed_lines": malformed_lines,
        "note": "Per-URL page records cannot reconstruct scheduled, dropped, or robots-skip counts.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize a crawler JSON-lines log")
    parser.add_argument("log_file", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.log_file), indent=2))


if __name__ == "__main__":
    main()
