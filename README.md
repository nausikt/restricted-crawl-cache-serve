# Restricted Crawl, Cache, and Serve (RCCS)

Crawl auth-gated and public websites, cache raw responses (HTML, JSON, RSS,
PDFs, Office docs, images, ...) with URL rewriting, and serve them locally
via nginx for offline RAG benchmarking.

Designed for sensitive/auth-gated sources such as CERN TWiki (Public/Private),
CERN SSO Discourse (`cms-talk.web.cern.ch`), and paywalled publications.

---

## How it works

1. **Crawl** — Scrapy spiders from the [archi](./archi) submodule fetch pages.
   Auth (e.g. CERN SSO) is handled by archi's `AuthDownloaderMiddleware`.
2. **Cache** — `CacheRawDownloaderMiddleware` saves raw responses to
   `<mirror_root>/<site>/<path>`:
   - HTML and XHTML are URL-rewritten (`twiki.cern.ch` → `twiki.cern.test`,
     `https` → `http`) so internal links resolve locally.
   - JSON / RSS / Atom / XML / Markdown / plain text are saved verbatim
     (preserves API payload semantics, e.g. Discourse JSON).
   - PDFs, MS Office (`.doc/.docx/.ppt/.pptx/.xls/.xlsx`), OpenDocument
     (`.odt/.odp/.ods`), RTF, EPUB, and all common image formats are saved
     as raw bytes.
   - Servers that return `application/octet-stream` are still handled via
     URL-extension fallback.
   - Query strings become filename suffixes — e.g. `87.json?page=3` is
     saved as `87.json__q__page-3`, so different query values map to
     different cached files.
3. **Serve** — `rccs generate` emits a `compose.yaml` + per-site nginx
   configs. The compose file has **absolute volume paths baked in** from
   `$MIRROR_ROOT` and `$GENERATED_OUTPUT_DIR`, so `(docker|podman) compose
   -f <path>/compose.yaml up` works from any directory. Nginx is served
   **only** on a private, no-egress container network named
   `restricted_mirror` — **no host ports are published**. Consumers
   (archi's `data_manager`, ad-hoc `curl`) attach to the same network to
   reach the `.test` aliases.

---

## Install

Python ≥ 3.11, a container engine (Docker or Podman). Clone with submodules:

```bash
git clone --recurse-submodules <this-repo>
cd restricted-crawl-cache-serve

# Venv (example location — feel free to put it anywhere)
python3 -m venv ~/venvs/rccs
source ~/venvs/rccs/bin/activate

pip install -U pip
pip install -e ".[archi,dev]"
playwright install chromium      # archi's SSO provider uses headless Chromium
```

The package exposes a `rccs` console script after `pip install -e .`, so
the examples below use `rccs ...` directly.

---

## CLI

All subcommands share the same global options. Config path can be passed
**before or after** the subcommand:

```bash
rccs -c examples/basic-crab/config.yaml parse       # both forms
rccs parse -c examples/basic-crab/config.yaml       # are equivalent
```

| Subcommand   | Action                                                |
|--------------|-------------------------------------------------------|
| `parse`      | Validate Archi config + print the crawl plan          |
| `crawl`      | Run Scrapy with caching middleware                    |
| `generate`   | Emit `compose.yaml` + `nginx/sites/*.conf`            |
| `run`        | `parse` → `crawl` → `generate` in one shot            |
| `net up`     | Create the private `restricted_mirror` network        |
| `net down`   | Remove the private `restricted_mirror` network        |

The container engine used by `rccs net …` is auto-detected (`podman`
first, then `docker`); override with `RCCS_CONTAINER_ENGINE`.

Global flags (each has an environment-variable fallback):

| Flag                     | Env var                 | Default      | Meaning                                                                 |
|--------------------------|-------------------------|--------------|-------------------------------------------------------------------------|
| `-c`, `--config`         | —                       | *required*   | Path to an Archi deployment YAML                                        |
| `--mirror-root`          | `MIRROR_ROOT`           | `./mirror`   | Where cached content is written                                         |
| `--generated-output-dir` | `GENERATED_OUTPUT_DIR`  | `.`          | Where `compose.yaml` and `nginx/sites/` are written                     |
| `--archi-root`           | `ARCHI_ROOT`            | *unset*      | Root of the archi submodule (for `input_lists` relative paths)          |
| `--benchmark`            | —                       | off          | Minimize delays for fast re-crawl of already-cached URLs                |
| `-v`, `--verbose`        | —                       | off          | Debug logging                                                           |

Auth secrets (read by archi's `CERNSSOProvider`):

| Env var        | Notes                                              |
|----------------|----------------------------------------------------|
| `SSO_USERNAME` | CERN SSO username                                  |
| `SSO_PASSWORD` | CERN SSO password                                  |

---

## Example — shared mirror at `/shared/rccs/`

This is the workflow I use day to day. Cache content under
`/shared/rccs/mirror` and emit the generated compose/nginx files under
`/shared/rccs/`, which is where they get mounted from:

- `/shared/rccs/compose.yaml`
- `/shared/rccs/nginx/sites/*.conf`

All `rccs` commands run from the project checkout; only the **outputs**
live under `/shared/rccs/`.

### 1. Export secrets + shared paths

```bash
export SSO_USERNAME=donut
export SSO_PASSWORD='••••••••'
export MIRROR_ROOT=/shared/rccs/mirror
export GENERATED_OUTPUT_DIR=/shared/rccs
mkdir -p "$MIRROR_ROOT" "$GENERATED_OUTPUT_DIR"
```

> `SSO_USERNAME` / `SSO_PASSWORD` are read by archi's `CERNSSOProvider`
> (see `archi/src/data_manager/collectors/scrapers/auth/cern_sso.py`).
> `MIRROR_ROOT` and `GENERATED_OUTPUT_DIR` are picked up automatically by
> the `rccs` CLI when the matching flags are not supplied.
> They are **not** committed anywhere; keep them in your shell/secret
> manager.

### 2. Inspect the plan

```bash
rccs parse -c examples/basic-crab/config.yaml
```

The env vars are applied automatically; no extra flags needed. The output
header will show the resolved `Mirror root` and `Generated outdir`.

### 3. Crawl + generate + serve

```bash
# Crawl-only (can run alongside generate in another terminal).
rccs crawl -c examples/basic-crab/config.yaml

# Emit /shared/rccs/compose.yaml + /shared/rccs/nginx/sites/*.conf
rccs generate -c examples/basic-crab/config.yaml

# Full pipeline (parse + crawl + generate) in one command.
rccs run -c examples/basic-crab/config.yaml
```

If you'd rather be explicit (or skip the env vars), pass flags instead:

```bash
rccs run -c examples/basic-crab/config.yaml \
    --mirror-root /shared/rccs/mirror \
    --generated-output-dir /shared/rccs
```

### 4. Create the private network (one-time)

`restricted_mirror` is declared `external: true` in the generated
compose, and created with `--internal` so it has **no egress**. Create
it once:

```bash
rccs net up
# equivalent to:  podman network create --internal restricted_mirror
```

### 5. Start nginx

Volume paths are absolute inside `compose.yaml`, so you don't have to
`cd` first:

```bash
podman compose -f "$GENERATED_OUTPUT_DIR/compose.yaml" up -d
podman compose -f "$GENERATED_OUTPUT_DIR/compose.yaml" ps
# or: docker compose -f "$GENERATED_OUTPUT_DIR/compose.yaml" up -d
```

Inspect the baked-in binds:

```bash
grep -A1 volumes "$GENERATED_OUTPUT_DIR/compose.yaml"
#   volumes:
#     - /shared/rccs/mirror:/usr/share/nginx/html:ro
#     - /shared/rccs/nginx/sites:/etc/nginx/conf.d:ro
```

### 6. Test from another container on the mirror network

The network is **internal** (no egress) and **has no host port**. The
only way in is to join the network from another container. `rccs net up`
created it as `restricted_mirror` (no project prefix).

```bash
# one-liner curl helper that joins the same network
rcurl() {
  podman run -it --rm --no-hosts \
      --network restricted_mirror curlimages/curl curl -v "$@"
}

rcurl http://twiki.cern.test/twiki/bin/view/CMSPublic/SWGuide/
rcurl http://cms-talk.web.cern.test/c/offcomp/comptools/87.json?page=3
```

`--no-hosts` prevents your host `/etc/hosts` from leaking `127.0.0.1`
mappings into the curl container so the container-network DNS wins.

### 7. Bridge archi into the same network

To let archi's `data_manager` crawl `*.test` directly, attach its
container(s) to `restricted_mirror`. Either run ad-hoc:

```bash
podman run -it --rm --no-hosts \
    --network restricted_mirror \
    -v "$PWD:/work" -w /work \
    <archi-image> python -m data_manager.run --base http://twiki.cern.test
```

…or, in archi's own compose file, declare the network as external:

```yaml
services:
  data_manager:
    networks:
      - restricted_mirror    # for *.test DNS, no egress
      - default              # only if the service also needs internet

networks:
  restricted_mirror:
    external: true
```

### 8. Tear down

```bash
podman compose -f "$GENERATED_OUTPUT_DIR/compose.yaml" down
rccs net down              # only after all consumers have detached
```

### 9. Benchmark mode

For re-runs against cached content:

```bash
rccs crawl -c examples/basic-crab/config.yaml --benchmark
```

This caps per-request delays at 1 s.

---

## Standalone Scrapy (debug a single spider)

```bash
cd crawler
SSO_USERNAME=$SSO_USERNAME SSO_PASSWORD=$SSO_PASSWORD scrapy crawl twiki
```

---

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
               <MIRROR_ROOT>/<site>/<path>[__q__<query>]
                        │
                        ▼
              ComposeGenerator + NginxGenerator
              <GENERATED_OUTPUT_DIR>/compose.yaml
              <GENERATED_OUTPUT_DIR>/nginx/sites/*.conf
                        │
                        ▼
           (docker|podman) compose up -d
            nginx serves *.cern.test on an
            internal network "restricted_mirror"
```

---

## Project layout

```
restricted-crawl-cache-serve/
  archi/                         # git submodule → nausikt/archi
  crawler/
    scrapy.cfg                   # points to archi's settings.py
    rccs/
      cli.py                     # `rccs` entry point
      config_adapter.py          # Archi YAML → RCCSConfig
      url_rewriter.py            # domain / scheme rewriting
      domain_mapper.py           # auto-detect domain → .test mapping
    middlewares/
      cache_raw.py               # MIME-aware caching middleware
  generators/
    compose.py                   # compose.yaml generator
    nginx.py                     # per-site nginx conf generator
  templates/
    compose.yaml.j2
    nginx-site.conf.j2
    nginx-shared.conf.j2         # `map $args $rccs_qsuffix`
  examples/
    basic-crab/config.yaml       # sample Archi deployment config
  pyproject.toml
```

Spiders, Scrapy settings, auth middlewares, and pipelines all come from
the archi submodule (`src.data_manager.collectors.scrapers.*`). RCCS only
adds `CacheRawDownloaderMiddleware` and the URL rewriting / generation
layer.

Generated outputs (`mirror/`, `nginx/sites/`, `compose.yaml`) are
`.gitignore`d.

---

## URL rewriting

From seed URLs and site configs, RCCS builds a `domain_map`:

- `twiki.cern.ch` → `twiki.cern.test`
- `cms-talk.web.cern.ch` → `cms-talk.web.cern.test`

The TLD is replaced with `.test` and `https` is downgraded to `http` for
local serving. Rewriting is applied only to HTML/XHTML bodies; JSON/RSS
payloads are preserved verbatim.

---

## Query-string cache layout

The middleware preserves query semantics offline by encoding the query
string into the filename:

| URL                                                       | On-disk path                                              |
|-----------------------------------------------------------|-----------------------------------------------------------|
| `…/87.json`                                               | `…/87.json`                                               |
| `…/87.json?page=3`                                        | `…/87.json__q__page-3`                                    |
| `…/87.json?page=3&order=asc`                              | `…/87.json__q__page-3__order-asc`                         |
| `…/WebHome?rev=12`                                        | `…/WebHome/index.html__q__rev-12`                         |

Nginx uses a shared `map $args $rccs_qsuffix { … }` block (emitted as
`nginx/sites/_rccs-shared.conf`) plus `try_files $uri$rccs_qsuffix $uri`
to serve these files as if they came from a dynamic backend. Extend that
`map` file with regex entries for any other query shapes your sites use;
unmapped queries fall back to the no-query file.

---

## Supported content types

- **Rewritten HTML:** `text/html`, `application/xhtml+xml`
- **Raw text (no rewrite):** `application/json`, `application/rss+xml`,
  `application/atom+xml`, `application/xml`, `text/xml`, `text/plain`,
  `text/csv`, `text/tab-separated-values`, `text/markdown`
- **Documents:** PDF, DOC/DOCX, PPT/PPTX, XLS/XLSX, ODT/ODP/ODS, RTF, EPUB
- **Images:** PNG, JPEG, GIF, WebP, SVG, BMP, ICO, TIFF, AVIF, HEIC/HEIF, APNG
- **Generic downloads:** `application/octet-stream` (and similar) are
  routed based on URL extension.

Unknown types are logged at DEBUG and skipped — the crawl continues.

---

## Contributors

- Krittin Phornsiricharoenphant (<krittin.phornsiricharoenphant@cern.ch>)
