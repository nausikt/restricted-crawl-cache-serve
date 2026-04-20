# Restricted Crawl, Cache, and Serve (RCCS)

Crawl auth-gated and public websites, cache raw HTML/PDF responses with URL rewriting, and serve them locally via nginx for offline RAG benchmarking.

*Especially for sensitive services: CERN TWiki (Public/Private), CERN SSO Discourse, paywalled publications, etc.*

## How it works

1. **Crawl** — Scrapy spiders (with SSO auth via archi submodule) fetch pages
2. **Cache** — `CacheRawDownloaderMiddleware` saves raw HTML/PDF to `mirror/`, rewriting domains (`twiki.cern.ch` → `twiki.cern.test`, `https` → `http`)
3. **Serve** — Auto-generated `compose.yaml` + nginx configs serve cached content at `.test` domains

## Quick Start

### Using an Archi deployment config

```bash
# Parse config and show crawl plan
python -m crawler.rccs.cli --config path/to/archi-config.yaml parse

# Crawl and cache all web sources
python -m crawler.rccs.cli --config path/to/archi-config.yaml crawl

# Generate compose.yaml + nginx configs
python -m crawler.rccs.cli --config path/to/archi-config.yaml generate

# Full pipeline (parse + crawl + generate)
python -m crawler.rccs.cli --config path/to/archi-config.yaml run

# Serve the cached mirror
docker compose up -d
```

### Benchmark mode

For fast re-crawling against already-cached content or local mirrors:

```bash
python -m crawler.rccs.cli --config config.yaml --benchmark crawl
```

This reduces all delays to at most 1 second.

### Standalone Scrapy (with archi spiders)

Spiders, settings, and auth come from the archi submodule:

```bash
cd crawler
scrapy crawl twiki
```

## Architecture

```
Archi config.yaml
       │
       ▼
 ConfigAdapter ──→ Scrapy CrawlerProcess
                        │
            ┌───────────┼───────────┐
            ▼           ▼           ▼
    AuthDownloader  CacheRaw     Retry
    Middleware(500) MW(510)      MW(550)
                        │
                        ▼
               URLRewriter + Save
               mirror/<site>/<path>/
                        │
                        ▼
              ComposeGenerator + NginxGenerator
              compose.yaml + nginx/sites/*.conf
                        │
                        ▼
               docker compose up -d
            nginx serves *.cern.test
```

## Project Structure

```
restricted-crawl-cache-serve/
  archi/                        # git submodule → nausikt/archi
  crawler/
    scrapy.cfg                  # points to archi's settings.py
    rccs/
      config_adapter.py         # Parse Archi YAML → RCCS crawl config
      url_rewriter.py           # Domain/scheme rewriting engine
      domain_mapper.py          # Auto-detect domain → .test mapping
      cli.py                    # CLI entry point
    middlewares/
      cache_raw.py              # CacheRawDownloaderMiddleware
  generators/
    compose.py                  # Auto-generate compose.yaml
    nginx.py                    # Auto-generate nginx site configs
  templates/
    compose.yaml.j2             # Jinja2 template for compose
    nginx-site.conf.j2          # Jinja2 template for nginx vhost
  mirror/                       # Cached crawl output
  nginx/sites/                  # Generated nginx configs
  pyproject.toml
```

Spiders, Scrapy settings, auth middlewares, and pipelines all come from the
archi submodule (`src.data_manager.collectors.scrapers.*`). RCCS only adds
`CacheRawDownloaderMiddleware` and the URL rewriting / generation layer.

## URL Rewriting

RCCS automatically detects domains from seed URLs and site configs, then rewrites:
- `https://twiki.cern.ch/...` → `http://twiki.cern.test/...`
- `https://cms-talk.web.cern.ch/...` → `http://cms-talk.web.cern.test/...`

The TLD is replaced with `.test` and `https` is downgraded to `http` for local serving.

## Contributors

- Krittin Phornsiricharoenphant (krittin.phornsiricharoenphant@cern.ch)
