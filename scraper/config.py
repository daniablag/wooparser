from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    wp_base_url: str
    wc_consumer_key: Optional[str]
    wc_consumer_secret: Optional[str]
    wp_user: Optional[str]
    wp_app_password: Optional[str]
    wc_api_version: str = "wc/v3"
    requests_timeout: int = 30
    rate_limit_rps: float = 0.5
    download_media: bool = True
    headless: bool = True
    db_path: Path = Path("wooparser.db")


def str_to_bool(val: Optional[str], default: bool) -> bool:
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y"}


def get_settings() -> Settings:
    return Settings(
        wp_base_url=os.getenv("WP_BASE_URL", "").rstrip("/"),
        wc_consumer_key=os.getenv("WC_CONSUMER_KEY"),
        wc_consumer_secret=os.getenv("WC_CONSUMER_SECRET"),
        wp_user=os.getenv("WP_USER"),
        wp_app_password=os.getenv("WP_APP_PASSWORD"),
        wc_api_version=os.getenv("WC_API_VERSION", "wc/v3"),
        requests_timeout=int(os.getenv("REQUESTS_TIMEOUT", "30")),
        rate_limit_rps=float(os.getenv("RATE_LIMIT_RPS", "0.5")),
        download_media=str_to_bool(os.getenv("DOWNLOAD_MEDIA"), True),
        headless=str_to_bool(os.getenv("HEADLESS"), True),
        db_path=Path(os.getenv("DB_PATH", "wooparser.db")),
    )
