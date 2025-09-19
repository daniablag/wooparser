from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from urllib.parse import urljoin
import csv
import re
import httpx
import hashlib
from bs4 import BeautifulSoup, Tag
import yaml
from .models import Product, Image, Variation
from .config import get_settings
from .utils import RateLimiter, get_logger

logger = get_logger("scrape")

FIXTURE_URL = "https://example.com/fixture"


def _workspace_root() -> Path:
    # Предполагаем, что модуль запущен из корня проекта (/workspaces/wooparser)
    return Path.cwd()


def _profile_dir(profile: str) -> Path:
    return _workspace_root() / "profiles" / profile


def _load_manifest(profile: str) -> Dict:
    mf = _profile_dir(profile) / "manifest.yaml"
    with mf.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_csv_map(path: Path) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    if not path.exists():
        return mapping
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = [h.strip() for h in (reader.fieldnames or [])]
        rows = list(reader)
    if path.name == "attributes.map.csv":
        # donor_name,pa_slug,is_variation
        for r in rows:
            donor = (r.get("donor_name") or "").strip()
            pa = (r.get("pa_slug") or "").strip()
            if donor and pa:
                mapping[donor] = pa
    elif path.name == "categories.map.csv":
        # donor_path,woo_category_slug
        for r in rows:
            donor = (r.get("donor_path") or "").strip()
            slug = (r.get("woo_category_slug") or "").strip()
            if donor and slug:
                mapping[donor] = slug
    else:
        # values/*.csv: donor_value,normalized_value
        for r in rows:
            donor = (r.get("donor_value") or "").strip()
            norm = (r.get("normalized_value") or "").strip()
            if donor:
                mapping[donor] = norm or donor
    return mapping


def _load_values_maps(profile: str) -> Dict[str, Dict[str, str]]:
    values_dir = _profile_dir(profile) / "values"
    value_maps: Dict[str, Dict[str, str]] = {}
    if not values_dir.exists():
        return value_maps
    for p in values_dir.glob("pa_*.csv"):
        pa_slug = p.stem
        value_maps[pa_slug] = _load_csv_map(p)
    return value_maps


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(strip=True)) if el else ""


def _price_to_float(text: str) -> Optional[float]:
    if not text:
        return None
    # Убираем все кроме цифр и разделителей
    cleaned = re.sub(r"[^0-9,\.]+", "", text)
    # Приводим запятую к точке, убираем лишние пробелы
    cleaned = cleaned.replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _abs_url(base: str, url: str) -> str:
    return urljoin(base, url)


def _is_placeholder_option(val: str) -> bool:
    v = (val or "").strip().lower()
    if not v:
        return True
    placeholders = [
        "будь який",
        "будь-який",
        "any",
        "любой",
    ]
    return any(p in v for p in placeholders)


def _normalize_value(profile: str, pa_slug: str, value: str) -> str:
    values_map = _load_values_maps(profile)
    mapping = values_map.get(pa_slug, {})
    return mapping.get(value, value)


def scrape_product(url: str, profile: str) -> Product:
    # Фикстура для теста интеграции
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

    manifest = _load_manifest(profile)
    settings = get_settings()
    rate = RateLimiter(settings.rate_limit_rps)

    rate.wait()
    with httpx.Client(timeout=settings.requests_timeout) as client:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "lxml")
    site_base = manifest.get("site", {}).get("base_url", "")

    sel = manifest.get("product", {}).get("selectors", {})
    title = _text(soup.select_one(sel.get("title", "")))
    sku = _text(soup.select_one(sel.get("sku", "")))
    if sku:
        # убрать префикс "Артикул: " если присутствует
        sku_clean = re.sub(r"^\s*Артикул\s*:\s*", "", sku, flags=re.IGNORECASE)
        sku = sku_clean or sku

    sale_el = soup.select_one(sel.get("price_sale", "")) if sel.get("price_sale") else None
    reg_el = soup.select_one(sel.get("price_regular", "")) if sel.get("price_regular") else None
    sale_price = _price_to_float(_text(sale_el)) if sale_el else None
    regular_price = _price_to_float(_text(reg_el)) if reg_el else None
    if sale_price and not regular_price:
        # иногда regular в другом месте — минимально подстрахуемся
        regular_price = sale_price

    desc_el = soup.select_one(sel.get("description_html", ""))

    def _sanitize_html_fragment(container: Optional[Tag]) -> str:
        if not container:
            return ""
        # удалить style/script
        for t in container.find_all(["style", "script"]):
            t.decompose()
        # развернуть теги <font>
        for t in list(container.find_all("font")):
            t.unwrap()
        # удалить inline style-атрибуты
        for t in container.find_all(True):
            if "style" in t.attrs:
                del t["style"]
        # удалить пустые <p> (только переносы/пробелы)
        for p in list(container.find_all("p")):
            text = p.get_text(strip=True)
            if not text:
                has_meaningful_child = any(getattr(ch, "name", None) not in (None, "br") for ch in p.children)
                if not has_meaningful_child:
                    p.decompose()
        return container.decode_contents()

    description_html = _sanitize_html_fragment(desc_el)

    # Галерея
    images: List[Image] = []
    gal_selector = sel.get("gallery_imgs")
    if gal_selector:
        for img in soup.select(gal_selector):
            src = (img.get("src") or "").strip()
            alt = (img.get("alt") or "").strip() or title
            if not src:
                continue
            full = _abs_url(site_base or url, src)
            images.append(Image(url=full, alt=alt))
    # Убираем дубли, сохраняя порядок
    seen: set = set()
    unique_images: List[Image] = []
    for im in images:
        if im.url not in seen:
            unique_images.append(im)
            seen.add(im.url)
    images = unique_images

    # Вариации/атрибуты
    attributes: Dict[str, List[str]] = {}
    default_attributes: Dict[str, str] = {}
    product_type = "simple"

    # Собираем кнопки вариаций
    active_sel = manifest.get("variations", {}).get("active_selector")
    obem_buttons = soup.select(".product__modifications .modification .modification__body .modification__list .modification__button")
    values_map = _load_values_maps(profile)
    attr_map = _load_csv_map(_profile_dir(profile) / "attributes.map.csv")

    def _normalize(pa_slug: str, value: str) -> str:
        m = values_map.get(pa_slug, {})
        return m.get(value, value)

    def _is_placeholder_option(val: str) -> bool:
        v = (val or "").strip().lower()
        if not v:
            return True
        # частые варианты плейсхолдеров
        placeholders = [
            "будь який",  # укр. "любой"
            "будь-який",
            "any",
            "любой",
        ]
        return any(p in v for p in placeholders)

    variations_data: List[Variation] = []
    if obem_buttons:
        raw_values = [_text(b) for b in obem_buttons]
        raw_values = [v for v in raw_values if not _is_placeholder_option(v)]
        # уникализируем порядок
        _seen = set()
        raw_values = [v for v in raw_values if not (v in _seen or _seen.add(v))]
        pa_slug = attr_map.get("Обʼєм", "pa_obyem")
        norm_values = [_normalize(pa_slug, v) for v in raw_values if v]
        if norm_values:
            attributes[pa_slug] = norm_values
        if len(obem_buttons) > 1:
            product_type = "variable"
        # дефолт из активной кнопки
        if active_sel:
            active = soup.select_one(active_sel)
            if active:
                active_val = _normalize(pa_slug, _text(active))
                if active_val:
                    default_attributes[pa_slug] = active_val

        # Попытаться собрать данные по вариациям через ajax-эндпоинт формы
        form = soup.select_one(".product__modifications form[method=post]")
        if form is not None:
            action = (form.get("data-action") or form.get("action") or "").strip()
            if action:
                action_url = _abs_url(site_base or url, action)
                hidden = form.select_one("input[name^=\"param[\"]")
                param_name = hidden.get("name") if hidden else "param[obem]"
                # построим карту значение -> подпись
                value_to_label: Dict[str, str] = {}
                for b in obem_buttons:
                    label = _text(b)
                    if _is_placeholder_option(label):
                        continue
                    val = (b.get("data-value") or "").strip()
                    if val:
                        value_to_label[val] = _normalize(pa_slug, label)
                ajax_hashes: Dict[str, str] = {}
                for val, label in value_to_label.items():
                    try:
                        rate.wait()
                        ajax_headers = {
                            "Referer": url,
                            "X-Requested-With": "XMLHttpRequest",
                            "Accept": "application/json,text/html,*/*",
                            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        }
                        with httpx.Client(timeout=settings.requests_timeout, headers=ajax_headers, follow_redirects=True) as sclient:
                            # сначала попробуем GET, как это часто делает фронтенд
                            r = sclient.get(action_url, params={param_name: val})
                            if r.status_code >= 400:
                                # fallback на POST
                                r = sclient.post(action_url, data={param_name: val})
                        r.raise_for_status()
                        # сохраняем хэш ответа для детекции "одинакового контента"
                        try:
                            ajax_hashes[val] = hashlib.md5(r.text.encode("utf-8", errors="ignore")).hexdigest()
                        except Exception:
                            ajax_hashes[val] = ""
                        # сначала пробыем как JSON
                        var_sku: Optional[str] = None
                        var_price: Optional[float] = None
                        var_image_url: Optional[str] = None
                        parsed_json = None
                        try:
                            parsed_json = r.json()
                        except Exception:
                            parsed_json = None
                        if isinstance(parsed_json, dict):
                            # эвристики по ключам
                            for key in ("price", "regular_price", "price_html", "new_price"):
                                if key in parsed_json and isinstance(parsed_json[key], (str, int, float)):
                                    var_price = _price_to_float(str(parsed_json[key]))
                                    break
                            for key in ("sku", "article", "code"):
                                if key in parsed_json and isinstance(parsed_json[key], str):
                                    var_sku = parsed_json[key].strip() or None
                                    break
                            for key in ("image", "image_url", "img"):
                                if key in parsed_json and isinstance(parsed_json[key], str):
                                    var_image_url = _abs_url(site_base or url, parsed_json[key])
                                    break
                            # иногда бывает html
                            if not (var_price and var_image_url):
                                html_fragment = parsed_json.get("html") or parsed_json.get("content")
                                if isinstance(html_fragment, str) and html_fragment:
                                    frag = BeautifulSoup(html_fragment, "lxml")
                                    if not var_price:
                                        el = frag.select_one(sel.get("price_sale", "")) or frag.select_one(sel.get("price_regular", ""))
                                        var_price = _price_to_float(_text(el)) if el else None
                                    if not var_image_url:
                                        img0 = frag.select_one(".gallery__photos .gallery__item:first-child .gallery__photo-img")
                                        if img0 and img0.get("src"):
                                            var_image_url = _abs_url(site_base or url, img0.get("src"))
                        else:
                            # HTML фрагмент: сайт отдаёт блок "Дивіться також" и т.п., не содержит данных вариаций
                            # сохраняем None, чтобы fallback ниже заполнил данными
                            pass

                        variations_data.append(Variation(
                            sku=var_sku or "",
                            regular_price=var_price or (regular_price or 0.0),
                            sale_price=None,
                            stock_quantity=None,
                            attributes={pa_slug: label},
                            image_url=var_image_url,
                        ))
                    except Exception:
                        # если ajax не сработал, создадим вариацию с дефолтной ценой и без изображения
                        variations_data.append(Variation(
                            sku="",
                            regular_price=(regular_price or 0.0),
                            sale_price=None,
                            stock_quantity=None,
                            attributes={pa_slug: label},
                            image_url=None,
                        ))
        # конец ajax-зоны

                # Если все ajax ответы идентичны (страница та же), не доверяем данным и переходим к URL/Playwright фолбэкам
                if ajax_hashes and len(set(ajax_hashes.values())) == 1:
                    variations_data = []

        # Fallback: если не удалось получить вариации через ajax, попробуем по URL-шаблону -{N}-ml
        if not variations_data and norm_values:
            m = re.search(r"-(\d+)-ml/?$", url)
            if m:
                for label in norm_values:
                    num_match = re.search(r"(\d+)", label)
                    if not num_match:
                        continue
                    new_num = num_match.group(1)
                    variant_url = re.sub(r"-(\d+)-ml/?$", f"-{new_num}-ml/", url)
                    try:
                        rate.wait()
                        with httpx.Client(timeout=settings.requests_timeout) as sclient:
                            vresp = sclient.get(variant_url)
                            vresp.raise_for_status()
                            vsoup = BeautifulSoup(vresp.text, "lxml")
                        vel = vsoup.select_one(sel.get("price_sale", "")) or vsoup.select_one(sel.get("price_regular", ""))
                        vprice = _price_to_float(_text(vel)) if vel else (regular_price or 0.0)
                        vsku = _text(vsoup.select_one(sel.get("sku", "")))
                        if vsku:
                            vsku = re.sub(r"^\s*Артикул\s*:\s*", "", vsku, flags=re.IGNORECASE)
                        vimg0 = vsoup.select_one(".gallery__photos .gallery__item:first-child .gallery__photo-img")
                        vimg_url = _abs_url(site_base or variant_url, vimg0.get("src")) if vimg0 and vimg0.get("src") else None
                        variations_data.append(Variation(
                            sku=vsku or "",
                            regular_price=vprice or (regular_price or 0.0),
                            sale_price=None,
                            stock_quantity=None,
                            attributes={pa_slug: label},
                            image_url=vimg_url,
                        ))
                    except Exception:
                        variations_data.append(Variation(
                            sku="",
                            regular_price=(regular_price or 0.0),
                            sale_price=None,
                            stock_quantity=None,
                            attributes={pa_slug: label},
                            image_url=None,
                        ))

        # Попытка через Playwright: имитируем клики по кнопкам вариаций и читаем цену/SKU/фото после смены
        if not variations_data and norm_values:
            try:
                from playwright.sync_api import sync_playwright
                headless = get_settings().headless
                option_selector = manifest.get("variations", {}).get("columns", {}).get("size") or ".modification__body .modification__list .modification__button"
                price_sel = sel.get("price_sale") or sel.get("price_regular")
                sku_sel = sel.get("sku")
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=headless)
                    page = browser.new_page()
                    page.goto(url, wait_until="domcontentloaded")
                    btns = page.query_selector_all(option_selector)
                    for btn in btns:
                        label = (btn.inner_text() or "").strip()
                        if _is_placeholder_option(label):
                            continue
                        btn.click()
                        # подождём апдейта цены/активного класса
                        page.wait_for_timeout(200)  # короткая пауза
                        vprice = None
                        if price_sel:
                            el = page.query_selector(price_sel)
                            if el:
                                vprice = _price_to_float((el.inner_text() or "").strip())
                        vsku = None
                        if sku_sel:
                            se = page.query_selector(sku_sel)
                            if se:
                                sk = (se.inner_text() or "").strip()
                                if sk:
                                    vsku = re.sub(r"^\s*Артикул\s*:\s*", "", sk, flags=re.IGNORECASE)
                        img0 = page.query_selector(".gallery__photos .gallery__item:first-child .gallery__photo-img")
                        vimg_url = None
                        if img0:
                            src = img0.get_attribute("src")
                            if src:
                                vimg_url = _abs_url(site_base or url, src)
                        label_norm = _normalize(pa_slug, label)
                        variations_data.append(Variation(
                            sku=vsku or "",
                            regular_price=vprice or (regular_price or 0.0),
                            sale_price=None,
                            stock_quantity=None,
                            attributes={pa_slug: label_norm},
                            image_url=vimg_url,
                        ))
                    browser.close()
            except Exception:
                pass
        # конец ajax-зоны

    # Категории по крошкам
    categories: List[str] = []
    cat_map = _load_csv_map(_profile_dir(profile) / "categories.map.csv")
    bc_sel = manifest.get("categories", {}).get("breadcrumbs_selector")
    name_sel = manifest.get("categories", {}).get("breadcrumbs_name_selector")
    exclude_names = set(manifest.get("categories", {}).get("breadcrumbs_exclude_names", []) or [])
    if bc_sel:
        crumbs = soup.select(bc_sel) or []
        names: List[str] = []
        for c in crumbs:
            name_el = c.select_one(name_sel) if name_sel else None
            name = _text(name_el or c)
            if not name:
                continue
            names.append(name)
        # отфильтровать служебные и последний (товар)
        names = [n for n in names if n not in exclude_names]
        if names:
            names = names[:-1]  # убрать последний элемент – название товара
        for n in names:
            slug = cat_map.get(n)
            if slug and slug not in categories:
                categories.append(slug)

    # Бренд CROOZ
    attributes.setdefault("pa_brand", ["CROOZ"])  # всегда CROOZ

    external_id = _external_id_from_url(url)

    return Product(
        external_id=external_id,
        name=title or external_id,
        sku=sku or None,
        description_html=description_html or None,
        short_description_html=None,
        categories=categories,
        tags=[],
        images=images,
        attributes=attributes,
        default_attributes=default_attributes,
        type=product_type,
        regular_price=regular_price,
        sale_price=sale_price,
        stock_quantity=None,
        variations=variations_data,
    )


def _external_id_from_url(url: str) -> str:
    # Используем последний сегмент без завершающего слеша
    u = url.rstrip("/")
    return u.rsplit("/", 1)[-1]


def collect_category_urls(category_url: str, profile: str, limit: int = 20, offset: int = 0) -> List[str]:
    manifest = _load_manifest(profile)
    settings = get_settings()
    rate = RateLimiter(settings.rate_limit_rps)

    product_sel = manifest.get("listing", {}).get("product_link") or "a"
    next_sel = manifest.get("listing", {}).get("pagination", {}).get("next_selector")

    results: List[str] = []
    url = category_url
    while len(results) < (offset + limit) and url:
        rate.wait()
        with httpx.Client(timeout=settings.requests_timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
        site_base = manifest.get("site", {}).get("base_url", url)
        for a in soup.select(product_sel):
            href = a.get("href")
            if not href:
                continue
            full = _abs_url(site_base, href)
            results.append(full)
            if len(results) >= (offset + limit):
                break
        if next_sel:
            next_a = soup.select_one(next_sel)
            url = _abs_url(site_base, next_a.get("href")) if next_a and next_a.get("href") else None
        else:
            break
    return results[offset : offset + limit]


def cluster_preview(profile: str, from_category: str, limit: int = 50):
    # Простая кластеризация по базовому external_id (последний сегмент URL без вариации)
    urls = collect_category_urls(from_category, profile=profile, limit=limit)
    clusters: Dict[str, List[str]] = {}
    for u in urls:
        key = _external_id_from_url(u)
        clusters.setdefault(key, []).append(u)
    return [{"parent_key": k, "urls": v} for k, v in clusters.items()]


def iterate_urls_from_file(path, limit: int = 50, offset: int = 0):
    p = Path(path)
    if not p.exists():
        return []
    lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return lines[offset : offset + limit]


def debug_variations(url: str, profile: str) -> List[Dict[str, Optional[str]]]:
    manifest = _load_manifest(profile)
    settings = get_settings()
    rate = RateLimiter(settings.rate_limit_rps)
    results: List[Dict[str, Optional[str]]] = []

    rate.wait()
    with httpx.Client(timeout=settings.requests_timeout) as client:
        resp = client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

    sel = manifest.get("product", {}).get("selectors", {})
    site_base = manifest.get("site", {}).get("base_url", "")

    # собрать опции
    pa_slug = _load_csv_map(_profile_dir(profile) / "attributes.map.csv").get("Обʼєм", "pa_obyem")
    obem_buttons = soup.select(".product__modifications .modification .modification__body .modification__list .modification__button")
    value_to_label: Dict[str, str] = {}
    for b in obem_buttons:
        label = _text(b)
        if _is_placeholder_option(label):
            continue
        val = (b.get("data-value") or "").strip()
        if val:
            value_to_label[val] = _normalize_value(profile, pa_slug, label)

    form = soup.select_one(".product__modifications form[method=post]")
    action = (form.get("data-action") or form.get("action") or "").strip() if form else ""
    hidden = form.select_one("input[name^=\"param[\"]") if form else None
    param_name = hidden.get("name") if hidden else "param[obem]"

    ajax_headers = {
        "Referer": url,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json,text/html,*/*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    debug_dir = _workspace_root() / "debug"
    debug_dir.mkdir(exist_ok=True)
    for val, label in value_to_label.items():
        entry: Dict[str, Optional[str]] = {"label": label, "ajax_get": None, "ajax_post": None, "price": None, "sku": None, "image": None}
        if action:
            action_url = _abs_url(site_base or url, action)
            try:
                rate.wait()
                with httpx.Client(timeout=settings.requests_timeout, headers=ajax_headers, follow_redirects=True) as sclient:
                    r = sclient.get(action_url, params={param_name: val})
                    entry["ajax_get"] = f"{r.status_code} {r.headers.get('content-type','')}"
                    if r.is_redirect:  # type: ignore[attr-defined]
                        entry["ajax_get"] += f" -> {r.headers.get('location','')}"
                    # сохранить html ответа GET для анализа
                    try:
                        (debug_dir / f"ajax_get_{val}.html").write_text(r.text, encoding="utf-8")
                    except Exception:
                        pass
                    if r.status_code >= 400:
                        rp = sclient.post(action_url, data={param_name: val})
                        entry["ajax_post"] = f"{rp.status_code} {rp.headers.get('content-type','')}"
                        try:
                            (debug_dir / f"ajax_post_{val}.html").write_text(rp.text, encoding="utf-8")
                        except Exception:
                            pass
            except Exception as e:
                entry["ajax_get"] = f"error: {e}"

        # после ajax попробуем вытащить из текущей страницы (или повторным GET страницы вариации, если удаётся вывести)
        try:
            # перезапрос страницы (часто ajax меняет серверно, но если нет — хотя бы текущие)
            rate.wait()
            with httpx.Client(timeout=settings.requests_timeout) as r2:
                page = r2.get(url)
                page.raise_for_status()
                vsoup = BeautifulSoup(page.text, "lxml")
            el = vsoup.select_one(sel.get("price_sale", "")) or vsoup.select_one(sel.get("price_regular", ""))
            entry["price"] = _text(el) if el else None
            sk = vsoup.select_one(sel.get("sku", ""))
            entry["sku"] = re.sub(r"^\s*Артикул\s*:\s*", "", _text(sk), flags=re.IGNORECASE) if sk else None
            img0 = vsoup.select_one(".gallery__photos .gallery__item:first-child .gallery__photo-img")
            entry["image"] = _abs_url(site_base or url, img0.get("src")) if img0 and img0.get("src") else None
        except Exception as e:
            entry["price"] = entry["price"] or f"error: {e}"

        results.append(entry)

    return results
