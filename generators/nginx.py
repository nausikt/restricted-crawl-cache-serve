"""
Auto-generate per-site nginx server configs from domain mapping.

Each site gets its own .conf file under nginx/sites/ with:
  - server_name set to the .test domain alias
  - root pointing at mirror/<site_key>/
  - static try_files for HTML + PDF serving
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _site_key_from_domain(domain: str) -> str:
    """Derive a short directory name from a domain.

    twiki.cern.ch        -> twiki
    cms-talk.web.cern.ch -> cms-talk
    deepwiki.com         -> deepwiki
    """
    return domain.split(".")[0]


def generate_nginx_configs(
    domain_map: Dict[str, str],
    output_dir: str | Path = "nginx/sites",
) -> list[Path]:
    """Render one nginx .conf per site.

    Args:
        domain_map: {original_domain: test_domain}
        output_dir: directory to write .conf files into

    Returns:
        List of paths to generated config files.
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )
    template = env.get_template("nginx-site.conf.j2")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []
    for original_domain, test_domain in sorted(domain_map.items()):
        site_key = _site_key_from_domain(original_domain)
        rendered = template.render(
            server_name=test_domain,
            site_key=site_key,
        )
        conf_path = out_dir / f"{site_key}.conf"
        conf_path.write_text(rendered, encoding="utf-8")
        logger.info("Generated nginx config: %s (server_name=%s)", conf_path, test_domain)
        generated.append(conf_path)

    return generated
