from pathlib import Path
from urllib.parse import urlparse
from functools import wraps
from typing import TypedDict, NotRequired
import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
CONFIG = yaml.safe_load(CONFIG_PATH.read_text())

class CustomScrapySettings(TypedDict):
    ROBOTSTXT_OBEY: bool
    DOWNLOAD_DELAY: int | float
    MAX_DEPTH: int
    CONCURRENT_REQUESTS: int
    CONCURRENT_REQUESTS_PER_DOMAIN: int
    USER_AGENT: str
    MIRROR_ROOT: str
    PROXY_ENABLED: bool
    HTTP_PROXY: NotRequired[str | None]
    HTTPS_PROXY: NotRequired[str | None]

def get_site_config(site_name: str) -> dict:
    for site in CONFIG.get("sites", []):
        if site.get("name") == site_name:
            return site
    raise ValueError(f"Site '{site_name}' not found in config.yaml")


def build_custom_settings(site: dict) -> CustomScrapySettings:
    crawl = CONFIG.get("crawl", {})
    mirror = CONFIG.get("mirror", {})
    proxy = CONFIG.get("proxy", {})
    site_crawl = site.get("crawl", {})

    merged = {
        **crawl,
        **site_crawl,
    }

    return {
        "ROBOTSTXT_OBEY": merged.get("obey_robots", True),
        "DOWNLOAD_DELAY": merged.get("crawl_delay", 0),
        "MAX_DEPTH": merged.get("max_depth", 1),
        "CONCURRENT_REQUESTS": merged.get("concurrent_requests", 1),
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "USER_AGENT": merged.get("user_agent", "rccs_scrapy"),
        "MIRROR_ROOT": mirror.get("root", "../mirror/"),
        "PROXY_ENABLED": proxy.get("enabled", False),
        "HTTP_PROXY": proxy.get("http"),
        "HTTPS_PROXY": proxy.get("https"),
    }

def site_configured(site_name: str):
    def decorator(cls):
        site = get_site_config(site_name)

        cls.site_name = site_name
        cls.site_enabled = site.get("enabled", False)
        cls.start_urls = site.get("start_urls", [])
        cls.allowed_domains = site.get("allowed_domains", [])
        cls.allowed_path_prefixes = tuple(site.get("allowed_path_prefixes", []))
        cls.custom_settings = {
            **(getattr(cls, "custom_settings", None) or {}),
            **build_custom_settings(site),
        }

        return cls

    return decorator

def after_parse(hook):
    """
    Run the wrapped Scrapy callback first, yield all its outputs,
    then run hook e.g. save the response as mirrored content.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(self, response, *args, **kwargs):
            result = fn(self, response, *args, **kwargs)

            if result is not None:
                yield from result

            hook(self, response)

        return wrapper
    return decorator

def save_as_mirror_response(self, response):
    parsed = urlparse(response.url)
    out_dir = Path(self.custom_settings["MIRROR_ROOT"]) / self.site_name / parsed.path.lstrip("/")
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / "index.html"
    out_file.write_text(response.text, encoding="utf-8")
    self.logger.info("Saved %s -> %s", response.url, out_file)


