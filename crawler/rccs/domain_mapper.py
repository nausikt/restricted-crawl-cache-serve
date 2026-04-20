"""
Auto-detect domain -> .test TLD mapping from seed URLs and site configs.

Given a set of real domains (e.g. twiki.cern.ch, cms-talk.web.cern.ch),
produces a mapping that replaces the TLD with .test:
    twiki.cern.ch        -> twiki.cern.test
    cms-talk.web.cern.ch -> cms-talk.web.cern.test
    deepwiki.com         -> deepwiki.test
"""
from __future__ import annotations

from urllib.parse import urlparse
from typing import Dict, List


def _replace_tld(domain: str) -> str:
    """Replace the last TLD segment of a domain with 'test'.

    Examples:
        twiki.cern.ch        -> twiki.cern.test
        cms-talk.web.cern.ch -> cms-talk.web.cern.test
        deepwiki.com         -> deepwiki.test
    """
    parts = domain.rstrip(".").split(".")
    if len(parts) < 2:
        return domain
    parts[-1] = "test"
    return ".".join(parts)


def extract_domains_from_urls(urls: List[str]) -> set[str]:
    """Extract unique hostnames from a list of URLs."""
    domains: set[str] = set()
    for url in urls:
        parsed = urlparse(url)
        host = parsed.hostname
        if host:
            domains.add(host.lower().rstrip("."))
    return domains


def build_domain_map(
    site_domains: List[str] | None = None,
    seed_urls: List[str] | None = None,
) -> Dict[str, str]:
    """Build {original_domain: test_domain} mapping.

    Merges domains declared in site configs with domains auto-detected
    from seed URLs.  Domains already ending in .test are skipped.
    """
    all_domains: set[str] = set()

    if site_domains:
        for d in site_domains:
            all_domains.add(d.lower().rstrip("."))

    if seed_urls:
        all_domains |= extract_domains_from_urls(seed_urls)

    domain_map: Dict[str, str] = {}
    for domain in sorted(all_domains):
        if domain.endswith(".test"):
            continue
        test_domain = _replace_tld(domain)
        domain_map[domain] = test_domain

    return domain_map
