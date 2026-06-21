from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import hashlib
import html
import math
import os

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "4")

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest, RandomForestRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, silhouette_score

from .marketplace import MARKETPLACES, normalize_marketplace, ru


@dataclass(frozen=True)
class ForecastResult:
    history: pd.DataFrame
    future: pd.DataFrame
    mae: float
    accuracy: float
    trend_slope: float
    monthly_change: float
    monthly_change_pct: float
    volatility_pct: float
    risk_level: str
    trend_label: str
    confidence_level: float = 0.95


@dataclass(frozen=True)
class BusinessCosts:
    purchase_cost: float = 0.0
    logistics: float = 0.0
    packaging: float = 0.0
    ads: float = 0.0
    other: float = 0.0


@dataclass(frozen=True)
class FinancialResult:
    fixed_cost: float
    commission_rate: float
    commission_value: float
    margin: float
    roi: float
    break_even_price: float
    suggested_min_price: float
    score: float
    market_position: str


def cluster_products(products: pd.DataFrame, max_clusters: int = 4) -> tuple[pd.DataFrame, list[str], float]:
    if products.empty:
        raise ValueError(ru(r"\u041d\u0435\u0442 \u0442\u043e\u0432\u0430\u0440\u043e\u0432 \u0434\u043b\u044f \u043a\u043b\u0430\u0441\u0442\u0435\u0440\u0438\u0437\u0430\u0446\u0438\u0438"))

    frame = products.copy()
    frame["text"] = frame["name"].fillna("") + " " + frame["description"].fillna("") + " " + frame["category"].fillna("")
    categories = frame["category"].dropna().astype(str).unique().tolist() or [ru(r"\u041e\u0431\u0449\u0430\u044f \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044f")]
    n_clusters = max(1, min(max_clusters, len(frame), len(categories)))

    if n_clusters == 1:
        frame["cluster"] = 0
        frame["cluster_name"] = categories[0]
        return frame, [categories[0]], 0.0

    matrix = TfidfVectorizer(max_features=1000, ngram_range=(1, 2)).fit_transform(frame["text"])
    labels = KMeans(n_clusters=n_clusters, random_state=42, n_init=10).fit_predict(matrix)
    frame["cluster"] = labels

    cluster_names: list[str] = []
    for cluster_id in sorted(set(labels)):
        subset = frame[frame["cluster"] == cluster_id]
        name = subset["category"].mode().iat[0] if not subset["category"].mode().empty else ru(r"\u041a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044f ") + str(cluster_id + 1)
        cluster_names.append(str(name))
        frame.loc[frame["cluster"] == cluster_id, "cluster_name"] = str(name)

    try:
        score = float(silhouette_score(matrix, labels))
    except Exception:
        score = 0.0
    return frame, cluster_names, score


def build_price_history(category: str, marketplace: str, base_price: float, days: int = 180) -> pd.DataFrame:
    raw_seed = f"{category}|{marketplace}|{round(base_price)}".encode("utf-8")
    seed = int(hashlib.sha256(raw_seed).hexdigest()[:12], 16) % (2**32)
    rng = np.random.default_rng(seed)
    dates = [datetime.now().date() - timedelta(days=days - day - 1) for day in range(days)]
    trend = rng.uniform(-0.0025, 0.0035)
    month_season = np.sin(np.linspace(0, 6 * np.pi, days)) * rng.uniform(0.025, 0.075)
    week_season = np.sin(np.linspace(0, 2 * np.pi * days / 7, days)) * rng.uniform(0.005, 0.018)
    promo_shock = np.zeros(days)
    for promo_start in rng.choice(np.arange(20, max(21, days - 20)), size=4, replace=False):
        promo_shock[promo_start:promo_start + 5] += rng.uniform(-0.06, 0.04)
    noise = rng.normal(0, 0.028, days)
    prices = [max(50, base_price * (1 + trend * idx + month_season[idx] + week_season[idx] + promo_shock[idx] + noise[idx])) for idx in range(days)]
    return clean_price_history(pd.DataFrame({"date": pd.to_datetime(dates), "price": prices}))


def clean_price_history(history: pd.DataFrame) -> pd.DataFrame:
    frame = history.copy()
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce").interpolate().bfill().ffill()
    if len(frame) >= 30:
        mask = IsolationForest(contamination=0.04, random_state=42).fit_predict(frame[["price"]]) == 1
        filtered = frame[mask].copy()
        if len(filtered) >= 120:
            frame = filtered
    return frame.sort_values("date").reset_index(drop=True)


def _make_features(days: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({
        "day": days,
        "week_sin": np.sin(2 * np.pi * days / 7),
        "week_cos": np.cos(2 * np.pi * days / 7),
        "month_sin": np.sin(2 * np.pi * days / 30),
        "month_cos": np.cos(2 * np.pi * days / 30),
    })


def _risk_level(volatility_pct: float, accuracy: float, monthly_change_pct: float) -> str:
    if volatility_pct > 12 or accuracy < 88 or monthly_change_pct < -8:
        return ru(r"\u0432\u044b\u0441\u043e\u043a\u0438\u0439")
    if volatility_pct > 7 or accuracy < 94 or monthly_change_pct < -3:
        return ru(r"\u0441\u0440\u0435\u0434\u043d\u0438\u0439")
    return ru(r"\u043d\u0438\u0437\u043a\u0438\u0439")


def _trend_label(monthly_change_pct: float) -> str:
    if monthly_change_pct > 5:
        return ru(r"\u0443\u0441\u0442\u043e\u0439\u0447\u0438\u0432\u044b\u0439 \u0440\u043e\u0441\u0442")
    if monthly_change_pct > 1:
        return ru(r"\u0441\u043b\u0430\u0431\u044b\u0439 \u0440\u043e\u0441\u0442")
    if monthly_change_pct < -5:
        return ru(r"\u0437\u0430\u043c\u0435\u0442\u043d\u043e\u0435 \u0441\u043d\u0438\u0436\u0435\u043d\u0438\u0435")
    if monthly_change_pct < -1:
        return ru(r"\u0441\u043b\u0430\u0431\u043e\u0435 \u0441\u043d\u0438\u0436\u0435\u043d\u0438\u0435")
    return ru(r"\u0431\u043e\u043a\u043e\u0432\u043e\u0439 \u0442\u0440\u0435\u043d\u0434")


def forecast_prices(history: pd.DataFrame, horizon: int = 30) -> ForecastResult:
    frame = history.copy().reset_index(drop=True)
    frame["day"] = np.arange(len(frame))
    split_at = max(30, int(len(frame) * 0.82))
    train = frame.iloc[:split_at]
    test = frame.iloc[split_at:]
    ridge = Ridge(alpha=8.0)
    ridge.fit(_make_features(train["day"].to_numpy()), train["price"])
    rf = RandomForestRegressor(n_estimators=220, random_state=42, min_samples_leaf=3)
    rf.fit(_make_features(train["day"].to_numpy()), train["price"])
    test_features = _make_features(test["day"].to_numpy())
    predicted_test = (ridge.predict(test_features) * 0.72 + rf.predict(test_features) * 0.28) if len(test) else np.array([])
    mae = float(mean_absolute_error(test["price"], predicted_test)) if len(test) else 0.0
    future_days = np.arange(len(frame), len(frame) + horizon)
    future_prices = ridge.predict(_make_features(future_days)) * 0.72 + rf.predict(_make_features(future_days)) * 0.28
    residuals = (test["price"].to_numpy() - predicted_test) if len(test) else frame["price"].to_numpy() - ridge.predict(_make_features(frame["day"].to_numpy()))
    residual_std = float(np.std(residuals)) if len(residuals) else max(mae, 1.0)
    if residual_std <= 0:
        residual_std = max(mae, float(frame["price"].std() * 0.15), 1.0)
    interval = 1.96 * residual_std * (1 + np.linspace(0.0, 0.55, horizon))
    future_dates = [frame["date"].iloc[-1] + timedelta(days=i + 1) for i in range(horizon)]
    future = pd.DataFrame({"date": future_dates, "price": future_prices, "lower": np.maximum(1, future_prices - interval), "upper": future_prices + interval})
    slope = float(np.polyfit(frame["day"], frame["price"], 1)[0]) if len(frame) > 1 else 0.0
    monthly_change = float(future["price"].iloc[-1] - frame["price"].iloc[-1])
    monthly_change_pct = monthly_change / max(float(frame["price"].iloc[-1]), 1.0) * 100
    returns = frame["price"].pct_change().dropna()
    volatility_pct = float(returns.std() * math.sqrt(30) * 100) if len(returns) else 0.0
    accuracy = max(0.0, 100.0 - (mae / max(float(frame["price"].mean()), 1.0) * 100.0))
    return ForecastResult(frame[["date", "price"]], future, mae, accuracy, slope, monthly_change, monthly_change_pct, volatility_pct, _risk_level(volatility_pct, accuracy, monthly_change_pct), _trend_label(monthly_change_pct))


def parse_costs(text: str) -> BusinessCosts:
    cleaned = text.lower().replace(",", ".").replace(";", " ")
    if cleaned.strip() in {"0", "skip", "auto", ru(r"\u0430\u0432\u0442\u043e"), ru(r"\u043f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442\u044c")}:
        return BusinessCosts()
    values = []
    for part in cleaned.split():
        try:
            values.append(float(part))
        except ValueError:
            continue
    values += [0.0] * (5 - len(values))
    return BusinessCosts(*values[:5])


def competitor_summary(products: pd.DataFrame, category: str) -> dict[str, float | int | str]:
    subset = products[products.get("cluster_name", products.get("category")) == category].copy()
    if subset.empty:
        subset = products.copy()
    prices = pd.to_numeric(subset["price"], errors="coerce").dropna()
    ratings = pd.to_numeric(subset["rating"], errors="coerce").dropna()
    reviews = pd.to_numeric(subset["reviews"], errors="coerce").dropna()
    return {
        "count": int(len(subset)),
        "min_price": float(prices.min()),
        "median_price": float(prices.median()),
        "avg_price": float(prices.mean()),
        "max_price": float(prices.max()),
        "avg_rating": float(ratings.mean()) if len(ratings) else 0.0,
        "total_reviews": int(reviews.sum()) if len(reviews) else 0,
    }


def calculate_financials(avg_price: float, costs: BusinessCosts, marketplace: str, popularity: float, forecast: ForecastResult, market: dict[str, float | int | str]) -> FinancialResult:
    config = MARKETPLACES.get(normalize_marketplace(marketplace))
    commission_rate = config.commission_rate if config else 0.18
    fixed_cost = costs.purchase_cost + costs.logistics + costs.packaging + costs.ads + costs.other
    if fixed_cost <= 0:
        fixed_cost = avg_price * 0.80
    commission_value = avg_price * commission_rate
    margin = avg_price - commission_value - fixed_cost
    roi = margin / max(fixed_cost, 1.0)
    break_even_price = fixed_cost / max(1 - commission_rate, 0.01)
    suggested_min_price = break_even_price * 1.12
    median_price = float(market["median_price"])
    if avg_price < median_price * 0.95:
        market_position = ru(r"\u043d\u0438\u0436\u0435 \u0440\u044b\u043d\u043a\u0430")
    elif avg_price > median_price * 1.05:
        market_position = ru(r"\u0432\u044b\u0448\u0435 \u0440\u044b\u043d\u043a\u0430")
    else:
        market_position = ru(r"\u043e\u043a\u043e\u043b\u043e \u0440\u044b\u043d\u043a\u0430")
    score = product_score(roi, popularity, forecast, avg_price, median_price)
    return FinancialResult(fixed_cost, commission_rate, commission_value, margin, roi, break_even_price, suggested_min_price, score, market_position)


def product_score(roi: float, popularity: float, forecast: ForecastResult, avg_price: float, median_price: float) -> float:
    score = 50.0
    score += min(max(roi * 100, -25), 30)
    score += min(max(forecast.monthly_change_pct * 1.4, -18), 18)
    score += min(popularity * 18, 18)
    score += max(0, 10 - forecast.volatility_pct * 0.8)
    if avg_price <= median_price * 1.03:
        score += 7
    else:
        score -= 6
    if forecast.risk_level == ru(r"\u0432\u044b\u0441\u043e\u043a\u0438\u0439"):
        score -= 12
    elif forecast.risk_level == ru(r"\u0441\u0440\u0435\u0434\u043d\u0438\u0439"):
        score -= 5
    return round(min(100, max(0, score)), 1)


def build_alerts(fin: FinancialResult, forecast: ForecastResult, market: dict[str, float | int | str]) -> list[str]:
    alerts = []
    if fin.margin < 0:
        alerts.append(ru(r"\u0426\u0435\u043d\u0430 \u043d\u0438\u0436\u0435 \u0442\u043e\u0447\u043a\u0438 \u0431\u0435\u0437\u0443\u0431\u044b\u0442\u043e\u0447\u043d\u043e\u0441\u0442\u0438."))
    if forecast.monthly_change_pct < -5:
        alerts.append(ru(r"\u041f\u0440\u043e\u0433\u043d\u043e\u0437 \u043f\u043e\u043a\u0430\u0437\u044b\u0432\u0430\u0435\u0442 \u0441\u043d\u0438\u0436\u0435\u043d\u0438\u0435 \u0446\u0435\u043d\u044b/\u0441\u043f\u0440\u043e\u0441\u0430."))
    if forecast.volatility_pct > 12:
        alerts.append(ru(r"\u0426\u0435\u043d\u0430 \u0441\u0438\u043b\u044c\u043d\u043e \u0441\u043a\u0430\u0447\u0435\u0442: \u043d\u0443\u0436\u0435\u043d \u0437\u0430\u043f\u0430\u0441 \u043f\u0440\u0438\u0431\u044b\u043b\u0438."))
    if int(market["count"]) > 35:
        alerts.append(ru(r"\u0412 \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u0438 \u043c\u043d\u043e\u0433\u043e \u043a\u043e\u043d\u043a\u0443\u0440\u0435\u043d\u0442\u043e\u0432."))
    return alerts or [ru(r"\u041a\u0440\u0438\u0442\u0438\u0447\u043d\u044b\u0445 \u0441\u0438\u0433\u043d\u0430\u043b\u043e\u0432 \u043d\u0435\u0442.")]


def _business_ideas(fin: FinancialResult, popularity: float, forecast: ForecastResult) -> list[str]:
    ideas = []
    if forecast.monthly_change_pct > 4 and fin.roi > 0:
        ideas.append(ru(r"\u0423\u0432\u0435\u043b\u0438\u0447\u0438\u0442\u044c \u0437\u0430\u043f\u0430\u0441 \u043d\u0430 15-25%, \u043f\u043e\u043a\u0430 \u0446\u0435\u043d\u0430 \u0438 \u0441\u043f\u0440\u043e\u0441 \u0438\u0434\u0443\u0442 \u0432\u0432\u0435\u0440\u0445."))
    if forecast.monthly_change_pct < -3:
        ideas.append(ru(r"\u041f\u0440\u043e\u0432\u0435\u0441\u0442\u0438 \u0430\u043a\u0446\u0438\u044e \u0438\u043b\u0438 \u0441\u043d\u0438\u0437\u0438\u0442\u044c \u0446\u0435\u043d\u0443 \u043d\u0430 3-7%, \u0447\u0442\u043e\u0431\u044b \u043d\u0435 \u043f\u043e\u0442\u0435\u0440\u044f\u0442\u044c \u043e\u0431\u043e\u0440\u043e\u0442."))
    if forecast.volatility_pct > 8:
        ideas.append(ru(r"\u041e\u0441\u0442\u0430\u0432\u0438\u0442\u044c \u0437\u0430\u043f\u0430\u0441 \u043f\u0440\u0438\u0431\u044b\u043b\u0438: \u0446\u0435\u043d\u0430 \u043c\u043e\u0436\u0435\u0442 \u0440\u0435\u0437\u043a\u043e \u043c\u0435\u043d\u044f\u0442\u044c\u0441\u044f."))
    if popularity < 0.35:
        ideas.append(ru(r"\u0423\u0441\u0438\u043b\u0438\u0442\u044c \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0443: \u0444\u043e\u0442\u043e, SEO-\u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435, \u043a\u043b\u044e\u0447\u0438 \u0438 \u043e\u0442\u0432\u0435\u0442\u044b."))
    if fin.roi < 0.05:
        ideas.append(ru(r"\u041f\u0435\u0440\u0435\u0441\u0447\u0438\u0442\u0430\u0442\u044c \u0437\u0430\u043a\u0443\u043f\u043a\u0443, \u043b\u043e\u0433\u0438\u0441\u0442\u0438\u043a\u0443 \u0438 \u0440\u0435\u043a\u043b\u0430\u043c\u0443: \u043c\u0430\u0440\u0436\u0430 \u0441\u043b\u0430\u0431\u0430\u044f."))
    ideas.append(ru(r"\u0412\u0435\u0441\u0442\u0438 \u0435\u0436\u0435\u043d\u0435\u0434\u0435\u043b\u044c\u043d\u044b\u0439 \u043c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433 \u043a\u043e\u043d\u043a\u0443\u0440\u0435\u043d\u0442\u043e\u0432: \u0446\u0435\u043d\u0430, \u043e\u0442\u0437\u044b\u0432\u044b, \u0440\u0435\u0439\u0442\u0438\u043d\u0433."))
    return ideas[:5]




def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " " + ru(r"\u0440\u0443\u0431.")


def _short_risk_text(forecast: ForecastResult) -> str:
    if forecast.risk_level == ru(r"\u0432\u044b\u0441\u043e\u043a\u0438\u0439"):
        return ru(r"\u0446\u0435\u043d\u0430 \u043c\u043e\u0436\u0435\u0442 \u0441\u0438\u043b\u044c\u043d\u043e \u0433\u0443\u043b\u044f\u0442\u044c")
    if forecast.risk_level == ru(r"\u0441\u0440\u0435\u0434\u043d\u0438\u0439"):
        return ru(r"\u0435\u0441\u0442\u044c \u0443\u043c\u0435\u0440\u0435\u043d\u043d\u044b\u0435 \u043a\u043e\u043b\u0435\u0431\u0430\u043d\u0438\u044f")
    return ru(r"\u0440\u044b\u043d\u043e\u043a \u0434\u043e\u0432\u043e\u043b\u044c\u043d\u043e \u0441\u043f\u043e\u043a\u043e\u0439\u043d\u044b\u0439")


def analyze_product(clustered: pd.DataFrame, category: str, marketplace: str, forecast: ForecastResult, costs: BusinessCosts | None = None) -> tuple[str, FinancialResult, dict[str, float | int | str], list[str]]:
    subset = clustered[clustered["cluster_name"] == category].copy()
    if subset.empty:
        subset = clustered.copy()
    market = competitor_summary(clustered, category)
    avg_price = float(subset["price"].mean())
    avg_rating = float(subset["rating"].mean())
    total_reviews = int(subset["reviews"].sum())
    config = MARKETPLACES.get(normalize_marketplace(marketplace))
    review_cap = config.review_cap if config else 1000
    popularity = min(1.0, (total_reviews / max(review_cap, 1)) * 0.65 + (avg_rating / 5.0) * 0.35)
    fin = calculate_financials(avg_price, costs or BusinessCosts(), marketplace, popularity, forecast, market)
    alerts = build_alerts(fin, forecast, market)
    ideas = _business_ideas(fin, popularity, forecast)
    low = float(forecast.future["lower"].min())
    high = float(forecast.future["upper"].max())
    expected_end = float(forecast.future["price"].iloc[-1])

    recommendation = ru(r"\u0422\u043e\u0432\u0430\u0440 \u043c\u043e\u0436\u043d\u043e \u0442\u0435\u0441\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u043d\u0435\u0431\u043e\u043b\u044c\u0448\u043e\u0439 \u043f\u0430\u0440\u0442\u0438\u0435\u0439. \u0413\u043b\u0430\u0432\u043d\u043e\u0435 - \u0441\u043b\u0435\u0434\u0438\u0442\u044c \u0437\u0430 \u0446\u0435\u043d\u043e\u0439 \u0438 \u043c\u0430\u0440\u0436\u043e\u0439.")
    if fin.score >= 75 and fin.roi > 0 and forecast.monthly_change_pct > 0:
        recommendation = ru(r"\u0421\u0438\u0433\u043d\u0430\u043b \u0445\u043e\u0440\u043e\u0448\u0438\u0439: \u0435\u0441\u0442\u044c \u0441\u043f\u0440\u043e\u0441, \u0437\u0430\u043f\u0430\u0441 \u043f\u043e \u043f\u0440\u0438\u0431\u044b\u043b\u0438 \u0438 \u043d\u0435\u043f\u043b\u043e\u0445\u043e\u0439 \u043f\u0440\u043e\u0433\u043d\u043e\u0437.")
    elif fin.score < 45 or fin.margin < 0:
        recommendation = ru(r"\u0421\u0438\u0433\u043d\u0430\u043b \u0441\u043b\u0430\u0431\u044b\u0439: \u0431\u0435\u0437 \u043f\u0435\u0440\u0435\u0441\u0447\u0435\u0442\u0430 \u0446\u0435\u043d\u044b \u0438 \u0440\u0430\u0441\u0445\u043e\u0434\u043e\u0432 \u043b\u0443\u0447\u0448\u0435 \u043d\u0435 \u0437\u0430\u0445\u043e\u0434\u0438\u0442\u044c.")

    def line(label: str, value: str) -> str:
        return f"{label}: {value}"

    safe_category = html.escape(str(category))
    alerts_text = "\n".join(f"- {html.escape(item)}" for item in alerts)
    ideas_text = "\n".join(f"- {html.escape(item)}" for item in ideas[:4])
    reviews_text = f"{int(market['total_reviews']):,}".replace(",", " ")
    change_text = f"{forecast.monthly_change:+,.0f}".replace(",", " ") + " " + ru(r"\u0440\u0443\u0431.") + f" ({forecast.monthly_change_pct:+.1f}%)"

    text = (
        f"<b>{ru(r'\u041a\u043e\u0440\u043e\u0442\u043a\u043e')}</b>\n"
        + line(ru(r"\u041a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044f"), safe_category) + "\n"
        + line(ru(r"\u041e\u0446\u0435\u043d\u043a\u0430"), f"<b>{fin.score:.0f}/100</b>") + "\n"
        + line(ru(r"\u0420\u0435\u0448\u0435\u043d\u0438\u0435"), html.escape(recommendation)) + "\n\n"
        + f"<b>{ru(r'\u0420\u044b\u043d\u043e\u043a \u0441\u0435\u0439\u0447\u0430\u0441')}</b>\n"
        + line(ru(r"\u0422\u043e\u0432\u0430\u0440\u043e\u0432 \u0432 \u0432\u044b\u0431\u043e\u0440\u043a\u0435"), str(int(market["count"]))) + "\n"
        + line(ru(r"\u0421\u0440\u0435\u0434\u043d\u044f\u044f \u0446\u0435\u043d\u0430"), _money(avg_price)) + "\n"
        + line(ru(r"\u041e\u0431\u044b\u0447\u043d\u044b\u0439 \u0434\u0438\u0430\u043f\u0430\u0437\u043e\u043d"), f"{_money(float(market['min_price']))} - {_money(float(market['max_price']))}") + "\n"
        + line(ru(r"\u041e\u0442\u0437\u044b\u0432\u044b \u0432 \u0433\u0440\u0443\u043f\u043f\u0435"), reviews_text) + "\n"
        + line(ru(r"\u0421\u0440\u0435\u0434\u043d\u0438\u0439 \u0440\u0435\u0439\u0442\u0438\u043d\u0433"), f"{avg_rating:.2f}/5") + "\n\n"
        + f"<b>{ru(r'\u041f\u0440\u043e\u0433\u043d\u043e\u0437 \u043d\u0430 \u043c\u0435\u0441\u044f\u0446')}</b>\n"
        + line(ru(r"\u0426\u0435\u043d\u0430 \u043a \u043a\u043e\u043d\u0446\u0443 \u043c\u0435\u0441\u044f\u0446\u0430"), _money(expected_end)) + "\n"
        + line(ru(r"\u0412\u043e\u0437\u043c\u043e\u0436\u043d\u044b\u0439 \u043a\u043e\u0440\u0438\u0434\u043e\u0440"), f"{_money(low)} - {_money(high)}") + "\n"
        + line(ru(r"\u041d\u0430\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435"), f"{forecast.trend_label}, {change_text}") + "\n"
        + line(ru(r"\u0420\u0438\u0441\u043a"), f"{forecast.risk_level}: {_short_risk_text(forecast)}") + "\n\n"
        + f"<b>{ru(r'\u0414\u0435\u043d\u044c\u0433\u0438')}</b>\n"
        + line(ru(r"\u0412\u0430\u0448\u0438 \u0440\u0430\u0441\u0445\u043e\u0434\u044b \u043d\u0430 1 \u0448\u0442."), _money(fin.fixed_cost)) + "\n"
        + line(ru(r"\u041c\u0438\u043d\u0438\u043c\u0443\u043c \u0431\u0435\u0437 \u0443\u0431\u044b\u0442\u043a\u0430"), _money(fin.break_even_price)) + "\n"
        + line(ru(r"\u041a\u043e\u043c\u0444\u043e\u0440\u0442\u043d\u0430\u044f \u0446\u0435\u043d\u0430 \u043e\u0442"), _money(fin.suggested_min_price)) + "\n"
        + line(ru(r"\u041f\u0440\u0438\u0431\u044b\u043b\u044c \u0441 \u043f\u0440\u043e\u0434\u0430\u0436\u0438"), _money(fin.margin)) + "\n"
        + line(ru(r"\u041e\u043a\u0443\u043f\u0430\u0435\u043c\u043e\u0441\u0442\u044c \u0440\u0430\u0441\u0445\u043e\u0434\u043e\u0432"), f"{fin.roi:.0%}") + "\n\n"
        + f"<b>{ru(r'\u041d\u0430 \u0447\u0442\u043e \u0441\u043c\u043e\u0442\u0440\u0435\u0442\u044c')}</b>\n{alerts_text}\n\n"
        + f"<b>{ru(r'\u0427\u0442\u043e \u0441\u0434\u0435\u043b\u0430\u0442\u044c')}</b>\n{ideas_text}"
    )
    return text, fin, market, alerts

def export_analysis_report(output_path: Path, products: pd.DataFrame, history: pd.DataFrame, forecast: ForecastResult, summary_text: str, fin: FinancialResult, market: dict[str, float | int | str]) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame([
        {"metric": ru(r"\u0418\u043d\u0434\u0435\u043a\u0441"), "value": fin.score},
        {"metric": ru(r"\u041c\u0430\u0440\u0436\u0430"), "value": fin.margin},
        {"metric": "ROI", "value": fin.roi},
        {"metric": ru(r"\u0422\u043e\u0447\u043a\u0430 \u0431\u0435\u0437\u0443\u0431\u044b\u0442\u043e\u0447\u043d\u043e\u0441\u0442\u0438"), "value": fin.break_even_price},
        {"metric": ru(r"\u041c\u0435\u0434\u0438\u0430\u043d\u0430 \u0440\u044b\u043d\u043a\u0430"), "value": market["median_price"]},
        {"metric": ru(r"\u0422\u0435\u043a\u0441\u0442"), "value": summary_text},
    ])
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="summary", index=False)
        products.to_excel(writer, sheet_name="competitors", index=False)
        history.to_excel(writer, sheet_name="history", index=False)
        forecast.future.to_excel(writer, sheet_name="forecast", index=False)
    return output_path


def _load_font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_price_chart(forecast: ForecastResult, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1200, 680
    margin_left, margin_right, margin_top, margin_bottom = 95, 45, 78, 92
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = _load_font(28)
    font = _load_font(18)
    small_font = _load_font(14)
    draw.text((margin_left, 22), ru(r"\u041f\u0440\u043e\u0433\u043d\u043e\u0437 \u0446\u0435\u043d\u044b \u043d\u0430 30 \u0434\u043d\u0435\u0439 \u0441 95% \u0438\u043d\u0442\u0435\u0440\u0432\u0430\u043b\u043e\u043c"), fill=(25, 25, 25), font=title_font)
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    x0, y0 = margin_left, margin_top
    x1, y1 = margin_left + plot_w, margin_top + plot_h
    all_prices = pd.concat([forecast.history["price"], forecast.future["lower"], forecast.future["upper"]]).to_numpy(dtype=float)
    min_price = math.floor(float(all_prices.min()) * 0.96)
    max_price = math.ceil(float(all_prices.max()) * 1.04)
    if min_price == max_price:
        max_price += 1
    draw.rectangle((x0, y0, x1, y1), outline=(190, 190, 190), width=2)
    for step in range(6):
        y = y1 - (plot_h * step / 5)
        price = min_price + (max_price - min_price) * step / 5
        draw.line((x0, y, x1, y), fill=(232, 232, 232), width=1)
        draw.text((10, y - 9), f"{price:,.0f}", fill=(70, 70, 70), font=small_font)
    total_points = len(forecast.history) + len(forecast.future)
    def point(index: int, price: float) -> tuple[float, float]:
        x = x0 + plot_w * index / max(total_points - 1, 1)
        y = y1 - plot_h * (price - min_price) / (max_price - min_price)
        return x, y
    history_points = [point(i, p) for i, p in enumerate(forecast.history["price"].to_numpy(dtype=float))]
    future_offset = len(forecast.history)
    future_points = [point(future_offset + i, p) for i, p in enumerate(forecast.future["price"].to_numpy(dtype=float))]
    lower_points = [point(future_offset + i, p) for i, p in enumerate(forecast.future["lower"].to_numpy(dtype=float))]
    upper_points = [point(future_offset + i, p) for i, p in enumerate(forecast.future["upper"].to_numpy(dtype=float))]
    band = upper_points + list(reversed(lower_points))
    if len(band) >= 3:
        overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
        ImageDraw.Draw(overlay).polygon(band, fill=(44, 160, 44, 45))
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(image)
    if len(history_points) > 1:
        draw.line(history_points, fill=(214, 39, 40), width=4)
    if history_points and future_points:
        draw.line([history_points[-1], future_points[0]], fill=(44, 160, 44), width=3)
    if len(future_points) > 1:
        draw.line(future_points, fill=(44, 160, 44), width=4)
    if len(lower_points) > 1:
        draw.line(lower_points, fill=(118, 185, 118), width=2)
        draw.line(upper_points, fill=(118, 185, 118), width=2)
    for x, y in future_points[::5]:
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(44, 160, 44))
    draw.text((x0, y1 + 18), forecast.history["date"].iloc[0].strftime("%d.%m"), fill=(70, 70, 70), font=small_font)
    draw.text((x1 - 60, y1 + 18), forecast.future["date"].iloc[-1].strftime("%d.%m"), fill=(70, 70, 70), font=small_font)
    draw.line((x0 + 10, height - 35, x0 + 60, height - 35), fill=(214, 39, 40), width=4)
    draw.text((x0 + 70, height - 46), ru(r"\u0418\u0441\u0442\u043e\u0440\u0438\u044f 6 \u043c\u0435\u0441."), fill=(40, 40, 40), font=font)
    draw.line((x0 + 250, height - 35, x0 + 300, height - 35), fill=(44, 160, 44), width=4)
    draw.text((x0 + 310, height - 46), ru(r"\u041f\u0440\u043e\u0433\u043d\u043e\u0437 30 \u0434\u043d."), fill=(40, 40, 40), font=font)
    draw.rectangle((x0 + 520, height - 42, x0 + 570, height - 28), fill=(218, 240, 218), outline=(118, 185, 118))
    draw.text((x0 + 580, height - 46), ru(r"95% \u0438\u043d\u0442\u0435\u0440\u0432\u0430\u043b"), fill=(40, 40, 40), font=font)
    image.save(output_path, format="PNG")
    return output_path
