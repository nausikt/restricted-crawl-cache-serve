"""
Archi config adapter — reads an Archi deployment YAML and produces
RCCS-specific crawl configuration.

Extracts ``data_manager.sources.web`` and transforms it into:
  - seed URLs (from input_lists + inline urls)
  - per-site spider configs (domain, auth, allow/deny, delay, depth, pages)
  - domain -> .test mapping
  - Scrapy settings dict for CrawlerProcess
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import yaml

from crawler.rccs.domain_mapper import build_domain_map, extract_domains_from_urls
from crawler.rccs.url_rewriter import URLRewriter

logger = logging.getLogger(__name__)


@dataclass
class SiteConfig:
    """Per-site crawl configuration extracted from Archi config."""

    key: str
    domain: str
    auth_provider_name: str = ""
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    max_depth: int = 2
    max_pages: int = 500
    delay: int | float = 60
    anonymize_data: bool = False
    markitdown: bool = False
    keywords: list[str] = field(default_factory=list)


@dataclass
class RCCSConfig:
    """Complete RCCS crawl configuration parsed from an Archi YAML."""

    seed_urls: list[str]
    sites: dict[str, SiteConfig]
    domain_map: dict[str, str]
    url_rewriter: URLRewriter
    fallback_spider: str = "link"
    mirror_root: str = "./mirror"

    # Global defaults (can be overridden per-site)
    global_max_depth: int = 2
    global_max_pages: int = 100
    global_delay: int | float = 10
    global_enabled: bool = True

    # Benchmark overrides
    benchmark: bool = False


def _extract_urls_from_file(path: Path) -> list[str]:
    """Read seed URLs from a .list file, skipping comments and blanks."""
    urls: list[str] = []
    if not path.exists():
        logger.warning("List file not found: %s", path)
        return urls
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            if line.startswith("http://") or line.startswith("https://"):
                urls.append(line)
    return urls


def _resolve_list_path(list_path: str, config_dir: Path, archi_root: Path | None) -> Path:
    """Resolve a list file path relative to the archi root or config directory."""
    p = Path(list_path)
    if p.is_absolute() and p.exists():
        return p

    if archi_root:
        candidate = archi_root / list_path
        if candidate.exists():
            return candidate

    candidate = config_dir / p.name
    if candidate.exists():
        return candidate

    candidate = config_dir / list_path
    if candidate.exists():
        return candidate

    return p


def parse_archi_config(
    config_path: str | Path,
    mirror_root: str = "./mirror",
    archi_root: str | Path | None = None,
    benchmark: bool = False,
) -> RCCSConfig:
    """Parse an Archi deployment YAML into an RCCSConfig."""
    config_path = Path(config_path)
    config_dir = config_path.parent

    if archi_root is None:
        archi_root_path: Path | None = None
    else:
        archi_root_path = Path(archi_root)

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    dm = raw.get("data_manager", {})
    sources = dm.get("sources", {})
    web = sources.get("web", {})

    global_enabled = web.get("enabled", True)
    fallback_spider = web.get("fallback_spider", "link")
    global_max_depth = web.get("max_depth", 2)
    global_max_pages = web.get("max_pages", 100)
    global_delay = web.get("delay", 10)

    # -- Collect seed URLs from input_lists --
    seed_urls: list[str] = list(web.get("urls") or [])
    for list_path in web.get("input_lists") or []:
        resolved = _resolve_list_path(list_path, config_dir, archi_root_path)
        seed_urls.extend(_extract_urls_from_file(resolved))

    # -- Parse per-site configs --
    sites_raw = web.get("sites", {}) or {}
    sites: dict[str, SiteConfig] = {}
    site_domains: list[str] = []

    for site_key, site_cfg in sites_raw.items():
        if not isinstance(site_cfg, dict):
            continue
        domain = site_cfg.get("domain", "")
        if domain:
            site_domains.append(domain)

        sites[site_key] = SiteConfig(
            key=site_key,
            domain=domain,
            auth_provider_name=site_cfg.get("auth_provider_name", ""),
            allow=site_cfg.get("allow", []),
            deny=site_cfg.get("deny", []),
            max_depth=site_cfg.get("max_depth", global_max_depth),
            max_pages=site_cfg.get("max_pages", global_max_pages),
            delay=site_cfg.get("delay", global_delay),
            anonymize_data=site_cfg.get("anonymize_data", False),
            markitdown=site_cfg.get("markitdown", False),
            keywords=site_cfg.get("keywords", []),
        )

    # -- Build domain mapping --
    domain_map = build_domain_map(site_domains=site_domains, seed_urls=seed_urls)
    url_rewriter = URLRewriter(domain_map)

    return RCCSConfig(
        seed_urls=seed_urls,
        sites=sites,
        domain_map=domain_map,
        url_rewriter=url_rewriter,
        fallback_spider=fallback_spider,
        mirror_root=mirror_root,
        global_max_depth=global_max_depth,
        global_max_pages=global_max_pages,
        global_delay=global_delay,
        global_enabled=global_enabled,
        benchmark=benchmark,
    )


def rccs_config_to_scrapy_settings(cfg: RCCSConfig) -> dict[str, Any]:
    """Load archi's Scrapy settings as the base and overlay RCCS-specific keys.

    Archi's settings.py provides the full crawl stack (middlewares, auth
    providers, pipelines, AutoThrottle, retry codes, etc.).  RCCS only
    adds CacheRawDownloaderMiddleware and the mirror/rewriter settings.
    """
    from scrapy.utils.project import get_project_settings

    settings = get_project_settings()

    delay = cfg.global_delay
    if cfg.benchmark:
        delay = min(delay, 1)

    # Overlay RCCS-specific values
    settings.set("DOWNLOAD_DELAY", delay, priority="project")
    settings.set("DEPTH_LIMIT", cfg.global_max_depth, priority="project")

    # Inject CacheRawDownloaderMiddleware into the middleware stack
    mw = dict(settings.getdict("DOWNLOADER_MIDDLEWARES", {}))
    mw["crawler.middlewares.cache_raw.CacheRawDownloaderMiddleware"] = 510
    settings.set("DOWNLOADER_MIDDLEWARES", mw, priority="project")

    # Disable archi's item pipelines (RCCS caches raw responses, not items)
    settings.set("ITEM_PIPELINES", {}, priority="project")

    # RCCS mirror and URL rewriting
    settings.set("RCCS_MIRROR_ROOT", cfg.mirror_root, priority="project")
    settings.set("RCCS_URL_REWRITER", cfg.url_rewriter, priority="project")
    settings.set("RCCS_DOMAIN_MAP", cfg.domain_map, priority="project")

    return settings
