from __future__ import annotations
import json
from pathlib import Path
import typer
from rich import print as rprint

app = typer.Typer(add_completion=False, help="CLI для парсинга и загрузки в WooCommerce")

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
def preview_category(profile: str = typer.Option(..., "--profile"), url: str = typer.Option(..., "--url"), limit: int = 20, offset: int = 0) -> None:
    from .scrape import collect_category_urls
    urls = collect_category_urls(category_url=url, profile=profile, limit=limit, offset=offset)
    rprint({"count": len(urls), "sample": urls[:5]})

@app.command("cluster-preview")
def cluster_preview(profile: str = typer.Option(..., "--profile"), from_category: str = typer.Option(..., "--from-category"), limit: int = 50) -> None:
    from .scrape import cluster_preview as do_cluster
    clusters = do_cluster(profile=profile, from_category=from_category, limit=limit)
    rprint({"clusters": clusters})

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

    settings = get_settings()
    if draft and publish:
        rprint("[red]Нельзя использовать --draft и --publish одновременно[/red]")
        raise typer.Exit(code=2)
    status = "draft" if draft else ("publish" if publish else "draft")

    product = scrape_product(url=url, profile=profile)
    payload = to_woo_product_payload(product, status=status)

    client = WooClient.from_settings(settings)

    existing = get_checkpoint_by_external_id(product.external_id, db_path=settings.db_path)
    if existing and existing.get("woo_product_id"):
        result = client.update_product(existing["woo_product_id"], payload)
    else:
        result = client.create_product(payload)
    upsert_product_checkpoint(product.external_id, result["id"], db_path=settings.db_path)
    rprint({"woo_product_id": result["id"], "status": result.get("status")})

@app.command("push-batch")
def push_batch(profile: str = typer.Option(..., "--profile"), file: Path = typer.Option(..., "--file"), draft: bool = False, publish: bool = False, limit: int = 50, offset: int = 0, resume: bool = False) -> None:
    from .scrape import iterate_urls_from_file
    for url in iterate_urls_from_file(file, limit=limit, offset=offset):
        try:
            push_product.callback(profile=profile, url=str(url), draft=draft, publish=publish)
        except SystemExit as e:
            if resume:
                rprint(f"[yellow]Ошибка для {url}, продолжаю (--resume)[/yellow]")
                continue
            raise

