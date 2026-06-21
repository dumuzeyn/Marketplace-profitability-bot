from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import pandas as pd
import requests


def ru(text: str) -> str:
    try:
        return text.encode("ascii").decode("unicode_escape")
    except UnicodeEncodeError:
        return text


@dataclass(frozen=True)
class MarketplaceConfig:
    name: str
    review_cap: int
    commission_rate: float
    category_templates: tuple[str, ...]


MARKETPLACES: dict[str, MarketplaceConfig] = {
    "ozon": MarketplaceConfig(
        name="Ozon",
        review_cap=10000,
        commission_rate=0.18,
        category_templates=(
            ru(r"\u0411\u044e\u0434\u0436\u0435\u0442\u043d\u044b\u0435"),
            ru(r"\u041f\u043e\u043f\u0443\u043b\u044f\u0440\u043d\u044b\u0435"),
            ru(r"\u041f\u0440\u0435\u043c\u0438\u0443\u043c"),
            ru(r"\u041f\u0440\u043e\u0444\u0435\u0441\u0441\u0438\u043e\u043d\u0430\u043b\u044c\u043d\u044b\u0435"),
        ),
    ),
    "wildberries": MarketplaceConfig(
        name="Wildberries",
        review_cap=1000,
        commission_rate=0.20,
        category_templates=(
            ru(r"\u0411\u0430\u0437\u043e\u0432\u044b\u0435"),
            ru(r"\u0425\u0438\u0442\u044b \u043f\u0440\u043e\u0434\u0430\u0436"),
            ru(r"\u0414\u043b\u044f \u0434\u043e\u043c\u0430"),
            ru(r"\u0414\u043b\u044f \u043f\u0440\u043e\u0444\u0435\u0441\u0441\u0438\u043e\u043d\u0430\u043b\u043e\u0432"),
        ),
    ),
    "yandex_market": MarketplaceConfig(
        name="Yandex Market",
        review_cap=1000,
        commission_rate=0.16,
        category_templates=(
            ru(r"\u042d\u043a\u043e\u043d\u043e\u043c"),
            ru(r"\u041e\u043f\u0442\u0438\u043c\u0430\u043b\u044c\u043d\u044b\u0435"),
            ru(r"\u0412\u044b\u0441\u043e\u043a\u0438\u0439 \u0440\u0435\u0439\u0442\u0438\u043d\u0433"),
            ru(r"\u0420\u0430\u0441\u0448\u0438\u0440\u0435\u043d\u043d\u0430\u044f \u043a\u043e\u043c\u043f\u043b\u0435\u043a\u0442\u0430\u0446\u0438\u044f"),
        ),
    ),
}

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


def normalize_marketplace(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_").replace(".", "")
    aliases = {
        "yandex": "yandex_market",
        ru(r"\u044f\u043d\u0434\u0435\u043a\u0441"): "yandex_market",
        ru(r"\u044f\u043d\u0434\u0435\u043a\u0441_\u043c\u0430\u0440\u043a\u0435\u0442"): "yandex_market",
        "wb": "wildberries",
        ru(r"\u0432\u0431"): "wildberries",
    }
    return aliases.get(normalized, normalized)


def _seed_for(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def is_url(value: str) -> bool:
    return value.strip().lower().startswith(("http://", "https://"))


def _clean_product_query(query: str) -> str:
    query = query.strip()
    if is_url(query):
        parsed = urlparse(query)
        params = parse_qs(parsed.query)
        for key in ("text", "search", "query", "q"):
            if params.get(key):
                return unquote(str(params[key][0])).strip()[:80] or ru(r"\u0442\u043e\u0432\u0430\u0440")
        path = unquote(parsed.path or "")
        parts = [part for part in re.split(r"[/_-]+", path) if part and not part.isdigit() and part not in {"catalog", "product", "detail", "search"}]
        if parts:
            return " ".join(parts[:5])[:80]
        return ru(r"\u0442\u043e\u0432\u0430\u0440 \u043f\u043e \u0441\u0441\u044b\u043b\u043a\u0435")
    return query[:80] or ru(r"\u0442\u043e\u0432\u0430\u0440")


def _to_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("\xa0", " ").replace(" ", "").replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) if match else default


def _to_int(value: object, default: int = 0) -> int:
    return int(round(_to_float(value, float(default))))


def _normalize_frame(rows: list[dict[str, object]], config: MarketplaceConfig, query: str, count: int) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows).head(count).copy()
    defaults = {
        "name": query,
        "description": "",
        "price": 0.0,
        "reviews": 0,
        "rating": 0.0,
        "category": ru(r"\u0420\u0435\u0430\u043b\u044c\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435"),
        "marketplace": config.name,
        "url": "",
        "data_source": "real_http",
    }
    for column, value in defaults.items():
        if column not in frame.columns:
            frame[column] = value
    frame["name"] = frame["name"].fillna(query).astype(str)
    frame["description"] = frame["description"].fillna("").astype(str)
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce").fillna(0)
    frame["reviews"] = pd.to_numeric(frame["reviews"], errors="coerce").fillna(0).astype(int)
    frame["rating"] = pd.to_numeric(frame["rating"], errors="coerce").fillna(0)
    frame["category"] = frame["category"].fillna(defaults["category"]).astype(str)
    frame["marketplace"] = config.name
    return frame[frame["price"] > 0].reset_index(drop=True)




def _fallback_profile(query: str) -> tuple[float, float, int]:
    text = _clean_product_query(query).lower()
    profiles = [
        ((ru(r"\u0441\u043c\u0430\u0440\u0442\u0444\u043e\u043d"), ru(r"\u0442\u0435\u043b\u0435\u0444\u043e\u043d"), "iphone", "phone", "smartphone", ru(r"\u0430\u0439\u0444\u043e\u043d")), 32000, 0.42, 900),
        ((ru(r"\u043d\u043e\u0443\u0442\u0431\u0443\u043a"), "laptop", "noutbuk", "notebook"), 62000, 0.35, 420),
        ((ru(r"\u043d\u0430\u0443\u0448\u043d\u0438\u043a"), "naushnik", "headphone", "earbuds", "airpods", ru(r"\u0433\u0430\u0440\u043d\u0438\u0442\u0443\u0440")), 4200, 0.45, 1200),
        ((ru(r"\u0447\u0430\u0441\u044b"), "watch", ru(r"\u0431\u0440\u0430\u0441\u043b\u0435\u0442")), 3800, 0.42, 850),
        ((ru(r"\u0444\u043e\u043d\u0430\u0440\u044c"), ru(r"\u0444\u043e\u043d\u0430\u0440\u0438\u043a"), "fonar", "flashlight", "nalob"), 1250, 0.38, 520),
        ((ru(r"\u043c\u043e\u043b\u043e\u0442\u043e\u043a"), "molotok", ru(r"\u0434\u0440\u0435\u043b\u044c"), "drel", "drill", ru(r"\u0448\u0443\u0440\u0443\u043f\u043e\u0432\u0435\u0440\u0442"), "shurupovert", ru(r"\u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442")), 2800, 0.36, 360),
        ((ru(r"\u0440\u044e\u043a\u0437\u0430\u043a"), ru(r"\u0441\u0443\u043c\u043a\u0430")), 2400, 0.40, 640),
        ((ru(r"\u043a\u0440\u043e\u0441\u0441\u043e\u0432"), ru(r"\u0431\u043e\u0442\u0438\u043d"), ru(r"\u043e\u0431\u0443\u0432")), 3600, 0.38, 780),
        ((ru(r"\u043a\u0443\u0440\u0442\u043a"), ru(r"\u0445\u0443\u0434\u0438"), ru(r"\u0444\u0443\u0442\u0431\u043e\u043b"), ru(r"\u043e\u0434\u0435\u0436")), 1900, 0.42, 900),
        ((ru(r"\u043a\u0440\u0435\u043c"), ru(r"\u0448\u0430\u043c\u043f\u0443\u043d"), ru(r"\u043a\u043e\u0441\u043c\u0435\u0442"), ru(r"\u043c\u0430\u0441\u043a\u0430")), 780, 0.34, 1100),
        ((ru(r"\u0438\u0433\u0440\u0443\u0448"), "lego", ru(r"\u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0442\u043e\u0440")), 1700, 0.43, 700),
        ((ru(r"\u043a\u043b\u0430\u0432\u0438\u0430\u0442"), ru(r"\u043c\u044b\u0448"), ru(r"\u043a\u043e\u0432\u0440\u0438\u043a")), 2600, 0.40, 650),
        ((ru(r"\u0447\u0430\u0439\u043d\u0438\u043a"), ru(r"\u043f\u044b\u043b\u0435\u0441\u043e\u0441"), ru(r"\u0431\u043b\u0435\u043d\u0434\u0435\u0440"), ru(r"\u0443\u0442\u044e\u0433")), 5200, 0.36, 540),
        ((ru(r"\u0447\u0435\u0445\u043e\u043b"), ru(r"\u043a\u0430\u0431\u0435\u043b\u044c"), ru(r"\u0437\u0430\u0440\u044f\u0434")), 650, 0.46, 1500),
    ]
    for keywords, base_price, spread, review_base in profiles:
        if any(word in text for word in keywords):
            return float(base_price), float(spread), int(review_base)
    seed = _seed_for("profile", text)
    rng = random.Random(seed)
    return float(rng.choice((900, 1400, 2200, 3200, 4800, 7200))), 0.42, int(rng.choice((350, 550, 800, 1100)))


def _iter_products(config: MarketplaceConfig, query: str, count: int) -> Iterable[dict[str, object]]:
    base_query = _clean_product_query(query)
    rng = random.Random(_seed_for(config.name, base_query))
    base_price, spread, review_base = _fallback_profile(base_query)
    marketplace_factor = {
        "Ozon": 1.04,
        "Wildberries": 0.96,
        "Yandex Market": 1.08,
    }.get(config.name, 1.0)
    tier_factors = (0.72, 0.94, 1.18, 1.45)
    tier_names = (
        ru(r"\u0431\u0430\u0437\u043e\u0432\u0430\u044f \u0432\u0435\u0440\u0441\u0438\u044f"),
        ru(r"\u043e\u043f\u0442\u0438\u043c\u0430\u043b\u044c\u043d\u044b\u0439 \u0432\u0430\u0440\u0438\u0430\u043d\u0442"),
        ru(r"\u043f\u043e\u043f\u0443\u043b\u044f\u0440\u043d\u0430\u044f \u043c\u043e\u0434\u0435\u043b\u044c"),
        ru(r"\u0440\u0430\u0441\u0448\u0438\u0440\u0435\u043d\u043d\u0430\u044f \u043a\u043e\u043c\u043f\u043b\u0435\u043a\u0442\u0430\u0446\u0438\u044f"),
    )

    for index in range(count):
        tier_index = index % len(config.category_templates)
        category = config.category_templates[tier_index]
        rank = index // len(config.category_templates)
        tier_factor = tier_factors[tier_index % len(tier_factors)]
        demand_factor = max(0.55, 1.18 - rank * 0.045)
        random_factor = rng.lognormvariate(0, spread / 2.8)
        price = int(max(120, base_price * marketplace_factor * tier_factor * random_factor))
        price = int(round(price / 10) * 10)
        rating_center = 4.62 - abs(tier_index - 2) * 0.07
        rating = round(min(5.0, max(3.7, rng.normalvariate(rating_center, 0.16))), 2)
        review_noise = rng.lognormvariate(0, 0.55)
        reviews = max(3, int(review_base * demand_factor * review_noise / (1 + tier_index * 0.22)))
        if config.name == "Ozon":
            reviews = int(reviews * 1.8)
        adjective = tier_names[tier_index % len(tier_names)]
        discount = rng.choice((0, 5, 7, 10, 12, 15))
        yield {
            "name": f"{base_query} - {adjective} {index + 1}",
            "description": f"{category.lower()}; " + ru(r"\u0446\u0435\u043d\u0430 \u043e\u043a\u043e\u043b\u043e \u0440\u044b\u043d\u043a\u0430; \u0441\u043a\u0438\u0434\u043a\u0430 ") + f"{discount}%",
            "price": price,
            "reviews": reviews,
            "rating": rating,
            "category": category,
            "marketplace": config.name,
            "url": "",
            "data_source": "synthetic_fallback",
        }

def _fallback_products(config: MarketplaceConfig, query: str, count: int, reason: str = "") -> pd.DataFrame:
    frame = pd.DataFrame(_iter_products(config, query, count))
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame["reviews"] = pd.to_numeric(frame["reviews"], errors="coerce").fillna(0).astype(int)
    frame["rating"] = pd.to_numeric(frame["rating"], errors="coerce").fillna(0)
    frame["fallback_reason"] = reason[:180]
    return frame


def _fetch_json(url: str, params: dict[str, object], timeout: int = 12) -> dict[str, object]:
    response = requests.get(url, params=params, headers={**HTTP_HEADERS, "Accept": "application/json"}, timeout=timeout)
    if response.status_code == 429:
        raise RuntimeError("marketplace returned 429 Too Many Requests")
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        text = response.text.strip()
        if text.startswith("callback(") and text.endswith(")"):
            return json.loads(text[len("callback("):-1])
        raise RuntimeError(f"marketplace returned non-json response: {text[:80]}") from exc


def _fetch_html(url: str, timeout: int = 15) -> str:
    response = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def _wildberries_products(query: str, count: int) -> pd.DataFrame:
    config = MARKETPLACES["wildberries"]
    rows: list[dict[str, object]] = []
    endpoints = [
        "https://search.wb.ru/exactmatch/ru/common/v13/search",
        "https://search.wb.ru/exactmatch/ru/common/v9/search",
        "https://search.wb.ru/exactmatch/sng/common/v9/search",
        "https://search.wb.ru/exactmatch/ru/common/v5/search",
        "https://search.wb.ru/exactmatch/ru/common/v4/search",
    ]
    for endpoint in endpoints:
        for page in range(1, 4):
            params = {
                "ab_testing": "false",
                "appType": 1,
                "curr": "rub",
                "dest": -1257786,
                "query": query,
                "resultset": "catalog",
                "sort": "popular",
                "spp": 30,
                "suppressSpellcheck": "false",
                "page": page,
            }
            payload = _fetch_json(endpoint, params)
            products = payload.get("data", {}).get("products", []) if isinstance(payload, dict) else []
            if not products:
                continue
            for product in products:
                price = product.get("salePriceU") or product.get("priceU") or 0
                brand = str(product.get("brand") or "").strip()
                name = str(product.get("name") or "").strip()
                subject = str(product.get("subjectName") or product.get("entity") or ru(r"\u0422\u043e\u0432\u0430\u0440\u044b"))
                nm_id = product.get("id") or product.get("nmId")
                rows.append({
                    "name": f"{brand} {name}".strip() or query,
                    "description": f"{brand} {subject}".strip(),
                    "price": _to_float(price) / 100 if _to_float(price) > 10000 else _to_float(price),
                    "reviews": _to_int(product.get("feedbacks") or product.get("reviewCount")),
                    "rating": _to_float(product.get("reviewRating") or product.get("rating")),
                    "category": subject,
                    "marketplace": config.name,
                    "url": f"https://www.wildberries.ru/catalog/{nm_id}/detail.aspx" if nm_id else "",
                    "data_source": "wildberries_search_api",
                })
                if len(rows) >= count:
                    return _normalize_frame(rows, config, query, count)
            if len(rows) >= count:
                break
        if rows:
            break
    return _normalize_frame(rows, config, query, count)


def _jsonld_objects(html: str) -> list[object]:
    objects: list[object] = []
    pattern = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
    for match in pattern.finditer(html):
        raw = re.sub(r"\s+", " ", match.group(1)).strip()
        try:
            objects.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return objects


def _flatten_jsonld(value: object) -> Iterable[dict[str, object]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _flatten_jsonld(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _flatten_jsonld(item)


def _products_from_jsonld(html: str, base_url: str, marketplace_name: str, query: str) -> list[dict[str, object]]:
    rows = []
    for node in _flatten_jsonld(_jsonld_objects(html)):
        node_type = node.get("@type")
        if isinstance(node_type, list):
            is_product = "Product" in node_type
        else:
            is_product = node_type == "Product"
        if not is_product:
            continue
        offers = node.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        rating = node.get("aggregateRating") or {}
        price = offers.get("price") or offers.get("lowPrice") or offers.get("highPrice")
        name = str(node.get("name") or query)
        url = str(node.get("url") or offers.get("url") or "")
        rows.append({
            "name": name,
            "description": str(node.get("description") or name),
            "price": _to_float(price),
            "reviews": _to_int(rating.get("reviewCount") or rating.get("ratingCount")),
            "rating": _to_float(rating.get("ratingValue")),
            "category": ru(r"\u041f\u043e\u0438\u0441\u043a"),
            "marketplace": marketplace_name,
            "url": urljoin(base_url, url) if url else base_url,
            "data_source": "jsonld_html",
        })
    return rows


def _embedded_product_rows(html: str, marketplace_name: str, base_url: str, query: str) -> list[dict[str, object]]:
    rows = []
    # Lightweight fallback for pages that expose product snippets in embedded JSON.
    for match in re.finditer(r'"name"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)".{0,800}?"price"\s*:\s*"?(\d+[\d\s.,]*)', html, re.S):
        try:
            name = json.loads('"' + match.group(1) + '"')
        except json.JSONDecodeError:
            name = match.group(1)
        rows.append({
            "name": name,
            "description": name,
            "price": _to_float(match.group(2)),
            "reviews": 0,
            "rating": 0.0,
            "category": ru(r"\u041f\u043e\u0438\u0441\u043a"),
            "marketplace": marketplace_name,
            "url": base_url,
            "data_source": "embedded_html",
        })
        if len(rows) >= 60:
            break
    return rows


def _html_market_products(key: str, query: str, count: int) -> pd.DataFrame:
    config = MARKETPLACES[key]
    encoded = quote_plus(query)
    if is_url(query):
        url = query
    elif key == "ozon":
        url = f"https://www.ozon.ru/search/?text={encoded}"
    else:
        url = f"https://market.yandex.ru/search?text={encoded}"
    html = _fetch_html(url)
    rows = _products_from_jsonld(html, url, config.name, _clean_product_query(query))
    if len(rows) < 3:
        rows.extend(_embedded_product_rows(html, config.name, url, query))
    return _normalize_frame(rows, config, query, count)


def _text_from_selectors(element: object, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        try:
            value = element.find_element("css selector", selector).text.strip()
            if value:
                return value
        except Exception:
            continue
    return ""


def _selenium_market_products(key: str, query: str, count: int) -> pd.DataFrame:
    config = MARKETPLACES[key]
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from webdriver_manager.chrome import ChromeDriverManager
    except Exception as exc:
        raise RuntimeError("Selenium parser is not installed. Run: pip install selenium webdriver-manager") from exc

    encoded = quote_plus(query)
    if key == "wildberries":
        url = f"https://www.wildberries.ru/catalog/0/search.aspx?search={encoded}"
        card_selectors = ("article.product-card", "div.product-card__wrapper", "div.product-card")
        name_selectors = ("span.product-card__name", "span.goods-name", "a.product-card__link")
        price_selectors = ("ins.price__lower-price", "ins.lower-price", "span.price__lower-price", "span.wallet-price")
        rating_selectors = ("span.address-rate-mini", "span.product-card__rating", "span.rating")
        review_selectors = ("span.product-card__count", "span.product-card__feedback", "span.feedbacks")
    elif key == "ozon":
        url = f"https://www.ozon.ru/search/?text={encoded}"
        card_selectors = ("div[data-widget='searchResultsV2'] div.tile-root", "div[data-widget='searchResultsV2'] a[href*='/product/']", "a[href*='/product/']")
        name_selectors = ("span.tsBody500Medium", "span.tsBodyL", "span", "div")
        price_selectors = ("span.tsHeadline500Medium", "span[class*='price']", "div[class*='price']")
        rating_selectors = ("span.ui-ratings-reviews__rating", "span[class*='rating']")
        review_selectors = ("span.ui-ratings-reviews__reviews-count", "span[class*='review']")
    else:
        url = f"https://market.yandex.ru/search?text={encoded}"
        card_selectors = ("article[data-auto='product-snippet']", "div[data-apiary-widget-name='@MarketNode/ProductSnippet']", "article")
        name_selectors = ("h3", "span[data-auto='snippet-title']", "a[data-auto='snippet-title']")
        price_selectors = ("span[data-auto='snippet-price-current']", "span[data-auto='price-value']", "span[class*='price']")
        rating_selectors = ("span[data-auto='rating-badge-value']", "span[class*='rating']")
        review_selectors = ("span[data-auto='rating-badge-text']", "span[class*='review']")
    if is_url(query):
        url = query

    options = Options()
    if os.getenv("MARKETPLACE_BROWSER_VISIBLE", "0") != "1":
        options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1440,1200")
    options.add_argument("--lang=ru-RU")
    options.add_argument(f"--user-agent={HTTP_HEADERS['User-Agent']}")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    rows: list[dict[str, object]] = []
    try:
        driver.get(url)
        time.sleep(float(os.getenv("MARKETPLACE_BROWSER_WAIT", "6")))
        page_text = driver.page_source.lower()
        if "captcha" in page_text or ru(r"\u043a\u0430\u043f\u0447") in page_text or ru(r"\u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u0435") in page_text:
            if os.getenv("MARKETPLACE_BROWSER_VISIBLE", "0") == "1":
                wait_seconds = float(os.getenv("MARKETPLACE_MANUAL_CAPTCHA_WAIT", "60"))
                print(ru(r"\u0421\u0430\u0439\u0442 \u043f\u043e\u043a\u0430\u0437\u0430\u043b \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443. \u041f\u0440\u043e\u0439\u0434\u0438\u0442\u0435 \u0435\u0435 \u0432 \u043e\u043a\u043d\u0435 \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0430, \u0435\u0441\u0442\u044c ") + f"{wait_seconds:.0f} " + ru(r"\u0441\u0435\u043a."))
                time.sleep(wait_seconds)
                page_text = driver.page_source.lower()
            if "captcha" in page_text or ru(r"\u043a\u0430\u043f\u0447") in page_text or ru(r"\u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u0435") in page_text:
                raise RuntimeError("marketplace showed captcha")
        for _ in range(3):
            driver.execute_script("window.scrollBy(0, document.body.scrollHeight / 3)")
            time.sleep(1.2)

        cards = []
        for selector in card_selectors:
            found = driver.find_elements(By.CSS_SELECTOR, selector)
            if len(found) > len(cards):
                cards = found
            if len(cards) >= count:
                break

        seen = set()
        for card in cards:
            name = _text_from_selectors(card, name_selectors).lstrip("/ ").strip()
            price_text = _text_from_selectors(card, price_selectors)
            price = _to_float(price_text)
            if not name or price <= 0:
                continue
            if (name, price) in seen:
                continue
            seen.add((name, price))
            rating = _to_float(_text_from_selectors(card, rating_selectors))
            reviews = _to_int(_text_from_selectors(card, review_selectors))
            try:
                href = card.get_attribute("href") or card.find_element(By.CSS_SELECTOR, "a").get_attribute("href") or url
            except Exception:
                href = url
            rows.append({
                "name": name[:180],
                "description": name[:240],
                "price": price,
                "reviews": reviews,
                "rating": rating,
                "category": ru(r"\u041f\u043e\u0438\u0441\u043a"),
                "marketplace": config.name,
                "url": href,
                "data_source": "selenium_browser",
            })
            if len(rows) >= count:
                break
    finally:
        driver.quit()

    frame = _normalize_frame(rows, config, query, count)
    if frame.empty:
        raise RuntimeError("Selenium opened the page but found no product cards")
    return frame


def get_marketplace_products(marketplace: str, query: str, count: int = 32, allow_fallback: bool = True) -> pd.DataFrame:
    key = normalize_marketplace(marketplace)
    if key not in MARKETPLACES:
        raise ValueError(ru(r"\u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u044b\u0439 \u043c\u0430\u0440\u043a\u0435\u0442\u043f\u043b\u0435\u0439\u0441: ") + marketplace)
    config = MARKETPLACES[key]
    if os.getenv("MARKETPLACE_DEMO_ONLY", "0") == "1" and allow_fallback:
        return _fallback_products(config, query, count, "MARKETPLACE_DEMO_ONLY=1")
    errors: list[str] = []
    try:
        if key == "wildberries":
            frame = _wildberries_products(query, count)
        else:
            frame = _html_market_products(key, query, count)
        if not frame.empty:
            return frame.head(count).reset_index(drop=True)
        raise RuntimeError("empty real marketplace response")
    except Exception as exc:
        errors.append(f"fast parser: {exc}")

    try:
        frame = _selenium_market_products(key, query, count)
        if not frame.empty:
            return frame.head(count).reset_index(drop=True)
        raise RuntimeError("empty selenium response")
    except Exception as exc:
        errors.append(f"selenium parser: {exc}")

    message = " | ".join(errors)
    if not allow_fallback:
        raise RuntimeError(message)
    return _fallback_products(config, query, count, message)
