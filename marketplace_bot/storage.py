from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


SCHEMA = """
CREATE TABLE IF NOT EXISTS product_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    chat_id INTEGER,
    marketplace TEXT NOT NULL,
    query TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    price REAL,
    rating REAL,
    reviews INTEGER
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    chat_id INTEGER,
    marketplace TEXT NOT NULL,
    category TEXT NOT NULL,
    date TEXT NOT NULL,
    price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    chat_id INTEGER,
    marketplace TEXT NOT NULL,
    query TEXT NOT NULL,
    category TEXT NOT NULL,
    score REAL,
    risk_level TEXT,
    roi REAL,
    break_even_price REAL,
    trend_pct REAL
);
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)


def save_products(db_path: Path, chat_id: int, marketplace: str, query: str, products: pd.DataFrame) -> None:
    init_db(db_path)
    rows = []
    for item in products.to_dict("records"):
        rows.append((
            chat_id,
            marketplace,
            query,
            str(item.get("name", "")),
            str(item.get("category", "")),
            float(item.get("price", 0) or 0),
            float(item.get("rating", 0) or 0),
            int(item.get("reviews", 0) or 0),
        ))
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO product_snapshots (chat_id, marketplace, query, name, category, price, rating, reviews)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def save_price_history(db_path: Path, chat_id: int, marketplace: str, category: str, history: pd.DataFrame) -> None:
    init_db(db_path)
    rows = []
    for item in history.to_dict("records"):
        rows.append((chat_id, marketplace, category, str(item["date"])[:10], float(item["price"])))
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO price_history (chat_id, marketplace, category, date, price)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )


def save_analysis(
    db_path: Path,
    chat_id: int,
    marketplace: str,
    query: str,
    category: str,
    score: float,
    risk_level: str,
    roi: float,
    break_even_price: float,
    trend_pct: float,
) -> None:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO analyses (chat_id, marketplace, query, category, score, risk_level, roi, break_even_price, trend_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (chat_id, marketplace, query, category, score, risk_level, roi, break_even_price, trend_pct),
        )
