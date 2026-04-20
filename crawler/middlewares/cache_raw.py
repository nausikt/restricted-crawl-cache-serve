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

Supported content types
-----------------------
HTML-like (URL-rewritten on save):
    text/html, application/xhtml+xml

Textual (saved raw, no rewriting — preserves API semantics):
    application/json, application/rss+xml, application/atom+xml,
    application/xml, text/xml, text/plain, text/csv,
    text/tab-separated-values, text/markdown

Binary documents:
    application/pdf,
    application/msword (.doc),
    application/vnd.openxmlformats-officedocument.wordprocessingml.document (.docx),
    application/vnd.ms-powerpoint (.ppt),
    application/vnd.openxmlformats-officedocument.presentationml.presentation (.pptx),
    application/vnd.ms-excel (.xls),
    application/vnd.openxmlformats-officedocument.spreadsheetml.sheet (.xlsx),
    application/vnd.oasis.opendocument.text (.odt),
    application/vnd.oasis.opendocument.presentation (.odp),
    application/vnd.oasis.opendocument.spreadsheet (.ods),
    application/rtf (.rtf),
    application/epub+zip (.epub)

Images (saved as raw bytes so embedded references in HTML still load):
    image/png, image/jpeg, image/gif, image/webp, image/svg+xml,
    image/bmp, image/x-icon, image/tiff, image/avif, image/heic,
    image/heif, image/apng

Fallback
--------
If the response's Content-Type is missing, ``application/octet-stream``,
``binary/octet-stream``, or otherwise unknown, the middleware inspects the
URL path's extension (e.g. ``.pdf``, ``.pptx``) and routes to the
corresponding handler when recognized.  This handles servers that serve
document downloads with a generic or missing Content-Type.

Query strings
-------------
URLs with a query string (e.g. ``...87.json?page=3``) are saved with a
filesystem-safe suffix appended to the filename so each distinct query
produces its own cached file.  Encoding:

    ?page=3                   -> __q__page-3
    ?page=3&order=asc         -> __q__page-3__order-asc

The companion nginx config uses a ``map $args $rccs_qsuffix`` block +
``try_files $uri$rccs_qsuffix $uri`` to serve these as if they were
live backend responses.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from scrapy.http import Request, Response

from crawler.rccs.url_rewriter import URLRewriter

if TYPE_CHECKING:
    from scrapy import Spider
    from scrapy.crawler import Crawler

logger = logging.getLogger(__name__)


# MIME types that should have HTML URL rewriting applied before save.
_REWRITE_HTML_MIMES = frozenset({
    "text/html",
    "application/xhtml+xml",
})

# MIME types saved as raw text (no rewriting).  Value is the file extension
# appended when the URL path has no extension of its own.
_TEXT_MIMES: dict[str, str] = {
    "application/json":              ".json",
    "application/rss+xml":           ".rss",
    "application/atom+xml":          ".atom",
    "application/xml":               ".xml",
    "text/xml":                      ".xml",
    "text/plain":                    ".txt",
    "text/csv":                      ".csv",
    "text/tab-separated-values":     ".tsv",
    "text/markdown":                 ".md",
    "text/x-markdown":               ".md",
}

# MIME types saved as raw bytes — document formats and images so the
# mirror can host PDFs, Office docs, OpenDocument, ebooks, and all the
# image formats embedded in HTML pages.
_BINARY_MIMES: dict[str, str] = {
    # PDF
    "application/pdf":                                                                ".pdf",
    # Microsoft Office (legacy + OOXML)
    "application/msword":                                                             ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":        ".docx",
    "application/vnd.ms-powerpoint":                                                  ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation":      ".pptx",
    "application/vnd.ms-excel":                                                       ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":              ".xlsx",
    # OpenDocument
    "application/vnd.oasis.opendocument.text":                                        ".odt",
    "application/vnd.oasis.opendocument.presentation":                                ".odp",
    "application/vnd.oasis.opendocument.spreadsheet":                                 ".ods",
    # Misc documents
    "application/rtf":                                                                ".rtf",
    "text/rtf":                                                                       ".rtf",
    "application/epub+zip":                                                           ".epub",
    # Images (common raster + vector)
    "image/png":                                                                      ".png",
    "image/jpeg":                                                                     ".jpg",
    "image/pjpeg":                                                                    ".jpg",
    "image/gif":                                                                      ".gif",
    "image/webp":                                                                     ".webp",
    "image/svg+xml":                                                                  ".svg",
    "image/bmp":                                                                      ".bmp",
    "image/x-icon":                                                                   ".ico",
    "image/vnd.microsoft.icon":                                                       ".ico",
    "image/tiff":                                                                     ".tiff",
    "image/avif":                                                                     ".avif",
    "image/heic":                                                                     ".heic",
    "image/heif":                                                                     ".heif",
    "image/apng":                                                                     ".apng",
}

# Generic / unknown Content-Type values that should trigger URL-extension
# based dispatch instead of being treated as "unknown → skip".  Many file
# downloads come through with one of these.
_GENERIC_MIMES = frozenset({
    "",
    "application/octet-stream",
    "binary/octet-stream",
    "application/download",
    "application/force-download",
    "application/x-download",
    "application/unknown",
})

# URL path extensions that map back to a known handler.  Used when the
# server returns a generic/missing Content-Type.  Kept in sync with
# _TEXT_MIMES / _BINARY_MIMES above.
_EXT_TO_MIME: dict[str, str] = {
    # Binary docs
    ".pdf":      "application/pdf",
    ".doc":      "application/msword",
    ".docx":     "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt":      "application/vnd.ms-powerpoint",
    ".pptx":     "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls":      "application/vnd.ms-excel",
    ".xlsx":     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".odt":      "application/vnd.oasis.opendocument.text",
    ".odp":      "application/vnd.oasis.opendocument.presentation",
    ".ods":      "application/vnd.oasis.opendocument.spreadsheet",
    ".rtf":      "application/rtf",
    ".epub":     "application/epub+zip",
    # Images
    ".png":      "image/png",
    ".jpg":      "image/jpeg",
    ".jpeg":     "image/jpeg",
    ".jpe":      "image/jpeg",
    ".jfif":     "image/jpeg",
    ".gif":      "image/gif",
    ".webp":     "image/webp",
    ".svg":      "image/svg+xml",
    ".svgz":     "image/svg+xml",
    ".bmp":      "image/bmp",
    ".ico":      "image/x-icon",
    ".tif":      "image/tiff",
    ".tiff":     "image/tiff",
    ".avif":     "image/avif",
    ".heic":     "image/heic",
    ".heif":     "image/heif",
    ".apng":     "image/apng",
    # Text
    ".json":     "application/json",
    ".rss":      "application/rss+xml",
    ".atom":     "application/atom+xml",
    ".xml":      "application/xml",
    ".txt":      "text/plain",
    ".csv":      "text/csv",
    ".tsv":      "text/tab-separated-values",
    ".md":       "text/markdown",
    ".markdown": "text/markdown",
}


_QS_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _encode_query(qs: str) -> str:
    """Encode a URL query string into a filesystem-safe filename suffix.

    Returns an empty string for an empty query.  Otherwise returns a string
    of the form ``__q__<k>-<v>[__<k>-<v>...]`` where every character outside
    ``[A-Za-z0-9._-]`` is replaced with ``_``.

    The ``__q__`` prefix and ``-`` key/value separator are chosen so that
    the nginx side can reconstruct the suffix from ``$args`` with a simple
    ``map`` block.
    """
    if not qs:
        return ""
    parts: list[str] = []
    for kv in qs.split("&"):
        k, _, v = kv.partition("=")
        k = _QS_SAFE.sub("_", k)
        v = _QS_SAFE.sub("_", v)
        parts.append(f"{k}-{v}" if v else k)
    return "__q__" + "__".join(parts)


def _parse_mime(content_type_header: str) -> str:
    """Extract the lowercase MIME type from a Content-Type header value."""
    return content_type_header.split(";", 1)[0].strip().lower()


def _url_extension(url: str) -> str:
    """Return the lowercase extension of the URL path (including leading dot).

    Returns ``""`` if the URL path has no extension.
    """
    path = urlparse(url).path
    _, dot, ext = path.rpartition(".")
    if not dot:
        return ""
    # Guard against dots inside directory names (e.g. "foo.bar/baz")
    if "/" in ext:
        return ""
    return f".{ext.lower()}"


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
    # process_response — dispatch by MIME type
    # ------------------------------------------------------------------

    def process_response(
        self, request: Request, response: Response, spider: "Spider"
    ) -> Response:
        raw_ct = response.headers.get(b"Content-Type", b"").decode(errors="replace")
        mime = _parse_mime(raw_ct)

        # Fall back to URL-extension dispatch when the server didn't tell us
        # (common for octet-stream downloads of Office docs, PDFs, etc.).
        if mime in _GENERIC_MIMES:
            ext = _url_extension(response.url)
            guessed = _EXT_TO_MIME.get(ext)
            if guessed:
                logger.debug(
                    "CacheRaw: Content-Type=%r for %s, using extension %s -> %s",
                    raw_ct, response.url, ext, guessed,
                )
                mime = guessed

        if mime in _REWRITE_HTML_MIMES:
            self._save_html(response, spider)
        elif mime in _TEXT_MIMES:
            self._save_text(response, spider, mime, _TEXT_MIMES[mime])
        elif mime in _BINARY_MIMES:
            self._save_binary(response, spider, mime, _BINARY_MIMES[mime])
        else:
            logger.debug(
                "CacheRaw: skipping %s (mime: %s)", response.url, mime or "<none>"
            )

        return response

    # ------------------------------------------------------------------
    # HTML: rewrite URLs then save
    # ------------------------------------------------------------------

    def _save_html(self, response: Response, spider: "Spider") -> None:
        out_path = self._output_path(response.url, default_filename="index.html")
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
    # Raw text (JSON, RSS/Atom, XML, plain): save bytes verbatim,
    # no URL rewriting (API payload semantics must be preserved).
    # ------------------------------------------------------------------

    def _save_text(
        self, response: Response, spider: "Spider", mime: str, fallback_ext: str
    ) -> None:
        out_path = self._output_path(response.url, fallback_ext=fallback_ext)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(response.body)
            logger.info(
                "CacheRaw: saved %s %s -> %s", mime, response.url, out_path
            )
        except Exception as exc:
            logger.warning(
                "CacheRaw: failed to save %s %s: %s", mime, response.url, exc
            )

    # ------------------------------------------------------------------
    # Binary (PDF, ...): save raw bytes
    # ------------------------------------------------------------------

    def _save_binary(
        self, response: Response, spider: "Spider", mime: str, fallback_ext: str
    ) -> None:
        out_path = self._output_path(response.url, fallback_ext=fallback_ext)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(response.body)
            logger.info(
                "CacheRaw: saved %s %s -> %s", mime, response.url, out_path
            )
        except Exception as exc:
            logger.warning(
                "CacheRaw: failed to save %s %s: %s", mime, response.url, exc
            )

    # ------------------------------------------------------------------
    # Path computation
    # ------------------------------------------------------------------

    def _output_path(
        self,
        url: str,
        default_filename: str | None = None,
        fallback_ext: str | None = None,
    ) -> Path:
        """Map a URL to a filesystem path under ``mirror_root``.

        Layout:  ``mirror/<site_key>/<url_path>[<default|ext>][<query-suffix>]``

        - ``site_key`` is the first segment of the hostname (e.g. "twiki").
        - If the URL path has no file extension, ``default_filename`` is
          appended (for HTML) or ``fallback_ext`` is set as the suffix
          (for JSON/PDF/etc.).
        - A non-empty query string is encoded via :func:`_encode_query`
          and appended to the *filename* so each distinct query maps to
          a distinct file.
        """
        parsed = urlparse(url)
        host = (parsed.hostname or "unknown").lower().rstrip(".")
        site_key = host.split(".")[0]

        url_path = parsed.path.lstrip("/")
        base = self.mirror_root / site_key / url_path if url_path else self.mirror_root / site_key

        if base.suffix:
            file_path = base
        elif default_filename:
            file_path = base / default_filename
        elif fallback_ext:
            file_path = base.with_suffix(fallback_ext)
        else:
            file_path = base

        qsuffix = _encode_query(parsed.query)
        if qsuffix:
            file_path = file_path.with_name(file_path.name + qsuffix)

        return file_path
