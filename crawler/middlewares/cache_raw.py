"""
CacheRawDownloaderMiddleware — saves every HTTP response to disk as a
local-serveable mirror with rewritten URLs.

Middleware ordering
-------------------
Request path (outbound):
    500  AuthDownloaderMiddleware   ← injects cookies/tokens
    510  CacheRawDownloaderMiddleware ← no-op on requests
    550  RetryMiddleware
    600  RedirectMiddleware

Response path (inbound — reversed):
    600  RedirectMiddleware
    550  RetryMiddleware
    510  CacheRawDownloaderMiddleware ← saves response to disk
    500  AuthDownloaderMiddleware     ← checks for auth failures

The middleware saves a *copy* of the response body to disk (with URL
rewriting for HTML).  The Scrapy Response object is returned unmodified
so spiders still see original URLs for correct link extraction.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from scrapy.http import Request, Response

from crawler.rccs.url_rewriter import URLRewriter

if TYPE_CHECKING:
    from scrapy import Spider
    from scrapy.crawler import Crawler

logger = logging.getLogger(__name__)


class CacheRawDownloaderMiddleware:
    """Save every response to disk as a local-serveable mirror."""

    def __init__(self, mirror_root: str, url_rewriter: URLRewriter | None) -> None:
        self.mirror_root = Path(mirror_root)
        self.rewriter = url_rewriter

    @classmethod
    def from_crawler(cls, crawler: "Crawler") -> "CacheRawDownloaderMiddleware":
        return cls(
            mirror_root=crawler.settings.get("RCCS_MIRROR_ROOT", "./mirror"),
            url_rewriter=crawler.settings.get("RCCS_URL_REWRITER"),
        )

    # ------------------------------------------------------------------
    # process_request — no-op, we only care about responses
    # ------------------------------------------------------------------

    def process_request(self, request: Request, spider: "Spider") -> None:
        return None

    # ------------------------------------------------------------------
    # process_response — save to disk
    # ------------------------------------------------------------------

    def process_response(
        self, request: Request, response: Response, spider: "Spider"
    ) -> Response:
        content_type = response.headers.get(b"Content-Type", b"").decode(errors="replace")

        if "text/html" in content_type:
            self._save_html(response, spider)
        elif "application/pdf" in content_type:
            self._save_pdf(response, spider)
        else:
            logger.debug(
                "CacheRaw: skipping %s (content-type: %s)", response.url, content_type
            )

        return response

    # ------------------------------------------------------------------
    # HTML: rewrite URLs then save
    # ------------------------------------------------------------------

    def _save_html(self, response: Response, spider: "Spider") -> None:
        out_path = self._output_path(response.url, "index.html")
        try:
            html = response.text
            if self.rewriter:
                html = self.rewriter.rewrite_html(html)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(html, encoding="utf-8")
            logger.info("CacheRaw: saved HTML %s -> %s", response.url, out_path)
        except Exception as exc:
            logger.warning("CacheRaw: failed to save HTML %s: %s", response.url, exc)

    # ------------------------------------------------------------------
    # PDF: save raw bytes (no rewriting)
    # ------------------------------------------------------------------

    def _save_pdf(self, response: Response, spider: "Spider") -> None:
        out_path = self._output_path(response.url, None)
        if not out_path.suffix:
            out_path = out_path.with_suffix(".pdf")
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(response.body)
            logger.info("CacheRaw: saved PDF  %s -> %s", response.url, out_path)
        except Exception as exc:
            logger.warning("CacheRaw: failed to save PDF %s: %s", response.url, exc)

    # ------------------------------------------------------------------
    # Path computation
    # ------------------------------------------------------------------

    def _output_path(self, url: str, default_filename: str | None) -> Path:
        """Map a URL to a filesystem path under mirror_root.

        Layout:  mirror/<site_key>/<url_path>[/index.html]
        where site_key is the first segment of the hostname (e.g. "twiki").
        """
        parsed = urlparse(url)
        host = (parsed.hostname or "unknown").lower().rstrip(".")
        site_key = host.split(".")[0]

        url_path = parsed.path.lstrip("/")
        if not url_path:
            url_path = ""

        base = self.mirror_root / site_key / url_path

        if default_filename:
            if base.suffix:
                return base
            return base / default_filename

        return base
