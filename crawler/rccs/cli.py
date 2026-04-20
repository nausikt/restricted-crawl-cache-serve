"""
RCCS CLI — orchestrates the crawl-cache-serve pipeline.

Usage:
    rccs -c <archi-config.yaml> parse            # validate + show crawl plan
    rccs parse -c <archi-config.yaml>            # same (config may precede or follow the subcommand)
    rccs crawl    -c <archi-config.yaml>         # run Scrapy with caching middleware
    rccs generate -c <archi-config.yaml>         # emit compose.yaml + nginx configs
    rccs run      -c <archi-config.yaml>         # all three steps in sequence

Standalone scrapy usage (with archi settings from submodule):
    cd crawler && scrapy crawl twiki
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from crawler.rccs.config_adapter import parse_archi_config, rccs_config_to_scrapy_settings, RCCSConfig
from generators.compose import generate_compose
from generators.nginx import generate_nginx_configs

logger = logging.getLogger("rccs")


# ---------------------------------------------------------------------------
# parse: validate config and show plan
# ---------------------------------------------------------------------------

def cmd_parse(cfg: RCCSConfig) -> None:
    """Print a summary of what RCCS will do."""
    print("=== RCCS Crawl Plan ===\n")
    print(f"Seed URLs:        {len(cfg.seed_urls)}")
    print(f"Sites configured: {len(cfg.sites)}")
    print(f"Domain mappings:  {len(cfg.domain_map)}")
    print(f"Benchmark mode:   {cfg.benchmark}")
    print(f"Mirror root:      {cfg.mirror_root}")
    print(f"Generated outdir: {cfg.generated_output_dir}")
    print()

    if cfg.domain_map:
        print("Domain mapping (original -> .test):")
        for orig, test in sorted(cfg.domain_map.items()):
            print(f"  {orig} -> {test}")
        print()

    if cfg.sites:
        print("Per-site configuration:")
        for key, site in cfg.sites.items():
            auth = f" [auth: {site.auth_provider_name}]" if site.auth_provider_name else ""
            print(f"  {key}: {site.domain}{auth}")
            print(f"    depth={site.max_depth}  pages={site.max_pages}  delay={site.delay}")
        print()

    if cfg.seed_urls:
        domain_buckets: dict[str, list[str]] = defaultdict(list)
        for url in cfg.seed_urls:
            host = urlparse(url).hostname or "unknown"
            domain_buckets[host].append(url)
        print("Seed URLs by domain:")
        for domain, urls in sorted(domain_buckets.items()):
            print(f"  {domain}: {len(urls)} URLs")
        print()


# ---------------------------------------------------------------------------
# crawl: run Scrapy CrawlerProcess with RCCS middlewares
# ---------------------------------------------------------------------------

def cmd_crawl(cfg: RCCSConfig) -> None:
    """Run Scrapy crawl with CacheRawDownloaderMiddleware."""
    from scrapy.crawler import CrawlerProcess

    settings = rccs_config_to_scrapy_settings(cfg)
    process = CrawlerProcess(settings)

    domain_to_spider = _build_domain_spider_map(cfg)
    url_buckets = _route_urls(cfg.seed_urls, domain_to_spider, cfg.fallback_spider)

    added = False
    for spider_key, urls in url_buckets.items():
        if not urls:
            continue

        site_cfg = cfg.sites.get(spider_key)
        spider_kwargs = {"start_urls": urls}

        if site_cfg:
            spider_kwargs["max_depth"] = site_cfg.max_depth
            spider_kwargs["max_pages"] = site_cfg.max_pages
            spider_kwargs["delay"] = site_cfg.delay if not cfg.benchmark else min(site_cfg.delay, 1)
            spider_kwargs["allow"] = site_cfg.allow
            spider_kwargs["deny"] = site_cfg.deny

        try:
            process.crawl(spider_key, **spider_kwargs)
            added = True
            logger.info("Scheduled spider %r with %d URLs", spider_key, len(urls))
        except KeyError:
            logger.warning("Spider %r not found, trying fallback %r", spider_key, cfg.fallback_spider)
            try:
                process.crawl(cfg.fallback_spider, **spider_kwargs)
                added = True
            except KeyError:
                logger.error("Fallback spider %r also not found, skipping", cfg.fallback_spider)

    if added:
        print(f"Starting crawl ({len(cfg.seed_urls)} seed URLs across {len(url_buckets)} spiders)...")
        process.start()
        print("Crawl complete.")
    else:
        print("No spiders scheduled — nothing to crawl.", file=sys.stderr)


# ---------------------------------------------------------------------------
# generate: emit compose.yaml + nginx configs
# ---------------------------------------------------------------------------

def cmd_generate(cfg: RCCSConfig) -> None:
    """Generate compose.yaml and nginx site configs from the domain mapping.

    Output location is controlled by ``cfg.generated_output_dir`` (CLI flag
    ``--generated-output-dir`` / env ``GENERATED_OUTPUT_DIR``).  Default is
    the current working directory.
    """
    out_root = Path(cfg.generated_output_dir).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    compose_path = generate_compose(
        domain_map=cfg.domain_map,
        output_path=out_root / "compose.yaml",
    )
    print(f"Generated: {compose_path}")

    nginx_configs = generate_nginx_configs(
        domain_map=cfg.domain_map,
        output_dir=out_root / "nginx" / "sites",
    )
    for p in nginx_configs:
        print(f"Generated: {p}")

    print(f"\nTo serve: (cd {out_root} && docker compose up -d)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_domain_spider_map(cfg: RCCSConfig) -> dict[str, str]:
    """Map hostnames to spider keys from site configs."""
    domain_map: dict[str, str] = {}
    for spider_key, site in cfg.sites.items():
        if site.domain:
            domain_map[site.domain.lower().rstrip(".")] = spider_key
    return domain_map


def _route_urls(
    urls: list[str],
    domain_to_spider: dict[str, str],
    fallback: str,
) -> dict[str, list[str]]:
    """Partition seed URLs into {spider_key: [urls]} buckets."""
    buckets: dict[str, list[str]] = defaultdict(list)
    for url in urls:
        host = urlparse(url).hostname
        if host:
            host = host.lower().rstrip(".")
        spider_key = domain_to_spider.get(host, fallback) if host else fallback
        buckets[spider_key].append(url)
    return dict(buckets)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parsers() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    """Return (full_parser, global_parser).

    Global options are parsed from anywhere in argv via ``parse_known_args`` so
    ``rccs -c cfg.yaml parse`` and ``rccs parse -c cfg.yaml`` both work.
    """
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument(
        "--config", "-c",
        required=False,
        help="Path to Archi deployment config YAML",
    )
    global_parser.add_argument(
        "--mirror-root",
        default=os.environ.get("MIRROR_ROOT", "./mirror"),
        help=(
            "Root directory for cached mirror content "
            "(env: MIRROR_ROOT, default: ./mirror)"
        ),
    )
    global_parser.add_argument(
        "--generated-output-dir",
        default=os.environ.get("GENERATED_OUTPUT_DIR", "."),
        help=(
            "Directory where compose.yaml and nginx/sites/ are written "
            "(env: GENERATED_OUTPUT_DIR, default: .)"
        ),
    )
    global_parser.add_argument(
        "--archi-root",
        default=os.environ.get("ARCHI_ROOT"),
        help=(
            "Root directory of archi submodule (for resolving list file paths; "
            "env: ARCHI_ROOT)"
        ),
    )
    global_parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Benchmark mode: reduce delays to minimum for fast re-crawling",
    )
    global_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging output",
    )

    full_parser = argparse.ArgumentParser(
        prog="rccs",
        description="Restricted Crawl, Cache, and Serve",
        parents=[global_parser],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = full_parser.add_subparsers(dest="command", required=True)
    sub.add_parser("parse", help="Validate config and show crawl plan")
    sub.add_parser("crawl", help="Run Scrapy crawl with caching middleware")
    sub.add_parser("generate", help="Generate compose.yaml + nginx configs")
    sub.add_parser("run", help="Parse + crawl + generate (full pipeline)")

    return full_parser, global_parser


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    full_parser, global_parser = build_parsers()

    if not argv:
        full_parser.print_help()
        sys.exit(1)

    gargs, rest = global_parser.parse_known_args(argv)
    if not rest:
        full_parser.print_help()
        sys.exit(1)

    cmd_args = full_parser.parse_args(rest)
    if not gargs.config:
        full_parser.error("the following arguments are required: -c/--config")

    logging.basicConfig(
        level=logging.DEBUG if gargs.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    cfg = parse_archi_config(
        config_path=gargs.config,
        mirror_root=gargs.mirror_root,
        archi_root=gargs.archi_root,
        benchmark=gargs.benchmark,
        generated_output_dir=gargs.generated_output_dir,
    )

    if cmd_args.command == "parse":
        cmd_parse(cfg)
    elif cmd_args.command == "crawl":
        cmd_parse(cfg)
        cmd_crawl(cfg)
    elif cmd_args.command == "generate":
        cmd_parse(cfg)
        cmd_generate(cfg)
    elif cmd_args.command == "run":
        cmd_parse(cfg)
        cmd_crawl(cfg)
        cmd_generate(cfg)


if __name__ == "__main__":
    main()
