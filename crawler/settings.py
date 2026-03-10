from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
CONFIG = yaml.safe_load(CONFIG_PATH.read_text())

BOT_NAME = "rccs_crawler"

SPIDER_MODULES = ["spiders"]
NEWSPIDER_MODULE = "spiders"

ROBOTSTXT_OBEY = CONFIG["crawl"].get("obey_robots", True)
DOWNLOAD_DELAY = CONFIG["crawl"].get("crawl_delay", 60)

CONCURRENT_REQUESTS = CONFIG["crawl"].get("concurrent_requests", 1)
CONCURRENT_REQUESTS_PER_DOMAIN = 1

USER_AGENT = CONFIG["crawl"].get("user_agent", BOT_NAME)

LOG_LEVEL = "INFO"
DOWNLOAD_TIMEOUT = 30
RETRY_ENABLED = True
RETRY_TIMES = 2

RCCS_CONFIG = CONFIG
