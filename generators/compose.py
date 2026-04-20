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
    mirror_root: str | Path = "./mirror",
    nginx_sites_dir: str | Path = "./nginx/sites",
    generated_output_dir: str | Path = ".",
    network_name: str = "restricted_mirror",
) -> Path:
    """Render compose.yaml from domain mapping.

    The mirror is served only on the private (external) container
    network ``network_name``.  No host ports are published — consumers
    must attach to the same network.  Create it once with
    ``rccs net up`` (or ``podman network create --internal <name>``)
    before running ``compose up``.

    Args:
        domain_map:            {original_domain: test_domain}
        output_path:           where to write the composed YAML
        mirror_root:           host path bound into nginx as
                               ``/usr/share/nginx/html`` (baked in as an
                               absolute path for portability).
        nginx_sites_dir:       host path bound into nginx as
                               ``/etc/nginx/conf.d`` (absolute).
        generated_output_dir:  rendered in a header comment so the file
                               documents its origin / ``$GENERATED_OUTPUT_DIR``.
        network_name:          compose network name, rendered as
                               ``external: true`` (default
                               ``"restricted_mirror"``).

    Returns:
        Path to the generated file.
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )
    template = env.get_template("compose.yaml.j2")

    aliases = sorted(domain_map.values())
    mirror_root_abs = Path(mirror_root).expanduser().resolve()
    nginx_sites_abs = Path(nginx_sites_dir).expanduser().resolve()
    generated_abs = Path(generated_output_dir).expanduser().resolve()

    rendered = template.render(
        aliases=aliases,
        network_name=network_name,
        mirror_root=str(mirror_root_abs),
        nginx_sites_dir=str(nginx_sites_abs),
        generated_output_dir=str(generated_abs),
    )

    out = Path(output_path)
    out.write_text(rendered, encoding="utf-8")
    logger.info("Generated compose.yaml -> %s", out)
    return out
