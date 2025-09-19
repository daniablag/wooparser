from __future__ import annotations
from typing import List
from .models import Product

REQUIRED_FIELDS: List[str] = ["external_id", "name", "type"]


def validate_product(product: Product) -> List[str]:
    issues: List[str] = []
    for f in REQUIRED_FIELDS:
        if getattr(product, f, None) in (None, ""):
            issues.append(f"Отсутствует обязательное поле: {f}")
    if product.type == "simple" and product.regular_price is None:
        issues.append("Для simple продукта требуется regular_price")
    return issues


def to_woo_product_payload(product: Product, status: str = "draft") -> dict:
    payload: dict = {
        "name": product.name,
        "status": status,
        "type": product.type,
        "description": product.description_html or "",
        "short_description": product.short_description_html or "",
        "meta_data": [
            {"key": "external_id", "value": product.external_id},
        ],
    }
    if product.sku:
        payload["sku"] = product.sku
    # Галерея/изображения товара: Woo позволяет передавать удалённые src
    if product.images:
        payload["images"] = [{"src": img.url, "alt": img.alt or product.name} for img in product.images]
    if product.type == "simple":
        if product.regular_price is not None:
            payload["regular_price"] = f"{product.regular_price:.2f}"
        if product.sale_price is not None:
            payload["sale_price"] = f"{product.sale_price:.2f}"
        if product.stock_quantity is not None:
            payload["manage_stock"] = True
            payload["stock_quantity"] = product.stock_quantity
    else:
        # Для variable: атрибуты и вариации задаём в месте вызова (push), здесь только общие поля
        pass
    return payload
