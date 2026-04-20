"""
Auto-generate compose.yaml from domain mapping.

Produces a self-contained docker compose file with an nginx service
that serves cached content under .test domain aliases.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def generate_compose(
    domain_map: Dict[str, str],
    output_path: str | Path = "compose.yaml",
    mirror_port: int = 8080,
) -> Path:
    """Render compose.yaml from domain mapping.

    Args:
        domain_map: {original_domain: test_domain}
        output_path: where to write the composed YAML
        mirror_port: host port to expose (default 8080)

    Returns:
        Path to the generated file.
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )
    template = env.get_template("compose.yaml.j2")

    aliases = sorted(domain_map.values())

    rendered = template.render(
        aliases=aliases,
        mirror_port=mirror_port,
    )

    out = Path(output_path)
    out.write_text(rendered, encoding="utf-8")
    logger.info("Generated compose.yaml -> %s", out)
    return out
