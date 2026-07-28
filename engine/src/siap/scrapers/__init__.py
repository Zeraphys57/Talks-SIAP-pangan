"""Source-specific scrapers.

Every scraper subclasses `base.BaseScraper`, which owns the conduct rules
(robots.txt, delay, one connection per host, identifying User-Agent) and the
provenance writes (`raw_snapshots`, `fetch_failures`). A scraper that bypassed
the base class could be impolite; the design makes that awkward on purpose.
"""
