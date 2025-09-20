## Woo Parser → WooCommerce

CLI-сервис продакшн-уровня для парсинга карточек товаров с внешних сайтов и загрузки в WooCommerce через REST API. Проект конфигурируется профилями (YAML/CSV), готов к локальному запуску и GitHub Codespaces, без хардкода селекторов в коде.

### Что реализовано
- **Профиль донора** `profiles/donor-example/` (Crooz) с селекторами и мэппингами.
- **Парсинг товаров**: simple/variable, описание с очисткой HTML, изображения, цена(ы), SKU, атрибуты, категории.
- **Вариации**: автоопределение, корректное снятие цены/sku/картинки каждой опции (AJAX/URL/Playwright), без дублей при повторных заливках.
- **Категории**: из крошек, создание иерархии `product_cat`, присвоение всех уровней; если в `categories.map.csv` нет строки — slug генерируется (`slugify`) при сохранении оригинального названия.
- **Бренд**: таксономия `product_brand` (создание/привязка терма «CROOZ»), не как атрибут.
- **Атрибуты**: глобальные `pa_*` создаются/обновляются и назначаются продуктам/вариациям. Для донора настроен `pa_obyem`.
- **Идемпотентность**: SQLite-чекпоинты по `external_id`; вариации создаются/обновляются батчем.
- **Ограничение скорости** и **ретраи** для сетевых вызовов.
- **CLI** команды: превью/валидация/сбор ссылок/батч-заливка/отладка вариаций.

### Структура репозитория (важное)
- `profiles/donor-example/`
  - `manifest.yaml` — селекторы и политики (листинг, пагинация, продукт, вариации, категории).
  - `attributes.map.csv` — соответствие имён атрибутов донора → `pa_*` (напр. «Обʼєм» → `pa_obyem`).
  - `categories.map.csv` — соответствие названий в крошках → slug категории Woo (если нет — slug генерируется автоматически).
  - `values/pa_*.csv` — нормализация значений (donor_value → normalized_value).
- `scraper/`
  - `main.py` — Typer CLI.
  - `scrape.py` — парсер/сборщик (HTTP, DOM, AJAX, Playwright, крошки, кластеризация URL).
  - `wc.py` — клиент WooCommerce/WP (продукты, вариации, атрибуты, категории, бренды).
  - `models.py` — Pydantic-модели (`Product`, `Variation`, `Image`).
  - `store.py` — SQLite-чекпоинты.
  - `utils.py` — логирование, rate limiter.
- `.devcontainer/` — конфигурация Codespaces (Python 3.11).
- `tests/` — базовый smoke.

## Установка и запуск

### Подготовка окружения
1) Скопируйте `.env.example` в `.env` и заполните:
```
cp .env.example .env
# Обязательно: WP_BASE_URL
# Авторизация: WC_CONSUMER_KEY + WC_CONSUMER_SECRET ИЛИ WP_USER + WP_APP_PASSWORD
```
Важно: в `.env` не должно быть дублей пустых ключей ниже — они перетрут значения.

2) Установка зависимостей:
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install  # для динамических страниц
```
Если нужны системные зависимости Playwright (Debian/Ubuntu):
```
sudo npx playwright install-deps
# или sudo apt-get install ... (см. документацию Playwright)
```

3) Инициализация БД (чекпоинты):
```
python -m scraper init-db
```

### Быстрая проверка (фикстура E2E)
```
python -m scraper push-product --profile donor-example --url https://example.com/fixture --draft
```

## Как работает парсинг

### Simple vs Variable
- Из блока `.product__modifications` собираются значения опций. Если опций **>1** — `variable`, если ровно **1** — считаем **simple**.
- В `variable` создаём глобальный атрибут (например, `pa_obyem`), его terms и вариации (без дублей, батч `create+update`).
- В `simple` атрибуты прикрепляются как невариативные.

### Цены
- Текущая цена: `.product-price__item.product-price__item--new` (если есть) иначе видимый `.product-price__item`.
- Старая цена (регулярная): `.product-price__old-price`.
- Для вариаций цена читается для КАЖДОЙ опции после переключения (клик/hidden input) и ожидания изменения URL/DOM.

### SKU
- Очищается от префикса «Артикул: ».
- Для вариаций читается после переключения опции.

### Описание
- Очистка HTML: удаляем `<style>`, `<script>`, пустые `<p>`, разворачиваем `<font>`, сбрасываем inline-стили.

### Изображения
- Собираются из галереи, первая — как главное. Для вариаций читается актуальная после переключения опции.

### Категории
- Из `nav.breadcrumbs` пропуская «Головна» и «Каталог», последний элемент (товар) отбрасывается.
- По именам крошек подбираются slugs из `categories.map.csv`; если нет — slug генерируется автоматически (`slugify`), название остаётся оригинальным (укр.).
- В Woo сохраняется **вся иерархия** (родитель, подкатегория, подподкатегория) и назначается товару.

### Бренд
- Таксономия `product_brand`: создаём/находим «CROOZ» и прикрепляем к товару.

### Вариации: стратегия
1) AJAX `load-modification`: если ответы отличаются — извлекаем цену/SKU/картинку.
2) Быстрый `URL`-режим: если у кнопок есть `href` на версию страницы и данные действительно различаются — читаем с этих страниц.
3) `Playwright` (надежный): кликаем по опциям или триггерим `change` на hidden input, ждём изменения цены/URL, затем читаем DOM.
4) Если AJAX/URL дают одинаковые ответы — принудительно уходим в Playwright.

## Профиль донора (как переключить на другой сайт)
1) Скопируйте папку профиля: `profiles/donor-example` → `profiles/<your-site>`.
2) В `manifest.yaml` обновите:
   - `site.base_url`
   - `listing.product_link` и `listing.pagination.next_selector`
   - `product.selectors` (title, sku, price_regular, price_sale, description_html, gallery_imgs)
   - `variations` (тип/selectors), `categories` (крошки)
3) В `attributes.map.csv` пропишите мэппинг имён → `pa_*` и признак вариативности.
4) В `values/*.csv` при необходимости нормализуйте значения.
5) В `categories.map.csv` добавьте соответствия крошек → слаги Woo (или доверьтесь auto-slug).
6) Прогоните превью/валидацию на 1–2 URL, затем батч.

## Команды CLI

### Превью
```
python -m scraper preview product --profile donor-example --url "<PRODUCT_URL>"
python -m scraper preview category --profile donor-example --url "<CATEGORY_URL>" --limit 200 --max-pages 2
```

### Валидация модели
```
python -m scraper validate --profile donor-example --url "<PRODUCT_URL>"
```

### Заливка одного товара
```
python -m scraper push-product --profile donor-example --url "<PRODUCT_URL>" --draft
# или опубликовать:
python -m scraper push-product --profile donor-example --url "<PRODUCT_URL>" --publish
```

### Сбор ссылок
```
# Из категории (с пагинацией)
python -m scraper collect --profile donor-example --from-category "<CATEGORY_URL>" --out urls.txt --limit 1000

# Весь каталог рекурсивно (подкатегории) с пагинацией
python -m scraper collect-all --profile donor-example --out urls_all.txt --limit-per-category 1000
```

### Батч-заливка
```
python -m scraper push-batch --profile donor-example --file urls.txt --draft --limit 100 --offset 0 --resume
```
Глобальные фильтры (для batch): `--include substr`, `--exclude substr` (можно повторять).

### Отладка вариаций
```
python -m scraper debug-variations --profile donor-example --url "<PRODUCT_URL>"
```

## Тесты
```
pytest -q
```

## Переменные окружения (`.env`)
- **WP_BASE_URL** — базовый URL Woo.
- Авторизация (один из вариантов):
  - **WC_CONSUMER_KEY**, **WC_CONSUMER_SECRET**
  - или **WP_USER**, **WP_APP_PASSWORD**
- **WC_API_VERSION** (по умолчанию `wc/v3`).
- **REQUESTS_TIMEOUT**, **RATE_LIMIT_RPS**.
- **DOWNLOAD_MEDIA** (не используется в минимальном E2E для медиа upload).
- **HEADLESS** — управление Playwright.
- **DB_PATH** (опционально, по умолчанию `wooparser.db`).

## Идемпотентность и обновления
- Чекпоинт по `external_id` записывается в SQLite.
- Родительский variable-продукт — upsert; при 400/404 (удалён) создаём заново.
- Вариации — батч `create + update` по ключу атрибутов; дубликаты не создаём, меняем цену/sku/картинку при повторном запуске.

## Известные ограничения / планы
- Импорт изображений категорий (иконки каталога) — в планах.
- Медиа через WP REST как бинарники не загружаем в минимальном E2E.

## Шпаргалка
- **Фикстура**: `python -m scraper push-product --profile donor-example --url https://example.com/fixture --draft`
- **Превью товара**: `python -m scraper preview product --profile donor-example --url "<URL>"`
- **Превью 2 страниц каталога**: `python -m scraper preview category --profile donor-example --url "https://crooz.in.ua/katalog/" --limit 200 --max-pages 2`
- **Сбор всех ссылок каталога**: `python -m scraper collect-all --profile donor-example --out urls_all.txt --limit-per-category 1000`
- **Батч заливка**: `python -m scraper push-batch --profile donor-example --file urls.txt --draft --limit 100 --resume`
- **Отладка вариаций**: `python -m scraper debug-variations --profile donor-example --url "<URL>"`

Если что-то пошло не так — включите логирование, проверьте `.env` (нет ли дублей), зависимости Playwright и попробуйте `preview product` для диагностики.
