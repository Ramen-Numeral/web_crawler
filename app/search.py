"""Search engine results used as crawl seeds."""

from ddgs import DDGS

from settings import settings

from .helpers import is_valid_url, normalize_url


class SearchError(RuntimeError):
    pass


def search(query: str) -> list[str]:
    try:
        # ask for thirty results so blocked and duplicate urls leave ten seeds
        results = DDGS(timeout=settings.REQUEST_TIMEOUT).text(query, max_results=30)
    except Exception as error:
        raise SearchError(f"search failed: {error}") from error

    seeds: list[str] = []
    for result in results:
        try:
            url = normalize_url(result["href"])
            if not is_valid_url(url) or url in seeds:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        seeds.append(url)
        if len(seeds) == 10:
            return seeds

    raise SearchError(f"search returned only {len(seeds)} usable seed pages")
