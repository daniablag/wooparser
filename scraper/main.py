from __future__ import annotations
import json
from pathlib import Path
from typing import List, Optional
import os
import typer
from rich import print as rprint

app = typer.Typer(add_completion=False, help="CLI для парсинга и загрузки в WooCommerce")


@app.callback()
def main_callback(
    download_media: Optional[bool] = typer.Option(
        None, "--download-media/--no-download-media", help="Скачивать медиа (override .env)"
    ),
    headless: Optional[bool] = typer.Option(
        None, "--headless/--no-headless", help="Безголовый браузер для парсинга (override .env)"
    ),
    rate_limit: Optional[float] = typer.Option(
        None, "--rate-limit", help="Ограничение RPS для сетевых вызовов (override .env)"
    ),
    include: Optional[List[str]] = typer.Option(
        None, "--include", help="Включить только URL, содержащие подстроки (можно повторять ключ)"
    ),
    exclude: Optional[List[str]] = typer.Option(
        None, "--exclude", help="Исключить URL, содержащие подстроки (можно повторять ключ)"
    ),
) -> None:
    if download_media is not None:
        os.environ["DOWNLOAD_MEDIA"] = "true" if download_media else "false"
    if headless is not None:
        os.environ["HEADLESS"] = "true" if headless else "false"
    if rate_limit is not None:
        os.environ["RATE_LIMIT_RPS"] = str(rate_limit)
    if include:
        os.environ["CLI_INCLUDE"] = ",".join(include)
    if exclude:
        os.environ["CLI_EXCLUDE"] = ",".join(exclude)

@app.command("init-db")
def init_db_cmd(db: Path = typer.Option(Path("wooparser.db"), "--db", help="Путь к SQLite БД")) -> None:
    from .store import init_db
    init_db(db)
    rprint(f"[green]OK[/green] База инициализирована: {db}")

preview_app = typer.Typer(help="Превью данных")
app.add_typer(preview_app, name="preview")

@preview_app.command("product")
def preview_product(profile: str = typer.Option(..., "--profile"), url: str = typer.Option(..., "--url")) -> None:
    from .scrape import scrape_product
    product = scrape_product(url=url, profile=profile)
    rprint(json.dumps(product.model_dump(), ensure_ascii=False, indent=2))

@preview_app.command("category")
def preview_category(
    profile: str = typer.Option(..., "--profile"),
    url: str = typer.Option(..., "--url"),
    limit: int = 20,
    offset: int = 0,
    max_pages: int = typer.Option(None, "--max-pages")
) -> None:
    from .scrape import collect_category_urls
    urls = collect_category_urls(category_url=url, profile=profile, limit=limit, offset=offset, max_pages=max_pages)
    rprint({"count": len(urls), "sample": urls[:5]})

@app.command("collect")
def collect(
    profile: str = typer.Option(..., "--profile"),
    from_category: str = typer.Option(..., "--from-category", help="URL категории донора"),
    out: Path = typer.Option(Path("urls.txt"), "--out", help="Файл для записи URL товаров (по одному в строке)"),
    limit: int = typer.Option(1000, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    from .scrape import collect_category_urls
    urls = collect_category_urls(category_url=from_category, profile=profile, limit=limit, offset=offset)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    rprint({"written": len(urls), "file": str(out)})

@app.command("collect-all")
def collect_all(
    profile: str = typer.Option(..., "--profile"),
    out: Path = typer.Option(Path("urls_all.txt"), "--out"),
    limit_per_category: int = typer.Option(1000, "--limit-per-category"),
) -> None:
    from .scrape import collect_all_product_urls
    urls = collect_all_product_urls(profile=profile, limit_per_category=limit_per_category)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    rprint({"written": len(urls), "file": str(out)})

@app.command("cluster-preview")
def cluster_preview(profile: str = typer.Option(..., "--profile"), from_category: str = typer.Option(..., "--from-category"), limit: int = 50) -> None:
    from .scrape import cluster_preview as do_cluster
    clusters = do_cluster(profile=profile, from_category=from_category, limit=limit)
    rprint({"clusters": clusters})


@app.command("debug-variations")
def debug_variations_cmd(profile: str = typer.Option(..., "--profile"), url: str = typer.Option(..., "--url")) -> None:
    from .scrape import debug_variations as do_debug
    rows = do_debug(url=url, profile=profile)
    rprint(rows)



@app.command("validate")
def validate(profile: str = typer.Option(..., "--profile"), url: str = typer.Option(..., "--url")) -> None:
    from .scrape import scrape_product
    from .transform import validate_product
    product = scrape_product(url=url, profile=profile)
    issues = validate_product(product)
    if issues:
        for i in issues:
            rprint(f"[yellow]- {i}[/yellow]")
        raise typer.Exit(code=1)
    rprint("[green]OK[/green] Валидация пройдена")

@app.command("push-product")
def push_product(profile: str = typer.Option(..., "--profile"), url: str = typer.Option(..., "--url"), draft: bool = typer.Option(False, "--draft", help="Создать черновик"), publish: bool = typer.Option(False, "--publish", help="Опубликовать")) -> None:
    from .scrape import scrape_product
    from .transform import to_woo_product_payload
    from .wc import WooClient
    from .config import get_settings
    from .store import upsert_product_checkpoint, get_checkpoint_by_external_id
    import httpx

    settings = get_settings()
    if draft and publish:
        rprint("[red]Нельзя использовать --draft и --publish одновременно[/red]")
        raise typer.Exit(code=2)
    status = "draft" if draft else ("publish" if publish else "draft")

    product = scrape_product(url=url, profile=profile)
    payload = to_woo_product_payload(product, status=status)

    client = WooClient.from_settings(settings)

    existing = get_checkpoint_by_external_id(product.external_id, db_path=settings.db_path)
    if product.type == "variable":
        # Определяем вариативный атрибут (например, pa_obyem), исключая бренд
        var_pa_slug = next((k for k, v in product.attributes.items() if k.startswith("pa_") and k != "pa_brand" and len(v) > 1), None)
        if not var_pa_slug:
            var_pa_slug = next((k for k in product.attributes.keys() if k.startswith("pa_") and k != "pa_brand"), None)
        # ensure variable attribute and its terms
        parent_attrs = []
        if var_pa_slug:
            var_options = product.attributes.get(var_pa_slug, [])
            var_attr_id = client.ensure_global_attribute(var_pa_slug)
            client.ensure_attribute_terms(var_attr_id, var_options)
            parent_attrs.append({
                "id": var_attr_id,
                "variation": True,
                "visible": True,
                "options": var_options,
            })
            # default attribute
            default_val = product.default_attributes.get(var_pa_slug)
            if default_val:
                payload["default_attributes"] = [{"id": var_attr_id, "option": default_val}]
        # Бренд через таксономию product_brand
        brand_opts = product.attributes.get("pa_brand", [])
        if brand_opts:
            brand_term = client.ensure_term_in_taxonomy("product_brand", brand_opts[0])
            payload.setdefault("brands", [])
            payload["brands"] = [{"id": brand_term.get("id")}] if brand_term.get("id") else [{"name": brand_opts[0]}]
        if parent_attrs:
            payload["attributes"] = parent_attrs
        # create/update parent variable product
        if existing and existing.get("woo_product_id"):
            try:
                result = client.update_product(existing["woo_product_id"], payload)
            except httpx.HTTPStatusError as e:
                if e.response is not None and e.response.status_code in (400, 404):
                    result = client.create_product(payload)
                else:
                    raise
        else:
            result = client.create_product(payload)
        # Проставим категории: сопоставим слуги Woo и создадим при необходимости, сохраняя иерархию
        # product.categories уже содержит список слугов от донора, упорядоченных по вложенности
        cat_ids: list[int] = []
        if product.categories:
            try:
                cat_ids = client.ensure_categories_hierarchy(product.categories, getattr(product, "category_names", None))
            except Exception:
                cat_ids = []
        if cat_ids:
            try:
                client.update_product(result["id"], {"categories": [{"id": cid} for cid in cat_ids]})
            except Exception:
                pass

        # create variations based on var_pa_slug
        if var_pa_slug and parent_attrs:
            var_attr_id = next((a["id"] for a in parent_attrs if a.get("variation")), None)
            if var_attr_id:
                # цены и картинки из собранных вариаций, fallback на родителя
                base_price = product.regular_price
                var_payloads = []
                opt_to_var = {v.attributes.get(var_pa_slug): v for v in product.variations or []}
                for opt in product.attributes.get(var_pa_slug, []):
                    v = opt_to_var.get(opt)
                    vp = {"attributes": [{"id": var_attr_id, "option": opt}]}
                    # всегда создаём/обновляем manage_stock=false, чтобы не упиралось в остатки
                    vp["manage_stock"] = False
                    price = None
                    if v and v.regular_price is not None:
                        price = v.regular_price
                    elif base_price is not None:
                        price = base_price
                    if price is not None:
                        vp["regular_price"] = f"{price:.2f}"
                    if v and v.sale_price is not None:
                        vp["sale_price"] = f"{v.sale_price:.2f}"
                    if v and v.image_url:
                        vp["image"] = {"src": v.image_url}
                    if v and v.sku:
                        vp["sku"] = v.sku
                    var_payloads.append(vp)
                client.create_variations(result["id"], var_payloads)
    else:
        if existing and existing.get("woo_product_id"):
            try:
                result = client.update_product(existing["woo_product_id"], payload)
            except httpx.HTTPStatusError as e:
                if e.response is not None and e.response.status_code in (400, 404):
                    result = client.create_product(payload)
                else:
                    raise
        else:
            result = client.create_product(payload)
        # Категории для simple
        cat_ids: list[int] = []
        if product.categories:
            try:
                cat_ids = client.ensure_categories_hierarchy(product.categories, getattr(product, "category_names", None))
            except Exception:
                cat_ids = []
        if cat_ids:
            try:
                client.update_product(result["id"], {"categories": [{"id": cid} for cid in cat_ids]})
            except Exception:
                pass
        # Бренд для simple через таксономию product_brand
        brand_opts = product.attributes.get("pa_brand", [])
        if brand_opts:
            try:
                brand_term = client.ensure_term_in_taxonomy("product_brand", brand_opts[0])
                client.update_product(result["id"], {"brands": ([{"id": brand_term.get("id")}] if brand_term.get("id") else [{"name": brand_opts[0]}])})
            except Exception:
                pass
        # Невариативные атрибуты для simple: создадим/обновим глобальные и привяжем к продукту
        simple_attrs_payload = []
        for slug, options in (product.attributes or {}).items():
            if slug == "pa_brand":
                continue
            if not options:
                continue
            try:
                attr_id = client.ensure_global_attribute(slug)
                client.ensure_attribute_terms(attr_id, options)
                simple_attrs_payload.append({"id": attr_id, "visible": True, "options": options})
            except Exception:
                continue
        if simple_attrs_payload:
            try:
                client.update_product(result["id"], {"attributes": simple_attrs_payload})
            except Exception:
                pass
    upsert_product_checkpoint(product.external_id, result["id"], db_path=settings.db_path)
    rprint({"woo_product_id": result["id"], "status": result.get("status")})

@app.command("push-batch")
def push_batch(
    profile: str = typer.Option(..., "--profile"),
    file: Path = typer.Option(..., "--file"),
    draft: bool = False,
    publish: bool = False,
    limit: int = 50,
    offset: int = 0,
    resume: bool = False,
    skip_processed: bool = typer.Option(False, "--skip-processed", help="Пропускать URL, уже прошедшие через checkpoint")
) -> None:
    from .scrape import iterate_urls_from_file, _external_id_from_url
    from .store import get_checkpoint_by_external_id
    from .config import get_settings
    include_patterns = os.environ.get("CLI_INCLUDE", "").split(",") if os.environ.get("CLI_INCLUDE") else []
    exclude_patterns = os.environ.get("CLI_EXCLUDE", "").split(",") if os.environ.get("CLI_EXCLUDE") else []

    def allowed(u: str) -> bool:
        if include_patterns:
            if not any(p for p in include_patterns if p and p in u):
                return False
        if exclude_patterns:
            if any(p for p in exclude_patterns if p and p in u):
                return False
        return True

    settings = get_settings()
    for url in iterate_urls_from_file(file, limit=limit, offset=offset):
        if not allowed(str(url)):
            continue
        try:
            if skip_processed:
                ext = _external_id_from_url(str(url))
                chk = get_checkpoint_by_external_id(ext, db_path=settings.db_path)
                if chk and chk.get("woo_product_id"):
                    rprint(f"[yellow]SKIP processed[/yellow]: {url}")
                    continue
            # вызывать как обычную функцию
            push_product(profile=profile, url=str(url), draft=draft, publish=publish)
        except SystemExit as e:
            if resume:
                rprint(f"[yellow]Ошибка для {url}, продолжаю (--resume)[/yellow]")
                continue
            raise
        except Exception as e:
            if resume:
                rprint(f"[yellow]Исключение для {url}: {e}; продолжаю (--resume)[/yellow]")
                continue
            raise

