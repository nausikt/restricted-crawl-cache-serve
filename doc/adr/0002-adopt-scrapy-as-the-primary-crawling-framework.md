# 2. Adopt Scrapy as the primary crawling framework

Date: 2026-03-20

## Status

Proposed

## Context

The current crawling and scraping architecture operates as a custom synchronous system that has proven functional but exhibits structural limitations:
1. Lack of crawl control & politeness.
2. No first-class support for centralized policy of `per-site rate limiting`, `backpressure`,  `adaptive throttling`.

High risk of:
1. being throttled or banned
2. inefficient crawl scheduling
3. Tight coupling across layers e.g. `Crawling`, `authentication`, `parsing` and `persistence` are a bit intertwined

No clear boundaries between:
1. Auth/session handling
2. Crawling logic
3. Parsing/extraction
4. Output modeling

Results in:
- low reusability
- difficult evolution of individual components
- Missing lifecycle & extensibility model

No standard hooks for:
- request/response processing
- retries, failures, session refresh
- Hard to introduce: `shared crawling mechanisms`, `reusable policies across sites`

The current crawling architecture is working
in Archi consists of multiple scrapers:

- LinkScraper
- SSOScraper
- (SSO)DiscourseScraper
- IndicoScraper
- EOSScraper
- GitScraper
- ...etc

and have single weblist to turn-on/off each mode in scraper manager e.g.
```
https://twiki.cern.ch/twiki/bin/view/CMSPublic/CRAB3ConfigurationFile
sso-https://twiki.cern.ch/twiki/bin/view/CMS/HeavyIon
elog-https://www-enstore.fnal.gov/elog/dCache/
indico-https://indico.cern.ch/event/1623577 (Or may be Indico may have explicit site/policy configuration like keywords/)
```

## Decision

Scrapy will be responsible for:
- request scheduling and concurrency
- crawl lifecycle management
- middleware-based extensibility (auth, retries, headers, etc.)
- built-in politeness mechanisms (AutoThrottle, delays, concurrency limits)

## Rationale

Why Scrapy?

Scrapy provides a battle-tested crawling runtime with:

**Seperation of Concerns:**
- abstractions e.g. Middlewares, Spiders, Parsers, Pipelines, Engine/Scheduler, Downloader.
- encourage ***Open/Closed Principles***

Built-in crawl control
- concurrency limits
- download delay
- AutoThrottle
- retry/backoff
- Middleware architecture
clean separation of concerns:
- auth/session handling
- headers/cookies
- ban avoidance

Pipeline system
→ structured post-processing before persistence

Extensible lifecycle hooks
→ predictable and composable crawling behavior

Asynchronous engine (Twisted-based)
→ efficient I/O without manual async orchestration

Why now?

Reduce Archi's overall Complexity/Footprint.

Robustified

Making static content ingestion robust

Increasing number of sources:
- Twiki
- SSO
- Discourse
- Indico
- ELOG (paginator, iterator)
- Git-based content

The current system will not scale without:
- introducing complexity manually, or
- adopting a framework designed for this problem, scrapy can escalate into scalable Daemon/distributed/queues.

## Consequences

**Positive**
- Clear separation of concerns
- Standardized crawling lifecycle
First-class support for:
- politeness
- backpressure
- retries
- Easier onboarding for contributors (industry-standard tool)
- Embracing open–closed principle

**Negative / Trade-offs**
Learning curve for Scrapy concepts (but Krittin's responsible for supporting these!):
- spiders
- middleware
- pipelines

- Twisted async model

Migration overhead:
- rewriting existing crawlers
- building adapter layer

Debugging complexity:
- asynchronous execution model (in Non-trivial cases)
- middleware interactions
