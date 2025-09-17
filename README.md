# Woo Parser → WooCommerce

Продукционный CLI-сервис для парсинга карточек товаров с внешних сайтов (config-driven профили доноров) и загрузки в WooCommerce через REST API. Готов к запуску локально и в GitHub Codespaces.

## Быстрый старт

1) Клонируйте репозиторий или откройте в Codespaces.
2) Скопируйте переменные окружения и заполните `.env`:
```
cp .env.example .env
# Впишите WP_BASE_URL и либо WC_CONSUMER_KEY/SECRET, либо WP_USER/WP_APP_PASSWORD
```
3) Установите зависимости и Playwright:
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install
```
4) Инициализируйте БД:
```
python -m scraper init-db
```
5) Минимальный E2E на фикстуре:
```
python -m scraper push-product --profile donor-example --url https://example.com/fixture --draft
```

## Профиль донора
Правьте файлы в `profiles/donor-example/`: `manifest.yaml`, `attributes.map.csv`, `categories.map.csv`, `values/*.csv`.

## Шпаргалка команд
См. конец основного сообщения в PR/Issue или инструкциях запуска.
