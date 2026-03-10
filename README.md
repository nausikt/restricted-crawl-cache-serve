# Restricted Crawl Cache and Serve (RCCS)
Restricted Crawl Cache Serve (RCCS) for internal RAG repetitive benchmarking. Includes a static mirror server and natural Squid proxy caching as PoC.

*P.S Especially for sensitive services e.g CERN TWiki Public/Private, CERN SSO private Discourse, etc.*

## Get Started
```bash
cd crawler
scrapy crawl twiki

# Serving mirror separately
docker compose up -d
```
