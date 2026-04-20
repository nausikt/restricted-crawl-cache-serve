"""
URL/domain rewriting engine for cached HTML content.

Replaces real domains with .test equivalents and rewrites https -> http
so that cached pages can be served locally by nginx.
"""
from __future__ import annotations

import re
from typing import Dict


class URLRewriter:
    """Rewrite domains and scheme in HTML text.

    The replacement order is longest-domain-first to avoid partial matches
    (e.g. rewriting "cern.ch" inside "twiki.cern.ch" prematurely).
    """

    def __init__(self, domain_map: Dict[str, str]) -> None:
        self.domain_map = domain_map
        self._replacements = self._build_replacement_pairs()

    def _build_replacement_pairs(self) -> list[tuple[str, str]]:
        """Pre-compute (old, new) pairs sorted longest-first."""
        pairs: list[tuple[str, str]] = []
        for original, replacement in sorted(
            self.domain_map.items(), key=lambda kv: len(kv[0]), reverse=True
        ):
            pairs.append((f"https://{original}", f"http://{replacement}"))
            pairs.append((f"http://{original}", f"http://{replacement}"))
            pairs.append((f"//{original}", f"//{replacement}"))
        return pairs

    def rewrite_html(self, html: str) -> str:
        """Apply all domain+scheme rewrites to an HTML string."""
        for old, new in self._replacements:
            html = html.replace(old, new)
        return html

    @property
    def test_domains(self) -> list[str]:
        """All .test domain aliases (useful for compose/nginx generation)."""
        return sorted(self.domain_map.values())

    @property
    def original_domains(self) -> list[str]:
        return sorted(self.domain_map.keys())

    def site_key_for_domain(self, domain: str) -> str:
        """Derive a short site key from a domain for directory naming.

        twiki.cern.ch        -> twiki
        cms-talk.web.cern.ch -> cms-talk
        deepwiki.com         -> deepwiki
        """
        parts = domain.split(".")
        return parts[0]
