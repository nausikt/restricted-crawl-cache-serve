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
1. Auth/session handling (SSO could be done once in seprate layer, to extract/refresh cookies via Playright or Selenium)
2. Crawling logic
3. Parsing/extraction
4. Output modeling

Results in:
- low reusability
- difficult evolution of individual components
- Missing lifecycle & extensibility model
- No clear conventions enforcing the ***Open/Closed Principle*** and ***Seperation of Concerns***

No standard hooks for:
- request/response processing
- retries, failures, session refresh
- Hard to introduce: `shared crawling mechanisms`, `reusable policies across sites`

Some details of the current crawling architecture Archi consists of multiple scrapers:
- LinkScraper
- SSOScraper
- (SSO)DiscourseScraper
- IndicoScraper
- EOSScraper
- GitScraper
- ...etc

and have a conventional weblist to enable and disable each mode in scraper manager e.g.
```
https://twiki.cern.ch/twiki/bin/view/CMSPublic/CRAB3ConfigurationFile
sso-https://twiki.cern.ch/twiki/bin/view/CMS/HeavyIon
elog-https://www-enstore.fnal.gov/elog/dCache/
indico-https://indico.cern.ch/event/1623577 
## P.S. in Indico case, we may have explicit site/policy configurations like queries, keywords, specific auth/whitelist ...etc
```

## Decision

Scrapy will be responsible for:
- request scheduling and concurrency.
- crawl lifecycle management, seperation of concerns.
- middleware-based extensibility (auth, retries, headers, etc.)
- built-in politeness mechanisms (delays, concurrency limits).
- battle-tested conventions.
- future-proof scalability.

## Rationale

Why Scrapy?

Goal: Make scraping robust, extensible, and sustainable.

Scrapy provides a battle-tested crawling runtime with **Seperation of Concerns**

*See also [Scrapy Architecture](https://docs.scrapy.org/en/latest/topics/architecture.html)*
- abstractions e.g. Middlewares, Spiders, Parsers, Pipelines, Engine/Scheduler, Downloader.
- encourage ***Open/Closed Principles***

<img src="https://github.com/user-attachments/assets/a46eea58-05d5-4080-9a3f-2d1d13965c74" 
     alt="scrapy_architecture_02" 
     width="70%" />

Built-in crawl control
- concurrency limits
- download delay
- retry/backoff
- Middleware architecture
clean separation of concerns:
- auth/session handling
- headers/cookies
- ban avoidance

Pipeline system
→ structured post-processing before persistence

*We preserve **Archi’s ScrapedResource** and **Persistence service** as the output model, while introducing a new adapter layer.*
*This allows new use cases and contributors to evolve the system cleanly.*

Extensible lifecycle hooks
→ predictable and composable crawling behavior

Asynchronous engine (Twisted-based)
→ efficient I/O without manual async orchestration

Why now?

1. Making static content ingestion complete robust.
2. Simplify and reduce Archi’s overall complexity and footprint..
3. A surge of evolving sources coming that could be handled with ***adapter-based*** lifecycle e.g.
- Twiki
- SSO
- Discourse
- Indico
- ELOG (paginator, iterator)
- Git-based content (remains quite the same, possibly be seperate synchronous process)

The current system will not scale without:
- introducing complexity manually, or
- adopting a framework designed for this problem, scrapy can escalate into scalable Daemon/Queues/Distributed manner.

## Consequences

**Positive**
- Clear separation of concerns
- Standardized crawling lifecycle
- Embracing **Open–Closed principle**
- future-proof for scalability

First-class support for:
- politeness
- backpressure
- retries
- Easier onboarding for contributors (industry-standard tool)

**Negative / Trade-offs**
Learning curve for Scrapy concepts:
- spiders
- middleware
- pipelines
- Twisted async model
- Unit-testing modular components becomes easier  

Migration overhead:
- rewriting existing crawlers
- building adapter layer

Debugging complexity:
- asynchronous execution model (in Non-trivial cases)
- middleware interactions
