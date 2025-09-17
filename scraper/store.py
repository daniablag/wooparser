from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS products (\n"
    " external_id TEXT PRIMARY KEY,\n"
    " woo_product_id INTEGER,\n"
    " last_pushed_at TEXT DEFAULT (datetime(now))\n"
    ");"
)


def init_db(db_path: Path) -> None:
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def upsert_product_checkpoint(external_id: str, woo_product_id: int, db_path: Path = Path("wooparser.db")) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO products(external_id, woo_product_id) VALUES(?, ?)\n"
            "ON CONFLICT(external_id) DO UPDATE SET woo_product_id=excluded.woo_product_id, last_pushed_at=datetime(now)",
            (external_id, woo_product_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_checkpoint_by_external_id(external_id: str, db_path: Path = Path("wooparser.db")) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE external_id=?", (external_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
