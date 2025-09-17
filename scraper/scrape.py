from __future__ import annotations
from typing import List
from .models import Product, Image

FIXTURE_URL = "https://example.com/fixture"


def scrape_product(url: str, profile: str) -> Product:
    if url == FIXTURE_URL:
        return Product(
            external_id="fixture-001",
            name="Fixture T-Shirt",
            sku="FIX-TS-001",
            description_html="<p>Фикстурный товар для теста загрузки</p>",
            short_description_html="Фикстура",
            categories=[],
            tags=[],
            images=[],
            attributes={},
            default_attributes={},
            type="simple",
            regular_price=19.99,
            sale_price=None,
            stock_quantity=10,
            variations=[],
        )
    # Заглушка для реальных парсеров (DOM/JSON-LD/Playwright)
    raise NotImplementedError("Парсинг реальных доноров пока не реализован в минимальном E2E")


def collect_category_urls(category_url: str, profile: str, limit: int = 20, offset: int = 0) -> List[str]:
    # Для минимального E2E используем фикстуру
    urls = [FIXTURE_URL]
    return urls[offset : offset + limit]


def cluster_preview(profile: str, from_category: str, limit: int = 50):
    # Для фикстуры один кластер
    return [{"parent_key": "fixture-001", "urls": [FIXTURE_URL]}]


def iterate_urls_from_file(path, limit: int = 50, offset: int = 0):
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return []
    lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return lines[offset : offset + limit]
