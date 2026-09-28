web crawler - homework 1

files

app/__init__.py         marks app as a python package.
app/__main__.py         reads command-line args and starts the crawl.
app/search.py           gets search results and picks ten usable seed urls.
app/fetcher.py          downloads pages and extracts html links.
app/helpers.py          normalizes urls and checks domains and file types.
app/models.py           records for fetch results, host timing, and heap nodes.
app/orchestrator.py     runs the two heaps, workers, stats, and crawl log.
app/politeness.py       checks robots.txt and spaces out host requests.
app/logging_utils.py    prints network errors during the crawl.
settings.py             crawl limits, delays, and blocked domains.
banned_extensions.csv   file types skipped when reading links.
app/banned_extensions.csv  same list for installed-package use.
pyproject.toml          python dependencies and package setup.
crawl1.log              euripides crawl: page records and final stats.
crawl2.log              dungeons and dragons crawl: page records and final stats.
readme.txt              this file.
explain.txt             crawler design, limitations, and bugs.

run it

use python 3.10 or newer. no compile step. from this folder:

    python3 -m venv .venv
    ./.venv/bin/python -m pip install -e .

run from the project folder so settings.py and the extension list are found:

    ./.venv/bin/python -m app "euripides" --max-pages 5000 --log-file crawl1.log
    ./.venv/bin/python -m app "dungeons and dragons" --max-pages 5000 --log-file crawl2.log

for a continuous demo, omit --max-pages and use a separate log file:

    ./.venv/bin/python -m app "euripides" --log-file demo.log

query is required. ddgs asks for up to 30 results; the crawler takes the first
ten distinct urls that pass its filters. it stops with an error if it gets
fewer than ten. search results can change, so rerunning may pick different
seeds. ddgs chooses the search backend automatically.

--max-pages optionally limits page request attempts and must be nonnegative.
without it, there is no page-count limit. robots skips do not use this budget.
the crawl can stop early
if no usable urls remain. --log-file chooses the output path (default
crawler.log). it must be writable; an existing file is overwritten.
ctrl-c stops the demo run and writes the summary.

If a process is force-killed before it can write a summary, recover the
page-level statistics with:

    python3 -m app.summarize_log crawl4.log

logs are json lines: one record for each attempted page request, then one
summary record. network warnings printed in the terminal are not page records.
page contents are not saved. pages_per_second counts successful 2xx requests
without fetch errors, not redirects or failed requests. http_attempts and
status_counts still include failures.

settings.py holds the worker count, pending-url cap, timeouts, host delay, size limit, and
blocked domains. wikipedia and archive hosts are skipped. crawl speed depends
on the sites reached, their robots rules, and network errors.

for submission, include the source, both logs, readme.txt, and explain.txt.
leave out .venv, __pycache__, .ruff_cache, and downloaded page contents.

demo notes

use a separate log name for trial runs; --log-file overwrites existing files.
ddgs can return fewer than ten usable seeds, so test the query before the demo.
the no-limit mode has passed offline tests, not a live 20-minute run.
